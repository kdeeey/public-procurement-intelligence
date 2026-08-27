"""FastAPI dependency: one SQLAlchemy session per request. Reuses
database/crud/session.py::get_engine() — same DATABASE_URL convention as
every other part of this project (see bigdata/README.md's "postgres vs
localhost" section: this module runs inside the `api` Docker container,
where the `postgres` hostname resolves correctly via docker-compose's
network, unlike host-side scripts)."""

from __future__ import annotations

from collections.abc import Generator

from sqlalchemy.orm import Session

from database.crud.session import get_engine, get_session_factory

_engine = get_engine()
_SessionFactory = get_session_factory(_engine)


def get_db() -> Generator[Session, None, None]:
    session = _SessionFactory()
    try:
        yield session
    finally:
        session.close()
