"""
Load RiskScore rows from data/processed/analytics/company_final_risk.parquet
(ai/risk_score.py's output) into PostgreSQL — makes Issue 12's score
queryable directly (DBCode, and later the API in Issue 13) instead of
only readable from a Parquet file.

Full replace, not an incremental upsert: a re-run of ai/risk_score.py
(e.g. after retraining Isolation Forest, as happened during the
redundancy-fix investigation) can change every company's score at once,
not just one row's — a per-row upsert would silently leave stale scores
for companies whose row didn't happen to change, while every OTHER
company moved. Delete-then-insert keeps the table always exactly in sync
with the last parquet actually loaded.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from sqlalchemy import delete
from sqlalchemy.orm import Session

from database.models import Company, RiskLevel, RiskScore


def load_risk_scores(session: Session, parquet_path: Path) -> dict:
    """Returns {'read': N, 'inserted': M, 'skipped_no_company': K} —
    skipped_no_company tracks any company_id in the parquet that no
    longer exists in `companies` (e.g. the DB was reloaded/re-filtered
    since the parquet was generated) rather than crashing on the FK."""
    df = pd.read_parquet(parquet_path)

    known_company_ids = {row[0] for row in session.query(Company.id).all()}
    skipped = 0

    session.execute(delete(RiskScore))

    for _, row in df.iterrows():
        company_id = int(row["company_id"])
        if company_id not in known_company_ids:
            skipped += 1
            continue
        session.add(RiskScore(
            company_id=company_id,
            anomaly_score=float(row["anomaly_score"]),
            final_score=float(row["final_score"]),
            risk_level=RiskLevel(row["risk_level"]),
            n_active_flags=int(row["n_active_flags"]),
            n_evaluable_flags=int(row["n_evaluable_flags"]),
            active_flags=str(row["active_flags"]),
            partially_evaluated=bool(row["partially_evaluated"]),
            dominant_driver=row.get("dominant_driver"),
            explanation=str(row["explanation"]),
        ))

    return {"read": len(df), "inserted": len(df) - skipped, "skipped_no_company": skipped}
