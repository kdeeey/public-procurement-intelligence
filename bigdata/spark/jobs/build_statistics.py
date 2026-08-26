"""
Issue 10 — per-company and per-market statistics from fact_award_company.

Reads the Parquet dataset Issue 9 wrote (not PostgreSQL directly — that
dataset is already the single analytical source of truth going forward),
aggregates, writes three new Parquet datasets to data/processed/analytics/.

Scope, confirmed with the user before coding: AWARDED markets only. No
participation/win rate — that needs a denominator of total consultations
the PV-only corpus does not carry (see bigdata/README.md).

    python -m bigdata.spark.jobs.build_statistics
"""

from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(REPO))

from pyspark.sql import functions as F  # noqa: E402

from bigdata.spark.session import get_spark_session  # noqa: E402
from database.crud.companies import MAX_PLAUSIBLE_NAME_LENGTH, _looks_implausible  # noqa: E402
from database.normalization import normalize_company_name  # noqa: E402

FACT_TABLE_PATH = REPO / "data/processed/analytics/fact_award_company"
COMPANY_STATS_BY_ACHETEUR_PATH = REPO / "data/processed/analytics/company_stats_by_acheteur"
COMPANY_STATS_GLOBAL_PATH = REPO / "data/processed/analytics/company_stats_global"
MARKET_STATS_PATH = REPO / "data/processed/analytics/market_stats"


def _is_implausible_name(name: str | None) -> bool:
    return bool(name) and _looks_implausible(name)


def _is_implausible_col(col):
    # F.udf() needs an active SparkContext — this module is imported before
    # get_spark_session() runs in main(), so a module-level call fails with
    # SESSION_OR_CONTEXT_NOT_EXISTS. Built lazily here instead.
    return F.udf(_is_implausible_name, "boolean")(col)


def _flag_implausible_companies(fact):
    """Defense in depth: re-apply _looks_implausible() to company_normalized_name
    before any aggregation, adding an `_implausible` boolean column rather
    than filtering here directly — callers null out or filter on it as
    needed, but the UDF itself runs exactly once, cached by the caller.

    Necessary in addition to the check already applied at insertion time
    (database/crud/companies.py::get_or_create_company) because a Company
    row can predate a filter improvement: company_id 48
    ("ECONOMIQUEMENT LA PLUS AVANTAGEUSE") was created before
    NOISE_WORDS_WHEN_NO_STRUCTURE existed, ranked #1 by total_amount_ttc in
    company_stats_global (96 128 952 DH) — the single most visible spot a
    noisy entry could occupy. Re-checking here means this job stays correct
    even against a PostgreSQL database that has not been reloaded since a
    filter improvement, not just after a fresh load.

    Single UDF invocation on purpose: calling F.udf(...) separately in two
    places (once for a "which companies got dropped" diagnostic, once for
    the actual null-out) caused a deterministic Python-worker TimeoutError
    on the second invocation in this environment — the first UDF call in
    the job always succeeded, subsequent ones did not (reproduced 3 times
    with different code shapes, including a plain named function, ruling
    out a lambda-serialization theory tried first). Spawning the local-mode
    worker subprocess more than once per session is what is unreliable
    here, not the UDF's implementation — one flag column, cached once by
    the caller (see main()), read by every downstream use, is the fix.
    """
    return fact.withColumn(
        "_implausible", _is_implausible_col(F.col("company_normalized_name")))


def _drop_implausible_companies(fact, excluded_company_ids: list[int]):
    """Nulls out company_id/company_normalized_name/company_display_name on
    rows whose company_id is in `excluded_company_ids` — treated exactly
    like "no company identified" (the LEFT JOIN's existing null case),
    never a dropped row.

    Takes a plain Python id list rather than re-running the plausibility
    UDF here on purpose — see collect_implausible_company_ids() and main()
    for why: a pure `isin()` Spark expression needs no Python worker at
    all, so this function carries zero risk of the UDF-session instability
    documented there, regardless of how many times it is called."""
    if not excluded_company_ids:
        return fact
    is_excluded = F.col("company_id").isin(excluded_company_ids)
    return (
        fact
        .withColumn("company_id", F.when(is_excluded, None).otherwise(F.col("company_id")))
        .withColumn("company_normalized_name",
                    F.when(is_excluded, None).otherwise(F.col("company_normalized_name")))
        .withColumn("company_display_name",
                    F.when(is_excluded, None).otherwise(F.col("company_display_name")))
    )


