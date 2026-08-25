"""Engine/session factory. Reads DATABASE_URL from the environment (.env,
same convention as api/ and dashboard/ — see docker-compose.yml)."""

from __future__ import annotations

import os

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import Session, sessionmaker

DEFAULT_DATABASE_URL = "postgresql://user:password@localhost:5432/procurement_db"


def get_engine(database_url: str | None = None) -> Engine:
    url = database_url or os.getenv("DATABASE_URL", DEFAULT_DATABASE_URL)
    return create_engine(url)


def get_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine)
