"""
Load Issue 12's risk score output into PostgreSQL (Issue 12 follow-up).

Requires companies (Issue 8) already loaded — RiskScore.company_id is a
FK to companies.id, and the parquet was generated from that same set of
Company rows in the first place.

    python scripts/load_risk_scores.py
    python scripts/load_risk_scores.py --database-url postgresql://user:password@localhost:5432/procurement_db
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from database.crud import get_engine, get_session_factory, load_risk_scores  # noqa: E402
from database.models import Base  # noqa: E402

RISK_SCORES_PARQUET_PATH = REPO / "data/processed/analytics/company_final_risk.parquet"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--database-url", default=None,
                    help="par defaut : DATABASE_URL de l'environnement (.env)")
    ap.add_argument("--create-schema", action="store_true",
                    help="cree la table risk_scores si absente")
    args = ap.parse_args()

    if not RISK_SCORES_PARQUET_PATH.exists():
        raise SystemExit(
            f"{RISK_SCORES_PARQUET_PATH} introuvable — lancer d'abord "
            "python -m ai.risk_score")

    engine = get_engine(args.database_url)
    if args.create_schema:
        Base.metadata.create_all(engine)

    session = get_session_factory(engine)()
    try:
        counts = load_risk_scores(session, RISK_SCORES_PARQUET_PATH)
        print(f"RiskScore : {counts}")
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
