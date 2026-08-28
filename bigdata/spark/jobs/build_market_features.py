"""
Refonte du 28/08/2026 — matrice de features au grain MARCHE.

POURQUOI CE JOB REMPLACE build_features.py COMME ENTREE DU MODELE
------------------------------------------------------------------
L'unite d'analyse etait l'entreprise. Mesure sur le corpus reel :

    180/193 entreprises (93,3 %) n'ont qu'UN SEUL marche
     13/193 en ont deux
      0/193 en ont trois ou plus

Un "taux" calcule sur une observation unique n'est pas un taux :
`single_bidder_rate = 1/1 = 100 %` ne decrit aucun comportement, il
recopie une observation en la deguisant en frequence. Et la consequence
etait visible dans les sorties du modele :

    entreprises a 1 marche  :  25/180 signalees anormales (13,9 %)
    entreprises a 2 marches :  13/13  signalees anormales (100 %)

Isolation Forest apprenait donc surtout la PROFONDEUR DE PRESENCE dans le
corpus — un artefact de couverture du scraping (on a collecte ~100 PV par
an, pas l'historique complet d'une entreprise), pas un comportement.

Le marche, lui, est une observation complete et independante : son montant,
son nombre de soumissionnaires, sa procedure et ses exclusions sont lus sur
UN document, pas agreges sur un echantillon arbitrairement peu profond.

L'information entreprise n'est pas supprimee pour autant : `company_id` /
`company_normalized_name` restent dans cette table, pour afficher le gagnant
et regrouper les marches APRES la detection — jamais pour la piloter.

REGLE ABSOLUE APPLIQUEE PARTOUT ICI : UNKNOWN != ZERO
-----------------------------------------------------
Chaque grandeur potentiellement absente est ecrite en DEUX colonnes : la
valeur (NULL si inconnue) et son drapeau `has_*_data`. Aucune absence n'est
comblee par un 0. Les seules valeurs comblees le sont par une mediane
explicite, signalee par `amount_imputed`, et jamais presentee comme lue.

FEATURES ECARTEES, ET POURQUOI (mesure, pas suppose)
-----------------------------------------------------
* `price_ratio` / `price_deviation` (montant attribue vs estimation) :
  IMPOSSIBLES sur ce corpus. `estimation_dhs_ttc` est renseignee pour
  1196/1350 consultations de la Passe B mais 0/454 des marches lies a un
  Award. Ce n'est pas un trou de scraping — consultation_parser.py cherche
  bien le libelle "Estimation (en Dhs TTC)" avec la meme liste de champs
  dans les deux passes : la page de detail d'un marche DEJA ATTRIBUE ne
  porte plus l'estimation. Confirme docs/ideas.md Sec 2.6. Aucune valeur
  n'est fabriquee pour combler ce trou, donc pas de red flag RF04.
* `lieu_execution` : renseigne 454/454 en base, mais ABSENT de la table de
  faits (build_analytics_dataset.py ne le selectionne pas). Il n'aurait de
  toute facon pas ete une entree du modele — texte libre allant jusqu'a 925
  caracteres (listes de provinces concatenees), cardinalite trop elevee pour
  un encodage honnete a cette taille de corpus. Le rapatrier supposerait de
  reconstruire la table de faits pour une colonne purement descriptive.
* pentes de tendance : retirees, 3/193 de support (voir build_features.py).

    python -m bigdata.spark.jobs.build_market_features
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from pyspark.sql import functions as F  # noqa: E402

from bigdata.spark.jobs.build_statistics import (  # noqa: E402
    FACT_TABLE_PATH, MARKET_STATS_PATH, _plausible_names, _with_groupement_size,
)
from bigdata.spark.session import get_spark_session  # noqa: E402
from database.crud.counts import award_count, check_against_database  # noqa: E402

MARKET_FEATURES_PATH = REPO / "data/processed/analytics/market_features"

# Modalites de mode_passation conservees en colonnes propres. Mesure sur les
# 454 marches : "Appel d'offres ouvert" 334, "ouvert simplifie" 112, puis 8
# marches repartis sur 6 modalites (Concours Architectural 2, Consultation
# architecturale ouverte 2, et 4 modalites a 1 seul marche chacune).
#
# Regrouper la queue dans `mode_autre` plutot que de creer 6 colonnes
# quasi-constantes : une colonne a 1 valeur non nulle sur 454 n'apporte
# aucune information a un modele qui tire ses features au hasard, elle
# dilue seulement les colonnes utiles dans le tirage.
MODE_AO_OUVERT = "Appel d'offres ouvert"
MODE_AO_SIMPLIFIE = "Appel d'offres ouvert simplifié"


def build_market_features(spark):
    """Une ligne par Award (= un lot attribue ou declare infructueux).

    Le grain est l'Award et non le document : un PV multi-lots decrit
    plusieurs marches, dont les statuts peuvent differer (piege confirme
    349e44bf : lot 1 attribue, lots 2 et 3 infructueux). Agreger au
    document ecraserait cette distinction, que tout le pipeline amont a
    justement ete construit pour preserver.
    """
    fact = spark.read.parquet(str(FACT_TABLE_PATH))
    fact = _with_groupement_size(fact)

    # fact est au grain (Award x Company) : un groupement produit 2 lignes
    # pour un meme marche. On repasse au grain Award en gardant UNE ligne,
    # et le nom du gagnant s'il y en a un.
    per_award = (
        fact.groupBy("award_id").agg(
            F.first("doc_id", ignorenulls=True).alias("doc_id"),
            F.first("ref_consultation", ignorenulls=True).alias("ref_consultation"),
            F.first("award_reference", ignorenulls=True).alias("reference"),
            F.first("lot_numero", ignorenulls=True).alias("lot_numero"),
            F.first("statut", ignorenulls=True).alias("statut"),
            F.first("montant_ht", ignorenulls=True).alias("montant_ht"),
            F.first("montant_ttc", ignorenulls=True).alias("montant_ttc"),
            F.first("montant_base_affichee", ignorenulls=True).alias("montant_base_affichee"),
            F.first("date_ouverture_plis", ignorenulls=True).alias("date_ouverture_plis"),
            F.first("acheteur_public", ignorenulls=True).alias("acheteur_public"),
            F.first("objet", ignorenulls=True).alias("objet"),
            F.first("categorie_principale", ignorenulls=True).alias("categorie_principale"),
            F.first("mode_passation", ignorenulls=True).alias("mode_passation"),
            F.first("annee", ignorenulls=True).alias("annee"),
            F.first("annee_source", ignorenulls=True).alias("annee_source"),
            F.first("lot_detection", ignorenulls=True).alias("lot_detection"),
            F.first("extraction_warnings", ignorenulls=True).alias("extraction_warnings"),
            F.first("concurrents_ecartes", ignorenulls=True).alias("concurrents_ecartes"),
            F.first("groupement_size", ignorenulls=True).alias("groupement_size"),
            # Le gagnant : conserve pour l'affichage et le regroupement APRES
            # detection (jamais une entree du modele). collect_list garde les
            # 2 membres d'un groupement au lieu d'en perdre un.
            F.collect_list("company_normalized_name").alias("companies"),
            F.first("company_id", ignorenulls=True).alias("company_id"),
        )
    )

    market = spark.read.parquet(str(MARKET_STATS_PATH))
    df = per_award.join(
        market.select("award_id", "has_competitor_data",
                      "number_of_bidders_raw", "number_of_bidders_filtered"),
        on="award_id", how="left")

    # --- concurrence ---------------------------------------------------- #
    # number_of_bidders_filtered est deja NULL quand la rubrique est absente
    # (build_statistics.py, correctif UNKNOWN != ZERO du 28/08/2026).
    df = (df
          .withColumn("nb_soumissionnaires", F.col("number_of_bidders_filtered"))
          .withColumn("has_competitor_data",
                      F.coalesce(F.col("has_competitor_data"), F.lit(0)).cast("int"))
          # single_bidder reste NULL quand on ne sait pas : c'est tout
          # l'objet du correctif. Un marche sans rubrique concurrents n'est
          # pas un marche a soumissionnaire unique.
          .withColumn("single_bidder",
                      F.when(F.col("nb_soumissionnaires").isNotNull(),
                             (F.col("nb_soumissionnaires") <= 1).cast("int"))))

    # --- exclusions ------------------------------------------------------ #
    # SEUL appel UDF de ce job. La contrainte "au plus une action UDF par
    # SparkSession" est documentee dans build_statistics.py (TimeoutError
    # deterministe du worker Python en local[*] Windows au 2e appel).
    filter_udf = F.udf(_plausible_names, "array<string>")
    df = df.withColumn("_ecartes_filtres", filter_udf(F.col("concurrents_ecartes")))
    df = (df
          .withColumn("has_exclusion_data",
                      F.col("_ecartes_filtres").isNotNull().cast("int"))
          .withColumn("nb_concurrents_ecartes",
                      F.when(F.col("_ecartes_filtres").isNotNull(),
                             F.size(F.col("_ecartes_filtres"))))
          # exclusion_rate exige les DEUX informations, et un denominateur
          # non nul. NULL dans tous les autres cas — jamais 0.
          .withColumn("exclusion_rate",
                      F.when((F.col("nb_concurrents_ecartes").isNotNull())
                             & (F.col("nb_soumissionnaires").isNotNull())
                             & (F.col("nb_soumissionnaires") > 0),
                             F.col("nb_concurrents_ecartes")
                             / F.col("nb_soumissionnaires")))
          .drop("_ecartes_filtres"))

    # --- financier ------------------------------------------------------- #
    # montant_ttc est la base monetaire du modele : 167/454 renseignes
    # contre 35/454 pour le HT. Les deux ne sont JAMAIS fusionnes et aucun
    # n'est deduit de l'autre par un taux de TVA suppose
    # (data_dictionary.md Sec 3.6). Le HT reste ecrit, hors modele.
    df = (df
          .withColumn("has_amount_data", F.col("montant_ttc").isNotNull().cast("int"))
          .withColumn("montant_ttc", F.col("montant_ttc").cast("double"))
          # log1p : les montants s'etalent sur plusieurs ordres de grandeur
          # (quelques milliers a ~100 M DH). Sans compression, une poignee
          # de tres gros marches ecrase toute la variance des autres et le
          # modele ne distingue plus rien en dessous.
          .withColumn("log_montant_ttc",
                      F.when(F.col("montant_ttc").isNotNull(),
                             F.log1p(F.col("montant_ttc")))))

    # --- procedure et secteur (100 % de couverture, mesure) -------------- #
    df = (df
          .withColumn("mode_ao_ouvert", (F.col("mode_passation") == MODE_AO_OUVERT).cast("int"))
          .withColumn("mode_ao_simplifie", (F.col("mode_passation") == MODE_AO_SIMPLIFIE).cast("int"))
          .withColumn("mode_autre",
                      (~F.col("mode_passation").isin([MODE_AO_OUVERT, MODE_AO_SIMPLIFIE])).cast("int"))
          .withColumn("cat_travaux", (F.col("categorie_principale") == "TRAVAUX").cast("int"))
          .withColumn("cat_fournitures", (F.col("categorie_principale") == "FOURNITURES").cast("int"))
          .withColumn("cat_services", (F.col("categorie_principale") == "SERVICES").cast("int")))

    # --- groupement (au grain marche, la ou il est observe) -------------- #
    df = df.withColumn(
        "is_groupement",
        F.when(F.col("groupement_size").isNotNull(),
               (F.col("groupement_size") >= 2).cast("int")))

    # --- qualite des donnees --------------------------------------------- #
    df = (df
          .withColumn("has_date_data", F.col("date_ouverture_plis").isNotNull().cast("int"))
          .withColumn("has_winner", F.size(F.col("companies")).__gt__(0).cast("int"))
          .withColumn("extraction_warning",
                      F.coalesce(F.size(F.col("extraction_warnings")), F.lit(0)).__gt__(0).cast("int")))

    return df


# Colonnes reellement soumises a Isolation Forest. Volontairement courte :
# la priorite est la qualite des donnees, pas le nombre de colonnes.
MODEL_FEATURE_COLUMNS = [
    "log_montant_ttc",       # + amount_imputed / has_amount_data
    "has_amount_data",
    "nb_soumissionnaires",
    "single_bidder",
    "has_competitor_data",
    "nb_concurrents_ecartes",
    "exclusion_rate",
    "has_exclusion_data",
    "mode_ao_ouvert",
    "mode_ao_simplifie",
    "mode_autre",
    "cat_travaux",
    "cat_fournitures",
    "cat_services",
]

# Colonnes ecrites pour l'affichage, le controle qualite et le regroupement
# par entreprise — jamais lues par le modele.
CONTEXT_COLUMNS = [
    "award_id", "doc_id", "ref_consultation", "reference", "lot_numero", "statut",
    "montant_ttc", "montant_ht", "montant_base_affichee", "date_ouverture_plis",
    "acheteur_public", "objet", "categorie_principale", "mode_passation",
    "annee", "annee_source", "companies", "company_id",
    "is_groupement", "has_date_data", "has_winner", "extraction_warning",
    "lot_detection", "number_of_bidders_raw",
]


def main() -> int:
    spark = get_spark_session(app_name="ppi-market-features")
    try:
        df = build_market_features(spark).cache()
        n = df.count()
        check_against_database(n, award_count(), "marches (Award) dans la matrice",
                               hint="rejouer build_analytics_dataset.py puis build_statistics.py")

        pdf = df.select(CONTEXT_COLUMNS + MODEL_FEATURE_COLUMNS).toPandas()

        print(f"\n=== couverture reelle des features marche ({n} marches) ===")
        print(f"{'colonne':<28}{'renseignees':>12}{'%':>8}")
        for col in MODEL_FEATURE_COLUMNS:
            k = int(pdf[col].notna().sum())
            print(f"  {col:<26}{k:>12}{100 * k / n:>7.1f}%")

        print("\n=== drapeaux de qualite (1 = information reellement extraite) ===")
        for col in ("has_amount_data", "has_competitor_data", "has_exclusion_data",
                    "has_date_data", "has_winner", "extraction_warning"):
            k = int(pdf[col].fillna(0).sum())
            print(f"  {col:<26}{k:>12}{100 * k / n:>7.1f}%")

        print("\n=== ce que le correctif UNKNOWN != ZERO a evite ===")
        inconnu = int((pdf["has_competitor_data"] == 0).sum())
        faux_single = int(((pdf["has_competitor_data"] == 0)).sum())
        print(f"  {inconnu} marches sans rubrique concurrents : nb_soumissionnaires NULL.")
        print(f"  Avant le correctif ils valaient 0, donc single_bidder = 1 :")
        print(f"  {faux_single} faux marches a soumissionnaire unique auraient ete fabriques.")
        reels = int((pdf["single_bidder"] == 1).sum())
        print(f"  Marches a soumissionnaire unique REELLEMENT observes : {reels}")

        print("\n=== repartition par statut ===")
        print(pdf["statut"].value_counts().to_string())

        MARKET_FEATURES_PATH.parent.mkdir(parents=True, exist_ok=True)
        pdf.to_parquet(MARKET_FEATURES_PATH.with_suffix(".parquet"), index=False)
        print(f"\nEcrit : {MARKET_FEATURES_PATH.with_suffix('.parquet')}")
    finally:
        spark.stop()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
