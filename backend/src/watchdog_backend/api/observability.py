"""Observability: LLM calls, tokens, latency, errors, cache hits, API requests, traces."""

from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from watchdog_backend.db import get_session
from watchdog_backend.identity.deps import require
from watchdog_backend.investigation.service import get_investigation
from watchdog_backend.observability import queries

router = APIRouter(
    prefix="/observability",
    tags=["observability"],
    dependencies=[Depends(require("view_observability"))],
)
DbSession = Annotated[Session, Depends(get_session)]


@router.get("/summary")
def summary(
    session: DbSession,
    hours: Annotated[int, Query(ge=1, le=24 * 30)] = 24,
    pack: str | None = None,
) -> dict[str, Any]:
    """Platform-wide unless `pack` is given."""
    return queries.summary(session.connection(), hours, pack)


@router.get("/investigations")
def investigations(session: DbSession) -> list[dict[str, Any]]:
    return queries.recent_investigations(session.connection())


@router.get("/investigations/{investigation_id}")
def trace(investigation_id: UUID, session: DbSession) -> dict[str, Any]:
    """One investigation's trace: graph steps (with timings) and every LLM call it made."""
    conn = session.connection()
    inv = get_investigation(conn, investigation_id)
    if inv is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    result = inv.get("result") or {}
    return {
        "investigation_id": str(investigation_id),
        "question": inv["question"],
        "domain": inv["domain"],
        "status": inv["status"],
        "duration_ms": inv["duration_ms"],
        "models": inv["models"],
        "steps": result.get("steps", []),
        "calls": queries.investigation_calls(conn, str(investigation_id)),
    }
