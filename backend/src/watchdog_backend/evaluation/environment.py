"""An isolated evaluation database (`<db>_eval`), reloaded per generator seed.

Import and call `use_eval_database()` BEFORE anything reads settings, so the evaluation never
touches the development or test databases.
"""

import os

from sqlalchemy import create_engine, make_url, text


def use_eval_database(suffix: str = "eval") -> str:
    """Point the app at `<db>_<suffix>` (created and migrated if needed). Concurrent runs
    need different suffixes: each run reloads its database per seed."""
    from watchdog_backend.config import get_settings

    base = make_url(get_settings().database_url)
    name = f"{base.database}_{suffix}"
    admin = create_engine(
        base.set(database="postgres").render_as_string(hide_password=False),
        isolation_level="AUTOCOMMIT",
    )
    with admin.connect() as c:
        if not c.execute(
            text("SELECT 1 FROM pg_database WHERE datname = :n"), {"n": name}
        ).scalar():
            c.execute(text(f'CREATE DATABASE "{name}"'))
    admin.dispose()
    os.environ["DATABASE_URL"] = base.set(database=name).render_as_string(hide_password=False)
    get_settings.cache_clear()

    from alembic import command
    from alembic.config import Config

    here = os.path.dirname(os.path.dirname(os.path.dirname(os.path.dirname(__file__))))
    command.upgrade(Config(os.path.join(here, "alembic.ini")), "head")
    return name


def load_seed(seed: int):
    """Replace the eval database's claims with the dataset for `seed`; (re)ingest documents."""
    from watchdog_backend.db import get_engine
    from watchdog_backend.domain.pack import get_pack
    from watchdog_backend.generator.insurance_claims import (
        GeneratorConfig,
        InsuranceClaimsGenerator,
    )
    from watchdog_backend.generator.loader import load_dataset
    from watchdog_backend.knowledge.ingest import ingest_directory
    from watchdog_backend.knowledge.models import get_embedder
    from watchdog_backend.knowledge.service import documents_dir

    dataset = InsuranceClaimsGenerator(get_pack(), GeneratorConfig(seed=seed)).generate()
    load_dataset(get_engine(), dataset)
    with get_engine().begin() as conn:
        ingest_directory(conn, get_pack().domain, documents_dir(), get_embedder())
    return dataset
