"""Database engine and session management."""

from collections.abc import Iterator
from functools import lru_cache

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from watchdog_backend.config import get_settings

# Postgres schemas, grouped by bounded context (see docs/PROJECT_BRIEF.md).
SCHEMAS = ("core", "operational", "knowledge", "intelligence", "operations", "governance")


class Base(DeclarativeBase):
    pass


@lru_cache
def get_engine() -> Engine:
    return create_engine(get_settings().database_url, pool_pre_ping=True)


@lru_cache
def _session_factory() -> sessionmaker[Session]:
    return sessionmaker(bind=get_engine(), expire_on_commit=False)


def get_session() -> Iterator[Session]:
    """FastAPI dependency yielding a session that is always closed."""
    session = _session_factory()()
    try:
        yield session
    finally:
        session.close()
