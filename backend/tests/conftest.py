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
os.environ["WATCH_AUTO_INVESTIGATE"] = "off"  # triage tests turn it on with a scripted model
os.environ["PROCESS_CACHE_WARM"] = "false"
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
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def kb(db_engine, pack):
    """The domain pack's policy documents, ingested into the test database."""
    from watchdog_backend.knowledge.ingest import ingest_directory
    from watchdog_backend.knowledge.models import get_embedder
    from watchdog_backend.knowledge.service import documents_dir

    with db_engine.begin() as conn:
        return ingest_directory(conn, pack.domain, documents_dir(), get_embedder())


TEST_PASSWORD = "test-password-123"


@pytest.fixture(scope="session")
def accounts(db_engine):
    """Accounts for API tests: an admin, every governance.yaml user (analysts with their
    business role per pack) and a read-only guest."""
    from watchdog_backend.config import get_settings

    s = get_settings()
    s.admin_password = s.demo_password = TEST_PASSWORD
    from watchdog_backend.identity.__main__ import seed

    seed()
    return db_engine


@pytest.fixture(scope="session")
def client_as(accounts):
    """client_as("a.rao") -> a TestClient signed in as that user (a real session cookie)."""
    from fastapi.testclient import TestClient

    from watchdog_backend.identity.middleware import COOKIE
    from watchdog_backend.identity.service import create_session
    from watchdog_backend.main import app

    def make(user_id: str) -> TestClient:
        with accounts.connect() as conn:
            token = create_session(conn, user_id)
        client = TestClient(app)
        client.cookies.set(COOKIE, token)
        return client

    return make


# --- Procure-to-pay: the second pack, loaded beside the insurance data -------------------


@pytest.fixture(scope="session")
def p2p_pack():
    from watchdog_backend.domain.pack import get_pack

    return get_pack("procure_to_pay")


@pytest.fixture(scope="session")
def p2p_dataset(p2p_pack):
    from watchdog_backend.generator.registry import generate

    return generate(p2p_pack, seed=42)


@pytest.fixture(scope="session")
def p2p_db(db_engine, p2p_dataset):
    """The test database with the P2P dataset and documents loaded beside the insurance data.
    Shared, so any test that reads P2P data can ask for it (a fresh CI database has none)."""
    from watchdog_backend.domain.pack import use_domain
    from watchdog_backend.generator.loader import load_dataset
    from watchdog_backend.knowledge.ingest import ingest_directory
    from watchdog_backend.knowledge.models import get_embedder
    from watchdog_backend.knowledge.service import documents_dir

    load_dataset(db_engine, p2p_dataset)
    with use_domain("procure_to_pay"), db_engine.begin() as conn:
        ingest_directory(conn, "procure_to_pay", documents_dir(), get_embedder())
    return db_engine


@pytest.fixture(autouse=True)
def _fresh_process_cache():
    """Tests reload data within seconds; the cache's 30 s fingerprint memo must not leak."""
    from watchdog_backend.analytics import process_cache

    process_cache.clear()
