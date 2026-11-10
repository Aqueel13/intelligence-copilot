"""Test setup: an isolated `<db>_test` database, migrated and loaded with seed-42 data.

The test database URL is derived from DATABASE_URL and set *before* any app module reads
settings, so tests never touch development data.
"""

import os

import pytest
from sqlalchemy import create_engine, make_url, text

from watchdog_backend.config import get_settings

_base_url = make_url(get_settings().database_url)
_test_db = (
    _base_url.database if _base_url.database.endswith("_test") else f"{_base_url.database}_test"
)
TEST_DATABASE_URL = _base_url.set(database=_test_db).render_as_string(hide_password=False)
os.environ["DATABASE_URL"] = TEST_DATABASE_URL
get_settings.cache_clear()


def _create_database() -> None:
    admin = create_engine(
        _base_url.set(database="postgres").render_as_string(hide_password=False),
        isolation_level="AUTOCOMMIT",
    )
    with admin.connect() as conn:
        exists = conn.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": _test_db}
        ).scalar()
        if not exists:
            conn.execute(text(f'CREATE DATABASE "{_test_db}"'))
    admin.dispose()


def _migrate() -> None:
    from alembic import command
    from alembic.config import Config

    here = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    command.upgrade(Config(os.path.join(here, "alembic.ini")), "head")


@pytest.fixture(scope="session")
def pack():
    from watchdog_backend.domain.pack import get_pack

    return get_pack()


@pytest.fixture(scope="session")
def dataset(pack):
    """The default 5,000-claim dataset (seed 42), generated once per test session."""
    from watchdog_backend.generator.insurance_claims import InsuranceClaimsGenerator

    return InsuranceClaimsGenerator(pack).generate()


@pytest.fixture(scope="session")
def db_engine(dataset):
    """Migrated test database loaded with `dataset`."""
    from watchdog_backend.db import get_engine
    from watchdog_backend.generator.loader import load_dataset

    _create_database()
    _migrate()
    engine = get_engine()
    load_dataset(engine, dataset)
    return engine
