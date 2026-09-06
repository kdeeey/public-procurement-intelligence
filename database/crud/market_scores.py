"""
Load MarketScore rows from data/processed/analytics/market_priority.parquet
(ai/priority_score.py's output, la table la plus complete des trois
sorties de scoring par marche) into PostgreSQL.

Full replace, meme raisonnement que l'ancien load_risk_scores() : un
reentrainement d'Isolation Forest peut changer tous les scores a la fois,
un upsert ligne par ligne laisserait des scores perimes.
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd
from sqlalchemy import delete
from sqlalchemy.orm import Session

from database.models import Award, MarketScore


def _opt_float(value) -> float | None:
    return None if pd.isna(value) else float(value)


def _opt_int(value) -> int | None:
    return None if pd.isna(value) else int(value)


def _opt_str(value) -> str | None:
    return None if pd.isna(value) else str(value)


def load_market_scores(session: Session, parquet_path: Path) -> dict:
    """Returns {'read': N, 'inserted': M, 'skipped_no_award': K} —
    skipped_no_award tracks any award_id in le parquet absent de `awards`
    (DB rechargee/refiltree depuis la generation du parquet) plutot que
    de planter sur la FK."""
    df = pd.read_parquet(parquet_path)

    known_award_ids = {row[0] for row in session.query(Award.id).all()}
    skipped = 0

    session.execute(delete(MarketScore))

    for _, row in df.iterrows():
        award_id = int(row["award_id"])
        if award_id not in known_award_ids:
            skipped += 1
            continue
        session.add(MarketScore(
            award_id=award_id,
            scorable=bool(row["scorable"]),
            data_completeness=int(row["data_completeness"]),
            anomaly_score_0_100=_opt_float(row.get("anomaly_score_0_100")),
            is_anomaly=bool(row["is_anomaly"]),
            stability_frequency=_opt_float(row.get("stability_frequency")),
            risk_level=str(row["risk_level"]),
            red_flag_score=_opt_float(row.get("red_flag_score")),
            red_flag_count=_opt_int(row.get("red_flag_count")),
            red_flags_evaluable=_opt_int(row.get("red_flags_evaluable")),
            red_flags_triggered=_opt_str(row.get("red_flags_triggered")),
            data_quality_score=_opt_float(row.get("data_quality_score")),
            data_quality_level=_opt_str(row.get("data_quality_level")),
            invalid_fields_count=_opt_int(row.get("invalid_fields_count")),
            confidence_level=_opt_str(row.get("confidence_level")),
            priority_raw=_opt_float(row.get("priority_raw")),
            priority_score=_opt_float(row.get("priority_score")),
            priority_level=str(row["priority_level"]),
        ))

    return {"read": len(df), "inserted": len(df) - skipped, "skipped_no_award": skipped}
