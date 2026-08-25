"""
Load the scraped/extracted corpus into PostgreSQL (Issue 8).

Order matters: Procurement first (join target), then Document (resolves
join_status against it), then Award (resolves procurement_id/ref_consultation
via Document, and Company via database/normalization.py).

    python scripts/load_database.py
    python scripts/load_database.py --database-url sqlite:///local_test.db
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO))

from database.crud import (  # noqa: E402
    get_engine, get_session_factory, load_awards, load_documents, load_procurements,
)
from database.models import Base  # noqa: E402

CONSULTATIONS_PATH = REPO / "data/raw/consultations/consultations_full.jsonl"
PV_MANIFEST_PATH = REPO / "data/samples/PVs/manifest.jsonl"
EXTRACTED_DIR = REPO / "data/processed/extracted"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--database-url", default=None,
                    help="par defaut : DATABASE_URL de l'environnement (.env)")
    ap.add_argument("--create-schema", action="store_true",
                    help="cree les tables si absentes (utile en local/test ; "
                         "en production preferer alembic)")
    args = ap.parse_args()

    engine = get_engine(args.database_url)
    if args.create_schema:
        Base.metadata.create_all(engine)

    session = get_session_factory(engine)()
    try:
        p_counts = load_procurements(session, CONSULTATIONS_PATH)
        print(f"Procurement : {p_counts}")

        d_counts = load_documents(session, PV_MANIFEST_PATH)
        print(f"Document    : {d_counts}")

        a_counts = load_awards(session, EXTRACTED_DIR)
        print(f"Award       : {a_counts}")

        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
