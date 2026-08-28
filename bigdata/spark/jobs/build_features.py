"""
Issue 11 — company-level feature matrix + yearly trajectory, for the
Isolation Forest model in ai/train_isolation_forest.py.

Reads fact_award_company + market_stats (Issue 9/10 outputs), reuses
build_statistics.py's plausibility-filter pipeline and amount aggregation
rather than re-implementing them (same two-session split to avoid the
UDF-session-instability documented there — see collect_implausible_company_ids()).

Two limitations measured before coding this job, not guessed:

1. `amount_variation` (écart offre retenue vs autres offres / vs estimation
   administrative) is NOT included — confirmed not calculable on this
   corpus. `montant_par_concurrent`/`classement` (Award) are 0/454
   populated, never extracted by Issue 7 (see database/crud/awards.py's
   own docstring). `estimation_dhs_ttc` is 0/454 for Award-linked
   Procurement — matches docs/ideas.md Sec 2.6's already-measured,
   already-retired decision: the estimation and the final amount never
   coexist for the same market on this portal (a market with a PV never
   has an estimation left over from its consultation page). Rattrapage
   possible only via a streaming collection over months, out of scope for
   a 15-day sprint (same doc).

2. A real extraction gap on the winner's amount: 98/211 (Award, Company)
   links have NEITHER montant_ht NOR montant_ttc (statut=ATTRIBUE, not
   the structurally-expected INFRUCTUEUX case where no amount exists by
   construction) — 92/200 Company have zero amount data on BOTH bases as
   a direct consequence, purely from this extraction gap. Amount-derived
   features are median-imputed (median of companies WITH that base, never
   0 — 0 would look like an extreme value, not a neutral one) with a
   companion `has_ttc_data`/`has_ht_data` boolean, so downstream models
   don't mistake "extraction gap" for "anomalously inactive company".
   TTC is the primary monetary signal fed to Isolation Forest (94/211
   links vs 19/211 for HT) — HT columns stay in this feature table for
   traceability but are not model inputs (ai/train_isolation_forest.py).

A third, smaller finding while building `concurrents_ecartes_rate`:
concurrents_ecartes (never validated against ground truth either) carries
the same extraction-noise character as concurrent_retenu once did
(caption/boilerplate fragments like "techniques :", "additifs :" rather
than real names) — reuses extraction/company_name.py::clean_company_candidate
and database/normalization.py::normalize_company_name (already built and
tuned for exactly this kind of noise ; _looks_implausible, cite ici avant
le 27/08/2026, a ete supprime avec ses quatre listes de rejet) to keep only plausible entries
before counting an award as having a real exclusion — measured: 215/454
non-empty raw, 178/454 with at least one plausible name.

    python -m bigdata.spark.jobs.build_features
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from pyspark.sql import functions as F  # noqa: E402

from bigdata.spark.jobs.build_statistics import (  # noqa: E402
    FACT_TABLE_PATH, MARKET_STATS_PATH, _drop_implausible_companies,
    _with_groupement_size, build_company_stats_global,
    collect_implausible_company_ids,
)
from bigdata.spark.session import get_spark_session  # noqa: E402
from extraction.company_name import clean_company_candidate  # noqa: E402
from database.crud.counts import (  # noqa: E402
    awards_with_company_count, check_against_database, company_count,
)
from database.normalization import normalize_company_name  # noqa: E402

COMPANY_FEATURES_PATH = REPO / "data/processed/analytics/company_features"
COMPANY_YEARLY_TRAJECTORY_PATH = REPO / "data/processed/analytics/company_yearly_trajectory"



def _has_plausible_exclusion(entries) -> bool | None:
    """Un award a une VRAIE exclusion de concurrent si au moins une entree
    de concurrents_ecartes survit au filtre de plausibilite deja construit
    pour Company (meme bruit de legende/fragment, meme filtre reutilise —
    voir la docstring du module).

    TROIS valeurs de retour, plus deux (corrige le 28/08/2026) :

      None  — la rubrique "concurrents ecartes" est absente du document.
              On ne sait pas s'il y a eu des exclusions. 239/454 Award.
      False — la rubrique existe et aucune entree n'est un nom plausible :
              aucune exclusion, REELLEMENT observee.
      True  — au moins une exclusion nommee.

    L'ancien `if entries is None: return False` faisait dire au pipeline
    "aucune exclusion" pour plus de la moitie du corpus alors que le
    document ne disait rien. La moyenne qui en decoule
    (concurrents_ecartes_rate) etait donc tiree vers 0 par un trou
    d'extraction, pas par une pratique d'achat.
    """
    if entries is None:
        return None
    for raw in entries:
        if raw is None:
            continue
        cleaned = clean_company_candidate(raw)
        if cleaned and normalize_company_name(cleaned):
            return True
    return False


def _load_clean_award_level(spark, excluded_company_ids: list):
    """Fact + market_stats, joints au grain Award, filtre de plausibilite
    Company deja applique. `excluded_company_ids` doit venir d'un appel a
    collect_implausible_company_ids() fait AVANT get_spark_session() pour
    cette session principale — meme contrainte a deux sessions que
    build_statistics.py::main() (une seule session ne doit jamais faire
    plus d'un appel UDF ; collect_implausible_company_ids() est le seul
    appel UDF de tout ce module, et il tourne dans sa propre session
    courte, jamais celle-ci)."""
    fact_raw = spark.read.parquet(str(FACT_TABLE_PATH))
    fact = _drop_implausible_companies(fact_raw, excluded_company_ids)
    fact = _with_groupement_size(fact)

    market = spark.read.parquet(str(MARKET_STATS_PATH))
    award_level = (
        fact.filter(F.col("company_id").isNotNull())
        .join(market.select("award_id", "number_of_bidders_filtered"), on="award_id", how="left")
    )
    return award_level


def build_company_features(award_level):
    """Matrice par entreprise — DESCRIPTIVE depuis le 28/08/2026, plus une
    entree de modele.

    Le modele principal est passe au grain MARCHE
    (bigdata/spark/jobs/build_market_features.py) : 180/193 entreprises
    n'ont qu'un seul marche, donc tout "taux" par entreprise est une
    observation unique deguisee en frequence, et Isolation Forest apprenait
    surtout la profondeur de presence dans le corpus (13/13 des entreprises
    a 2 marches signalees anormales contre 25/180 de celles a 1 marche).
    Ce que ce job produit sert desormais a decrire et regrouper APRES la
    detection, jamais a la piloter.

    Les taux sont calcules sur les seuls marches ou l'information EXISTE, et
    accompagnes de leur denominateur (`n_awards_with_*`) : une moyenne sur
    2 marches renseignes n'a pas le meme poids qu'une moyenne sur 2 marches
    dont 1 inconnu, et l'ancien code ne permettait pas de faire la
    difference.

    groupement_rate et les deux pentes de tendance ne sont plus calcules ici
    (support mesure : 2/193 et 3/193). L'information groupement existe
    desormais au grain marche, la ou elle est reellement observee.
    """
    amount_stats = build_company_stats_global(award_level)

    # `number_of_bidders_filtered` est NULL quand le document ne porte pas de
    # rubrique concurrents. F.avg ignore les NULL, donc le taux porte sur les
    # seuls marches renseignes — et le compte de ces marches est conserve a
    # cote pour que l'aval puisse juger de la solidite du taux.
    single_bidder = award_level.groupBy("company_id").agg(
        F.avg((F.col("number_of_bidders_filtered") <= 1).cast("double"))
            .alias("single_bidder_rate"),
        F.count("number_of_bidders_filtered").alias("n_awards_with_competitor_data"),
    )

    per_award = award_level.select("company_id", "award_id", "concurrents_ecartes").dropDuplicates(
        ["company_id", "award_id"])
    pdf = per_award.toPandas()
    # None (rubrique absente) reste None et sera ignore par la moyenne ;
    # False (rubrique presente, aucune exclusion) compte bien pour 0.
    pdf["_has_exclusion"] = pdf["concurrents_ecartes"].apply(_has_plausible_exclusion)
    known = pdf.dropna(subset=["_has_exclusion"]).copy()
    known["_has_exclusion"] = known["_has_exclusion"].astype(float)
    ecartes_rate = (
        known.groupby("company_id")["_has_exclusion"]
        .agg(concurrents_ecartes_rate="mean", n_awards_with_exclusion_data="size")
        .reset_index()
    )
    # Une entreprise dont AUCUN marche ne renseigne la rubrique disparait du
    # groupby : le join a gauche ci-dessous lui laisse un taux NULL (inconnu),
    # ce qui est le resultat correct — jamais 0.
    spark = award_level.sparkSession
    ecartes_rate_df = spark.createDataFrame(ecartes_rate) if len(ecartes_rate) else None

    features = (
        amount_stats
        .join(single_bidder, on="company_id", how="left")
        .withColumn("has_ttc_data", F.col("n_with_ttc") > 0)
        .withColumn("has_ht_data", F.col("n_with_ht") > 0)
    )
    if ecartes_rate_df is not None:
        features = features.join(ecartes_rate_df, on="company_id", how="left")
    else:
        features = (features
                    .withColumn("concurrents_ecartes_rate", F.lit(None).cast("double"))
                    .withColumn("n_awards_with_exclusion_data", F.lit(0)))
    features = features.fillna({"n_awards_with_exclusion_data": 0})
    return features


def build_yearly_trajectory(award_level):
    """{company_id, annee} -> comptages annuels observes, sans extrapolation.

    Collecte en pandas parce que la table est minuscule (~193 entreprises x
    <= 4 annees) ; aucun besoin de paralleliser."""
    by_year = award_level.groupBy("company_id", "company_normalized_name", "annee").agg(
        F.count("award_id").alias("number_of_awards_by_year"),
        F.avg((F.col("number_of_bidders_filtered") <= 1).cast("double")).alias("single_bidder_rate_by_year"),
        F.sum("montant_ht").alias("total_amount_ht_by_year"),
        F.sum("montant_ttc").alias("total_amount_ttc_by_year"),
    )
    pdf = by_year.toPandas()

    # Les deux pentes de regression (single_bidder_rate_trend_slope,
    # number_of_awards_trend_slope) ne sont PLUS calculees ici — retirees le
    # 28/08/2026. Support mesure : 3/193 entreprises seulement avaient les
    # >= 2 points annuels (2023-2025) qu'une pente exige. Les 190 autres
    # recevaient None, puis 0.0 par imputation a l'entree du modele, ce qui
    # revient a affirmer "tendance plate mesuree" pour 98,4 % du corpus.
    # Le comptage annuel brut, lui, reste ecrit : il est observe, pas
    # extrapole, et redeviendra une base de tendance quand le corpus sera
    # assez profond.
    return pdf


def main() -> int:
    dropped_companies = collect_implausible_company_ids(FACT_TABLE_PATH)
    excluded_company_ids = [row["company_id"] for row in dropped_companies]

    spark = get_spark_session()
    try:
        award_level = _load_clean_award_level(spark, excluded_company_ids).cache()
        award_level.count()

        features = build_company_features(award_level)
        yearly_pdf = build_yearly_trajectory(award_level)

        features_pdf = features.toPandas()

        n_companies = len(features_pdf)
        n_awards_total = award_level.select("award_id").distinct().count()
        check_against_database(n_companies, company_count(),
                               "Company dans la matrice de features")
        check_against_database(n_awards_total, awards_with_company_count(),
                               "Award (avec compagnie) couverts")
        print("OK : recoupement confirme contre la base.")

        n_has_ttc = features_pdf["has_ttc_data"].sum()
        n_has_ht = features_pdf["has_ht_data"].sum()
        n_neither = ((~features_pdf["has_ttc_data"]) & (~features_pdf["has_ht_data"])).sum()
        print(f"\nCompany avec au moins un montant TTC : {n_has_ttc}/{n_companies}")
        print(f"Company avec au moins un montant HT  : {n_has_ht}/{n_companies}")
        print(f"Company SANS aucun montant (ni HT ni TTC) : {n_neither}/{n_companies}")
        print("  NOTE : trou d'extraction mesure (98/211 liens Award-Company"
              " ATTRIBUE sans montant), pas une absence d'activite reelle —"
              " voir la docstring de ce module. Imputation median + flag"
              " has_ttc_data geree dans ai/train_isolation_forest.py, pas ici"
              " (ce fichier n'ecrit que les valeurs mesurees, jamais imputees).")
        print(f"  Rappel : 8,8% de bruit pur + 7,4% de noms contamines dans"
              f" Company (audit du 27/08/2026, bigdata/README.md) — ce compte"
              f" de {n_companies} n'est pas un nombre exact d'entreprises reelles.")

        example = features_pdf[features_pdf["company_normalized_name"] == "TECTRA"]
        print(f"\n=== exemple concret : TECTRA ===")
        print(example.to_string(index=False))

        COMPANY_FEATURES_PATH.parent.mkdir(parents=True, exist_ok=True)
        features_pdf.to_parquet(COMPANY_FEATURES_PATH.with_suffix(".parquet"), index=False)
        yearly_pdf.to_parquet(COMPANY_YEARLY_TRAJECTORY_PATH.with_suffix(".parquet"), index=False)
        print(f"\nEcrit : {COMPANY_FEATURES_PATH.with_suffix('.parquet')}")
        print(f"Ecrit : {COMPANY_YEARLY_TRAJECTORY_PATH.with_suffix('.parquet')}")
    finally:
        spark.stop()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
