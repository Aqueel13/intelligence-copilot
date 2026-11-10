from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from watchdog_backend import __version__
from watchdog_backend.config import get_settings
from watchdog_backend.db import SCHEMAS, get_session

router = APIRouter(tags=["health"])


class DatabaseHealth(BaseModel):
    ok: bool
    pgvector_version: str | None = None
    missing_schemas: list[str] = []
    error: str | None = None


class HealthResponse(BaseModel):
    status: Literal["ok", "degraded"]
    app: str
    version: str
    environment: str
    database: DatabaseHealth


def _check_database(session: Session) -> DatabaseHealth:
    try:
        pgvector = session.execute(
            text("SELECT extversion FROM pg_extension WHERE extname = 'vector'")
        ).scalar_one_or_none()
        present = set(
            session.execute(text("SELECT schema_name FROM information_schema.schemata")).scalars()
        )
    except SQLAlchemyError as exc:
        return DatabaseHealth(ok=False, error=type(exc).__name__)

    missing = [s for s in SCHEMAS if s not in present]
    problems = []
    if pgvector is None:
        problems.append("pgvector extension not installed")
    if missing:
        problems.append(f"missing schemas: {', '.join(missing)}")
    return DatabaseHealth(
        ok=not problems,
        pgvector_version=pgvector,
        missing_schemas=missing,
        error=f"{'; '.join(problems)} (run migrations)" if problems else None,
    )


@router.get("/health", response_model=HealthResponse)
def health(response: Response, session: Annotated[Session, Depends(get_session)]) -> HealthResponse:
    settings = get_settings()
    db = _check_database(session)
    if not db.ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return HealthResponse(
        status="ok" if db.ok else "degraded",
        app=settings.app_name,
        version=__version__,
        environment=settings.app_env,
        database=db,
    )
