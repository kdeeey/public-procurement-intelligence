"""
Load ai/priority_score.py's output (market_priority.parquet) into
PostgreSQL, table market_scores. Remplace scripts/load_risk_scores.py
(score par entreprise, retire — voir docs/refonte_marche.md).

Requires awards deja charges (scripts/load_database.py) — MarketScore.award_id
est une FK vers awards.id.

    python scripts/load_market_scores.py
    python scripts/load_market_scores.py --database-url postgresql://user:password@localhost:5432/procurement_db
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from database.crud import get_engine, get_session_factory, load_market_scores  # noqa: E402
from database.models import Base  # noqa: E402

MARKET_PRIORITY_PARQUET_PATH = REPO / "data/processed/analytics/market_priority.parquet"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--database-url", default=None,
                    help="par defaut : DATABASE_URL de l'environnement (.env)")
    ap.add_argument("--create-schema", action="store_true",
                    help="cree la table market_scores si absente")
    args = ap.parse_args()

    if not MARKET_PRIORITY_PARQUET_PATH.exists():
        raise SystemExit(
            f"{MARKET_PRIORITY_PARQUET_PATH} introuvable — lancer d'abord "
            "python -m ai.priority_score")

    engine = get_engine(args.database_url)
    if args.create_schema:
        Base.metadata.create_all(engine, checkfirst=True)

    session_factory = get_session_factory(engine)
    with session_factory() as session:
        report = load_market_scores(session, MARKET_PRIORITY_PARQUET_PATH)
        session.commit()

    print(f"Lus     : {report['read']}")
    print(f"Charges : {report['inserted']}")
    if report["skipped_no_award"]:
        print(f"Ignores : {report['skipped_no_award']} (award_id absent de la table awards)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