def collect_implausible_company_ids(fact_table_path: Path) -> list:
    """Own short-lived SparkSession, exactly one UDF-touching action, then
    stopped — see the long comment in main() for why this job is split
    into two sessions. Returns plain collect()ed Row objects (safe to use
    after the session that produced them stops, since collect() already
    pulled the data to the driver)."""
    spark = get_spark_session(app_name="ppi-analytics-plausibility-scan")
    try:
        fact_raw = spark.read.parquet(str(fact_table_path))
        flagged = _flag_implausible_companies(fact_raw)
        return (
            flagged.filter(F.col("company_id").isNotNull() & F.col("_implausible"))
            .select("company_id", "company_normalized_name").distinct().collect()
        )
    finally:
        spark.stop()


def _with_groupement_size(fact):
    """1 par entreprise seule, 2+ pour un groupement, NULL (jamais 0
    fabrique) quand aucune entreprise n'est identifiee sur cet Award —
    voir bigdata/README.md pour la decision et sa justification."""
    counts = (fact.filter(F.col("company_id").isNotNull())
              .groupBy("award_id").agg(F.count("company_id").alias("groupement_size")))
    return fact.join(counts, on="award_id", how="left")


def _company_amount_stats(fact, group_cols: list[str]):
    """number_of_awards, total/average HT et TTC, chacune sur son propre
    denominateur (n_with_ht/n_with_ttc) — jamais une base deduite de
    l'autre, jamais une seule base choisie a la place des deux
    (data_dictionary.md §3.6, toujours en vigueur depuis Issue 7)."""
    with_company = fact.filter(F.col("company_id").isNotNull())
    return with_company.groupBy(*group_cols).agg(
        F.count("award_id").alias("number_of_awards"),
        F.sum("montant_ht").alias("total_amount_ht"),
        F.avg("montant_ht").alias("average_amount_ht"),
        F.count("montant_ht").alias("n_with_ht"),
        F.sum("montant_ttc").alias("total_amount_ttc"),
        F.avg("montant_ttc").alias("average_amount_ttc"),
        F.count("montant_ttc").alias("n_with_ttc"),
    )


def build_company_stats_by_acheteur(fact):
    stats = _company_amount_stats(fact, ["company_id", "company_normalized_name", "acheteur_public"])
    totals = stats.groupBy("acheteur_public").agg(
        F.sum("total_amount_ht").alias("_acheteur_total_ht"),
        F.sum("total_amount_ttc").alias("_acheteur_total_ttc"),
    )
    return (
        stats.join(totals, on="acheteur_public", how="left")
        .withColumn("market_share_ht",
                    F.when(F.col("_acheteur_total_ht") > 0,
                          F.col("total_amount_ht") / F.col("_acheteur_total_ht")))
        .withColumn("market_share_ttc",
                    F.when(F.col("_acheteur_total_ttc") > 0,
                          F.col("total_amount_ttc") / F.col("_acheteur_total_ttc")))
        .drop("_acheteur_total_ht", "_acheteur_total_ttc")
    )


