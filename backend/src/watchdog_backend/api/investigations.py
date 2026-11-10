from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from watchdog_backend.analytics.metrics import MetricQueryError
from watchdog_backend.analytics.process import ProcessQuery
from watchdog_backend.api.metrics import get_engine
from watchdog_backend.db import get_session
from watchdog_backend.investigation.service import (
    get_investigation,
    list_investigations,
    stream_investigation,
)
from watchdog_backend.llm.gateway import LLMConfigError, get_chat_model

router = APIRouter(prefix="/investigations", tags=["investigations"])
DbSession = Annotated[Session, Depends(get_session)]


class InvestigationRequest(BaseModel):
    question: str = Field(min_length=5, max_length=500)
    scope: ProcessQuery = Field(default_factory=ProcessQuery)


@router.post("/stream")
def start_investigation(req: InvestigationRequest) -> StreamingResponse:
    """Run an investigation, streaming progress as Server-Sent Events:
    `start` {id, models} → `step` {node, update}… → `done` {id} | `error` {id, message}."""
    try:  # validate the scope and model configuration before opening the stream
        get_engine().where_clause(
            "cases", req.scope.filters, req.scope.period_from, req.scope.period_to
        )
        get_chat_model("planner")
    except MetricQueryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LLMConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    return StreamingResponse(
        stream_investigation(req.question, req.scope),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


class InvestigationSummary(BaseModel):
    investigation_id: UUID
    question: str
    status: str
    route: str | None
    models: dict[str, str]
    created_at: datetime
    duration_ms: int | None
    error: str | None
    supported: int


@router.get("", response_model=list[InvestigationSummary])
def recent(session: DbSession) -> list[dict[str, Any]]:
    return list_investigations(session.connection())


@router.get("/{investigation_id}")
def detail(investigation_id: UUID, session: DbSession) -> dict[str, Any]:
    row = get_investigation(session.connection(), investigation_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    return row
