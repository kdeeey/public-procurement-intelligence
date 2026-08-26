"""
Issue 11 — Isolation Forest anomaly detection on the per-company feature
matrix built by bigdata/spark/jobs/build_features.py.

Plain Python/pandas/sklearn, not PySpark: 200 rows, 18 columns — nothing
here benefits from distributed processing, and staying out of Spark
avoids the UDF-session-instability documented in
bigdata/spark/jobs/build_statistics.py entirely.

Imputation policy, confirmed with the user before coding (46% of Company
have zero amount data on both bases — a measured extraction gap, not a
real absence of activity, see build_features.py's docstring):
  - Amount/market-share columns (TTC only — see below): missing values are
    median-imputed using the median of companies that DO have TTC data,
    never 0 (0 would look like an extreme low value to Isolation Forest,
    not a neutral "unknown"). A companion `has_ttc_data` boolean feature
    lets the model learn that "imputed" is not itself a signal.
  - Trend slopes (single_bidder_rate_trend_slope, number_of_awards_trend_slope):
    None when a company has <2 usable (2023/2024/2025) yearly points —
    imputed with 0 (a flat/no-trend slope is a genuinely neutral value
    here, unlike an amount) + a companion `has_trend_data` boolean.

HT is NOT fed to the model (only 24/200 companies have any HT data at
all — imputing the other 176 would make the column almost entirely
fabricated, i.e. not informative). HT columns stay in company_features
for traceability but never enter MODEL_FEATURE_COLUMNS below —
data_dictionary.md Sec 3.6's "never merge HT/TTC" is respected by keeping
them as fully separate columns, not by feeding both into one model.

    python -m ai.train_isolation_forest
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

import joblib  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.ensemble import IsolationForest  # noqa: E402

COMPANY_FEATURES_PATH = REPO / "data/processed/analytics/company_features.parquet"
MODEL_PATH = REPO / "ai/models/isolation_forest.joblib"
FEATURE_COLUMNS_PATH = REPO / "ai/models/feature_columns.json"

# TTC seulement (voir docstring) — jamais HT, jamais les deux fusionnes en
# une colonne unique.
AMOUNT_COLUMNS_TTC = ["total_amount_ttc", "average_amount_ttc", "market_share_global_ttc"]
TREND_COLUMNS = ["single_bidder_rate_trend_slope", "number_of_awards_trend_slope"]
NON_IMPUTED_COLUMNS = ["number_of_awards", "single_bidder_rate", "groupement_rate",
                       "concurrents_ecartes_rate"]

MODEL_FEATURE_COLUMNS = (
    NON_IMPUTED_COLUMNS + AMOUNT_COLUMNS_TTC + ["has_ttc_data"]
    + TREND_COLUMNS + ["has_trend_data"]
)


def prepare_model_matrix(features_pdf: pd.DataFrame) -> pd.DataFrame:
    """company_features.parquet -> matrice numerique sans NaN pour
    Isolation Forest. Toute imputation est explicite et documentee ici,
    jamais silencieuse — voir la docstring du module pour le choix
    median (montants) vs 0 (pentes)."""
    df = features_pdf.copy()

    df["has_trend_data"] = df["single_bidder_rate_trend_slope"].notna()

    for col in AMOUNT_COLUMNS_TTC:
        median_with_data = df.loc[df["has_ttc_data"], col].median()
        df[col] = df[col].fillna(median_with_data)

    for col in TREND_COLUMNS:
        df[col] = df[col].fillna(0.0)

    df["has_ttc_data"] = df["has_ttc_data"].astype(int)
    df["has_trend_data"] = df["has_trend_data"].astype(int)

    matrix = df[["company_id"] + MODEL_FEATURE_COLUMNS].copy()
    assert not matrix[MODEL_FEATURE_COLUMNS].isna().any().any(), (
        "colonnes d'entree du modele encore NaN apres imputation — "
        "diagnostiquer avant d'entrainer")
    return matrix


DECIMAL_COLUMNS = ["total_amount_ht", "average_amount_ht", "total_amount_ttc",
                   "average_amount_ttc", "market_share_global_ht", "market_share_global_ttc",
                   "single_bidder_rate_trend_slope", "number_of_awards_trend_slope"]


def _load_features() -> pd.DataFrame:
    """company_features.parquet came through Spark's DecimalType (PostgreSQL
    NUMERIC -> montant_ht/ttc), so these columns land here as object dtype
    holding python Decimal (or None) rather than float64 — pyarrow later
    refuses to write a mixed Decimal/float column (confirmed: it raised
    exactly on this when the imputed median, a numpy float, replaced a None
    inside an otherwise-Decimal column). pd.to_numeric with errors="coerce"
    converts Decimal -> float64 and None -> NaN cleanly, keeping the actual
    "missing" semantics intact for the imputation step below."""
    features_pdf = pd.read_parquet(COMPANY_FEATURES_PATH)
    for col in DECIMAL_COLUMNS:
        features_pdf[col] = pd.to_numeric(features_pdf[col], errors="coerce")
    return features_pdf


def main() -> int:
    features_pdf = _load_features()
    n_companies = len(features_pdf)
    print(f"Company chargees : {n_companies} (attendu 200)")
    if n_companies != 200:
        raise RuntimeError("recoupement echoue — diagnostiquer avant de continuer")

    matrix = prepare_model_matrix(features_pdf)

    # --- validation visuelle sur un petit echantillon avant l'ensemble ---
    sample_ids = features_pdf[features_pdf["company_normalized_name"].isin(
        ["TECTRA", "COSTACOM"])]["company_id"].tolist()
    print("\n=== echantillon avant entrainement (TECTRA, COSTACOM) ===")
    print(matrix[matrix["company_id"].isin(sample_ids)]
          .merge(features_pdf[["company_id", "company_normalized_name"]], on="company_id")
          .to_string(index=False))

    X = matrix[MODEL_FEATURE_COLUMNS].to_numpy()
    model = IsolationForest(n_estimators=200, contamination="auto", random_state=42)
    model.fit(X)

    scores = model.decision_function(X)  # plus bas = plus anormal
    is_anomaly = model.predict(X) == -1

    matrix["anomaly_score"] = scores
    matrix["is_anomaly"] = is_anomaly
    result = matrix.merge(features_pdf[["company_id", "company_normalized_name"]], on="company_id")

    n_flagged = int(is_anomaly.sum())
    print(f"\nCompany signalees anormales par Isolation Forest : {n_flagged}/{n_companies}")

    print("\n=== echantillon apres entrainement (TECTRA, COSTACOM) ===")
    print(result[result["company_id"].isin(sample_ids)][
        ["company_normalized_name", "anomaly_score", "is_anomaly"]].to_string(index=False))

    print("\n=== top 10 les plus anormales (score le plus bas) ===")
    print(result.sort_values("anomaly_score").head(10)[
        ["company_normalized_name", "anomaly_score", "has_ttc_data",
         "single_bidder_rate", "market_share_global_ttc"]].to_string(index=False))

    MODEL_PATH.parent.mkdir(parents=True, exist_ok=True)
    joblib.dump(model, MODEL_PATH)
    FEATURE_COLUMNS_PATH.write_text(json.dumps(MODEL_FEATURE_COLUMNS, indent=2), encoding="utf-8")
    print(f"\nModele sauvegarde : {MODEL_PATH}")
    print(f"Ordre des colonnes sauvegarde : {FEATURE_COLUMNS_PATH}")

    result.to_parquet(REPO / "data/processed/analytics/company_anomaly_scores.parquet", index=False)
    print(f"Scores ecrits : data/processed/analytics/company_anomaly_scores.parquet")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