def build_company_stats_global(fact):
    # Cross-join contre un total agrege en une seule ligne, meme motif que
    # build_company_stats_by_acheteur, plutot que .first() pour ramener un
    # scalaire au driver — .first() sur une lignee qui remonte a un UDF
    # (_drop_implausible_companies) declenchait un TimeoutError deterministe
    # du worker Python a cet endroit precis (reproduit deux fois de suite,
    # pas un incident isole). Rester sur des transformations DataFrame de
    # bout en bout evite de re-declencher la lignee UDF via une action driver
    # separee.
    stats = _company_amount_stats(fact, ["company_id", "company_normalized_name"])
    totals = stats.agg(
        F.sum("total_amount_ht").alias("_total_ht"),
        F.sum("total_amount_ttc").alias("_total_ttc"),
    )
    return (
        stats.crossJoin(totals)
        .withColumn("market_share_global_ht",
                    F.when(F.col("_total_ht") > 0, F.col("total_amount_ht") / F.col("_total_ht")))
        .withColumn("market_share_global_ttc",
                    F.when(F.col("_total_ttc") > 0, F.col("total_amount_ttc") / F.col("_total_ttc")))
        .drop("_total_ht", "_total_ttc")
    )


def _plausible_names(entries: list[str] | None) -> list[str]:
    if not entries:
        return []
    result = set()
    for entry in entries:
        if not entry or len(entry) > MAX_PLAUSIBLE_NAME_LENGTH:
            continue
        norm = normalize_company_name(entry)
        if not norm or _looks_implausible(norm):
            continue
        result.add(norm)
    return sorted(result)


def build_market_stats(spark, fact):
    # liste_concurrents vit au grain Award, duplique sur chaque ligne
    # (Award, Company) d'un meme award_id dans fact — dedup par award_id
    # avant de compter, un groupement a 2 entreprises ne doit pas compter
    # ses concurrents deux fois.
    per_award = fact.select("award_id", "doc_id", "liste_concurrents").dropDuplicates(["award_id"])

    filter_udf = F.udf(_plausible_names, "array<string>")
    per_award = per_award.withColumn("_filtered", filter_udf(F.col("liste_concurrents")))

    return per_award.select(
        "award_id",
        "doc_id",
        F.coalesce(F.size(F.col("liste_concurrents")), F.lit(0)).alias("number_of_bidders_raw"),
        F.size(F.col("_filtered")).alias("number_of_bidders_filtered"),
    )


