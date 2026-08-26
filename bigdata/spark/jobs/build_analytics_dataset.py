"""
Issue 9 — read Procurement/Award/Company/Document from PostgreSQL, join into
one analytical fact table, write Parquet to data/processed/analytics/.

Grain: one row per (Award, Company) pair. LEFT JOIN throughout, never INNER
— an INFRUCTUEUX/OFFRE_EXCESSIVE lot with zero linked companies still gets
exactly one row (company columns NULL), never silently dropped; an Award
whose Procurement join failed (structurally possible via Document.join_status
== REF_CONSULTATION_NOT_FOUND, even though 0/454 currently) keeps its row
with acheteur/annee columns NULL rather than disappearing.

    python -m bigdata.spark.jobs.build_analytics_dataset
    python -m bigdata.spark.jobs.build_analytics_dataset --database-url postgresql://...
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from pyspark.sql import functions as F  # noqa: E402

from bigdata.spark.session import get_spark_session, read_table  # noqa: E402

OUTPUT_DIR = REPO / "data/processed/analytics/fact_award_company"


def build_fact_table(spark, database_url: str | None = None):
    awards = read_table(spark, "awards", database_url)
    companies = read_table(spark, "companies", database_url)
    procurements = read_table(spark, "procurements", database_url)
    award_companies = read_table(spark, "award_companies", database_url)

    # Award -> award_companies -> Company : LEFT JOIN twice, deliberately.
    # An Award with 0 linked companies (no winner extracted, or the winner
    # was rejected by the Company plausibility filter) must keep its row —
    # dropping it would silently erase every INFRUCTUEUX/OFFRE_EXCESSIVE lot
    # from this dataset, which Issue 10's red-flag analysis needs to see.
    award_company_links = (
        awards.join(award_companies, awards.id == award_companies.award_id, "left")
        .join(companies, award_companies.company_id == companies.id, "left")
    )

    # Award -> Procurement : also LEFT JOIN. Currently 0/454 Award rows have
    # a null procurement_id (every Award traces to a Pass-A PV document, and
    # 100% of those currently resolve their Procurement join — confirmed by
    # checking, not assumed) — but Document.join_status ==
    # REF_CONSULTATION_NOT_FOUND is a real, if currently zero-instance, case
    # this join must survive without dropping the Award row.
    fact = award_company_links.join(
        procurements, award_company_links.procurement_id == procurements.id, "left"
    )

    return fact.select(
        awards.id.alias("award_id"),
        awards.doc_id,
        awards.lot_numero,
        award_company_links.ref_consultation,
        awards.reference.alias("award_reference"),
        awards.statut,
        # HT et TTC jamais fusionnes, jamais l'un derive de l'autre par un
        # taux de TVA suppose — data_dictionary.md Sec 3.6, absolu depuis
        # Issue 7-8. Toute agregation future qui a besoin d'une seule base
        # doit choisir explicitement laquelle (voir docstring du module) et
        # documenter combien de lignes elle ecarte faute de cette base.
        awards.montant_ht,
        awards.montant_ttc,
        awards.montant_base_affichee,
        awards.date_ouverture_plis,
        awards.date_achevement_travaux_commission,
        awards.lot_detection,
        awards.extraction_warnings,
        # Ajoute pour Issue 10 (number_of_bidders) — non valide contre une
        # verite terrain (Issue 7), mesure separement au niveau du job de
        # statistiques plutot que suppose fiable ici.
        awards.liste_concurrents,
        # Ajoute pour Issue 11 (red flag "exclusion de concurrents",
        # docs/ideas.md Sec 2.6) — meme statut non valide que
        # liste_concurrents ci-dessus, mesure au niveau du job de features.
        awards.concurrents_ecartes,
        companies.id.alias("company_id"),
        # Deja normalise en amont (database/normalization.py, Issue 8) —
        # lu tel quel ici, jamais renormalise.
        companies.normalized_name.alias("company_normalized_name"),
        companies.display_name.alias("company_display_name"),
        procurements.acheteur_public,
        procurements.objet,
        procurements.categorie_principale,
        procurements.mode_passation,
        # Copie telle quelle depuis Procurement, jamais recalculee depuis
        # une date d'Award — c'est le mecanisme qui satisfait l'exigence de
        # distinguer les deux sources d'annee (voir docstring du module et
        # database/README.md pour le piege "2024 Passe B concentre a 92%
        # en decembre").
        procurements.annee,
        procurements.annee_source,
        procurements.estimation_dhs_ttc,
    )


def validate(spark, fact_df, database_url: str | None = None) -> None:
    """Recoupe le compte de lignes en sortie contre les comptages deja
    etablis en base plutot que de supposer que la jointure s'est bien
    passee."""
    awards = read_table(spark, "awards", database_url)
    award_companies = read_table(spark, "award_companies", database_url)

    total_awards = awards.count()
    total_links = award_companies.count()
    awards_with_company = award_companies.select("award_id").distinct().count()
    awards_without_company = total_awards - awards_with_company
    expected_rows = total_links + awards_without_company

    actual_rows = fact_df.count()

    print(f"Award (base)                    : {total_awards}")
    print(f"liens award_companies (base)    : {total_links}")
    print(f"Award avec >=1 compagnie        : {awards_with_company}")
    print(f"Award sans compagnie            : {awards_without_company}")
    print(f"lignes attendues (LEFT JOIN)    : {expected_rows}")
    print(f"lignes reelles en sortie        : {actual_rows}")
    if actual_rows != expected_rows:
        raise RuntimeError(
            f"lignes en sortie ({actual_rows}) != attendu ({expected_rows}) — "
            "diagnostiquer avant de continuer, ne pas supposer que c'est normal.")
    print("OK : recoupement confirme.")

    distinct_companies = fact_df.filter(F.col("company_id").isNotNull()) \
        .select("company_id").distinct().count()
    print(f"\nEntreprises distinctes dans le dataset : {distinct_companies}")
    print("  NOTE : ~20% de bruit residuel dans Company malgre le filtre de")
    print("  plausibilite (database/crud/companies.py) — ce chiffre n'est PAS")
    print("  un compte exact d'entreprises reelles. Voir database/README.md.")

    awards_no_company = fact_df.filter(F.col("company_id").isNull()).count()
    print(f"\nLignes Award sans compagnie liee : {awards_no_company}")
    print("  (INFRUCTUEUX/OFFRE_EXCESSIVE, ou vainqueur rejete par le filtre")
    print("  de plausibilite Company — pas des lignes orphelines a corriger)")

    no_procurement = fact_df.filter(F.col("acheteur_public").isNull()).count()
    print(f"\nLignes sans Procurement resolu (acheteur_public NULL) : {no_procurement}")
    print("  Nullable par construction (Document.join_status) — pas une erreur.")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--database-url", default=None)
    args = ap.parse_args()

    spark = get_spark_session()
    try:
        fact = build_fact_table(spark, args.database_url)
        validate(spark, fact, args.database_url)

        OUTPUT_DIR.parent.mkdir(parents=True, exist_ok=True)
        fact.write.mode("overwrite").parquet(str(OUTPUT_DIR))
        print(f"\nEcrit : {OUTPUT_DIR}")
    finally:
        spark.stop()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
