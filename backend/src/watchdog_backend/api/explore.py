"""Exploratory SQL (read-only, sandboxed). See analytics/explore.py for the safeguards."""

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from watchdog_backend.analytics import explore
from watchdog_backend.db import get_session
from watchdog_backend.identity import limits
from watchdog_backend.identity.deps import require
from watchdog_backend.identity.service import Principal
from watchdog_backend.llm.gateway import LLMCallError, LLMConfigError
from watchdog_backend.observability.context import traced

router = APIRouter(prefix="/explore", tags=["explore"])
Explorer = Annotated[Principal, Depends(require("explore"))]


class SchemaInfo(BaseModel):
    doc: str
    tables: dict[str, list[tuple[str, str]]]
    max_rows: int
    timeout_seconds: int


@router.get("/schema", response_model=SchemaInfo)
def schema(_: Explorer) -> SchemaInfo:
    return SchemaInfo(
        doc=explore.schema_doc(),
        tables={name: cols for name, (_, cols) in explore.TABLES.items()},
        max_rows=explore.MAX_ROWS,
        timeout_seconds=explore.TIMEOUT_MS // 1000,
    )


class RunRequest(BaseModel):
    sql: str = Field(min_length=1, max_length=explore.MAX_SQL_CHARS + 100)


@router.post("/run", response_model=explore.ExploreResult)
def run(req: RunRequest, _: Explorer) -> explore.ExploreResult:
    try:
        return explore.run(req.sql)
    except explore.ExploreError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


class DraftRequest(BaseModel):
    question: str = Field(min_length=5, max_length=500)


class DraftResponse(explore.Draft):
    model: str


@router.post("/draft", response_model=DraftResponse)
def draft(req: DraftRequest, who: Explorer, session: Annotated[Session, Depends(get_session)]):
    """A model writes the SQL; it is returned, not run, so the person sees it first. Counts
    against the question rate limit."""
    conn = session.connection()
    try:
        limits.check(conn, who, "ask")
    except limits.RateLimited as exc:
        raise HTTPException(
            status_code=429, detail=str(exc), headers={"Retry-After": str(exc.retry_after)}
        ) from exc
    limits.charge(conn, who, "ask")
    session.commit()
    try:
        with traced(purpose="explore", user_id=who.user.user_id):
            out, model = explore.draft(req.question)
    except LLMConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    except LLMCallError as exc:
        raise HTTPException(
            status_code=502, detail=f"The language model ({exc.model_id}) failed: {exc.reason}"
        ) from exc
    except ValueError as exc:  # no valid structured answer
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return DraftResponse(sql=out.sql, explanation=out.explanation, model=model)