def main() -> int:
    # Confirmed on this machine, reproduced consistently across many code
    # shapes (named function vs lambda, cached vs uncached, local[1] vs
    # local[*], with/without a "warmup" call, spark.python.worker.reuse
    # true/false): the FIRST UDF-touching action in a SparkSession succeeds,
    # every subsequent DISTINCT one times out with a Python-worker socket
    # TimeoutError. A warmup call only moved the failure — it became
    # invocation #1, making the real work invocation #2, which then failed
    # instead. The fix is architectural, not configuration: two short-lived
    # sessions, each doing at most one UDF-touching action —
    # collect_implausible_company_ids() (Company filter, own session,
    # stopped before this one starts) and build_market_stats() below (the
    # only UDF call in this session, liste_concurrents filter).
    dropped_companies = collect_implausible_company_ids(FACT_TABLE_PATH)
    excluded_company_ids = [row["company_id"] for row in dropped_companies]

    spark = get_spark_session()
    try:
        fact_raw = spark.read.parquet(str(FACT_TABLE_PATH))
        n_awards_with_company_before = fact_raw.filter(F.col("company_id").isNotNull()) \
            .select("award_id").distinct().count()
        # Comptes les Award DISTINCTS touches par un id exclu, pas le nombre
        # d'id exclus — une Company peut couvrir plusieurs Award (mesure :
        # 4 Company exclues touchent 5 Award, company_id 48 a elle seule en
        # couvrant 2 — une premiere version de cette validation supposait
        # 1 Award par Company exclue et se trompait de 1, attrapee par ce
        # recoupement lui-meme plutot que suppose correct).
        n_awards_affected = (
            fact_raw.filter(F.col("company_id").isin(excluded_company_ids))
            .select("award_id").distinct().count()
        ) if excluded_company_ids else 0

        fact = _drop_implausible_companies(fact_raw, excluded_company_ids)
        fact = _with_groupement_size(fact).cache()
        fact.count()

        # --- verification groupement_size avant toute agregation ---
        dist = fact.groupBy("groupement_size").count().orderBy("groupement_size").collect()
        print("Repartition groupement_size :")
        for row in dist:
            print(f"  {row['groupement_size']}: {row['count']}")

        by_acheteur = build_company_stats_by_acheteur(fact)
        global_stats = build_company_stats_global(fact)
        # cache()+count() : market est ensuite lu par la validation
        # (n_market_rows) PUIS par l'ecriture Parquet — deux actions
        # separees sur la meme lignee UDF (build_market_stats) sans cache
        # relancerait le worker Python une seconde fois dans cette session,
        # exactement le motif d'echec documente plus haut dans ce fichier.
        market = build_market_stats(spark, fact).cache()
        market.count()

        # --- validations ---
        n_companies_by_acheteur = by_acheteur.select("company_id").distinct().count()
        n_companies_global = global_stats.count()
        n_awards_with_company = fact.filter(F.col("company_id").isNotNull()) \
            .select("award_id").distinct().count()
        n_awards_total = fact.select("award_id").distinct().count()
        n_market_rows = market.count()

        print(f"\nCompany rejetees par le filtre de plausibilite (defense en profondeur, "
              f"{len(dropped_companies)}, touchant {n_awards_affected} Award) :")
        for row in dropped_companies:
            print(f"  id={row['company_id']} {row['company_normalized_name']!r}")

        print(f"\nAward distincts dans fact                     : {n_awards_total} (attendu 454)")
        print(f"Award distincts avec compagnie (avant filtre) : {n_awards_with_company_before}")
        print(f"Award distincts avec compagnie (apres filtre) : {n_awards_with_company} "
              f"(attendu {n_awards_with_company_before - n_awards_affected})")
        print(f"Company distinctes (company_stats_global)     : {n_companies_global}")
        print("  NOTE : ~20% de bruit residuel dans Company malgre le filtre de")
        print("  plausibilite — ce chiffre n'est PAS un compte exact d'entreprises")
        print("  reelles. Voir database/README.md.")
        print(f"Company distinctes (by_acheteur, dedup)       : {n_companies_by_acheteur}")
        print(f"Lignes market_stats                           : {n_market_rows} (attendu 454)")

        expected_with_company = n_awards_with_company_before - n_awards_affected
        if (n_awards_total != 454 or n_awards_with_company != expected_with_company
                or n_market_rows != 454):
            raise RuntimeError("recoupement echoue — diagnostiquer avant de continuer")
        print("\nOK : tous les recoupements confirmes.")

        # --- exemple concret avant generalisation ---
        # Pas "le plus haut total_amount_ttc" : un essai avec ce tri a
        # remonte 'ECONOMIQUEMENT LA PLUS AVANTAGEUSE' en premiere place,
        # un fragment de phrase issu du bruit residuel documente dans
        # database/README.md, pas une entreprise reelle. TECTRA est deja
        # verifie propre a plusieurs reprises depuis Issue 7 (extraction/
        # tests/test_extraction.py).
        example_rows = by_acheteur.filter(
            F.col("company_normalized_name") == "TECTRA").collect()
        print(f"\n=== exemple concret : TECTRA ({len(example_rows)} acheteur(s)) ===")
        for example in example_rows:
            print(f"  acheteur_public   : {example['acheteur_public']}")
            print(f"  number_of_awards  : {example['number_of_awards']}")
            print(f"  total_amount_ht   : {example['total_amount_ht']} (n={example['n_with_ht']})")
            print(f"  total_amount_ttc  : {example['total_amount_ttc']} (n={example['n_with_ttc']})")
            print(f"  market_share_ttc  : {example['market_share_ttc']}")

        for df, path in [(by_acheteur, COMPANY_STATS_BY_ACHETEUR_PATH),
                         (global_stats, COMPANY_STATS_GLOBAL_PATH),
                         (market, MARKET_STATS_PATH)]:
            path.parent.mkdir(parents=True, exist_ok=True)
            df.write.mode("overwrite").parquet(str(path))
            print(f"Ecrit : {path}")
    finally:
        spark.stop()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
