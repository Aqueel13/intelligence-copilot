from datetime import datetime
from typing import Annotated, Any
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from watchdog_backend.analytics.metrics import MetricQueryError
from watchdog_backend.analytics.process import ProcessQuery
from watchdog_backend.api.metrics import get_engine
from watchdog_backend.db import get_session
from watchdog_backend.domain.pack import get_pack
from watchdog_backend.identity import limits
from watchdog_backend.identity.deps import require
from watchdog_backend.identity.service import Principal
from watchdog_backend.investigation import cache
from watchdog_backend.investigation.service import (
    find_previous_run,
    get_investigation,
    list_investigations,
    replay_investigation,
    set_showcase,
    stream_investigation,
)
from watchdog_backend.llm.gateway import LLMConfigError, get_chat_model

router = APIRouter(prefix="/investigations", tags=["investigations"])
DbSession = Annotated[Session, Depends(get_session)]


SSE_HEADERS = {"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
# Cache hits replay quickly (the answer is what matters); showcase replays are paced to watch.
CACHE_HIT_SPEED = 40.0
SHOWCASE_SPEED = 8.0


class InvestigationRequest(BaseModel):
    question: str = Field(min_length=5, max_length=500)
    scope: ProcessQuery = Field(default_factory=ProcessQuery)
    fresh: bool = False  # True: run again even if an identical run is cached


@router.post("/stream")
def start_investigation(
    req: InvestigationRequest,
    session: DbSession,
    who: Annotated[Principal, Depends(require("investigate"))],
) -> StreamingResponse:
    """Run an investigation, streaming progress as Server-Sent Events:
    `start` {id, models, replay?, cached?, recorded_at?} → `step` {node, update}… →
    `done` {id} | `error` {id, message}.

    An identical earlier run (same question, scope, models, data, documents and pack) is
    replayed from the cache unless `fresh` is set; replays cost no tokens and are not
    rate-limited."""
    try:  # validate the scope and model configuration before opening the stream
        get_engine().where_clause(
            "cases", req.scope.filters, req.scope.period_from, req.scope.period_to
        )
        get_chat_model("planner")
    except MetricQueryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    except LLMConfigError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc

    conn = session.connection()
    key, _, previous = find_previous_run(conn, req.question, req.scope)
    if previous is not None and not req.fresh:
        cache.record_hit(conn, get_pack().domain, previous, who.user.user_id)
        return StreamingResponse(
            replay_investigation(previous, speed=CACHE_HIT_SPEED, cached=True),
            media_type="text/event-stream",
            headers=SSE_HEADERS,
        )
    try:
        limits.check(conn, who, "investigate")
    except limits.RateLimited as exc:
        raise HTTPException(
            status_code=429, detail=str(exc), headers={"Retry-After": str(exc.retry_after)}
        ) from exc
    limits.charge(conn, who, "investigate")
    session.commit()
    return StreamingResponse(
        stream_investigation(req.question, req.scope, {"user_id": who.user.user_id}, key),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
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
    showcase: bool
    replayable: bool


@router.get("", response_model=list[InvestigationSummary])
def recent(session: DbSession, showcase: bool = False) -> list[dict[str, Any]]:
    return list_investigations(session.connection(), showcase_only=showcase)


@router.get("/{investigation_id}")
def detail(investigation_id: UUID, session: DbSession) -> dict[str, Any]:
    row = get_investigation(session.connection(), investigation_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Investigation not found")
    row["replayable"] = row.pop("events") is not None
    row.pop("cache_key", None)
    return row


@router.get("/{investigation_id}/replay")
def replay(
    investigation_id: UUID,
    session: DbSession,
    speed: Annotated[float, Query(ge=1, le=100)] = SHOWCASE_SPEED,
) -> StreamingResponse:
    """Play a completed run back as the same Server-Sent Events, without a model call. Open to
    every role (viewers included): this is how visitors watch showcase runs."""
    row = get_investigation(session.connection(), investigation_id)
    if row is None or row["domain"] != get_pack().domain:
        raise HTTPException(status_code=404, detail="Investigation not found")
    if row["status"] != "completed" or row["events"] is None:
        raise HTTPException(
            status_code=409,
            detail="Only completed runs recorded since replay was added can be replayed",
        )
    return StreamingResponse(
        replay_investigation(row, speed=speed), media_type="text/event-stream", headers=SSE_HEADERS
    )


class ShowcaseRequest(BaseModel):
    showcase: bool


@router.put("/{investigation_id}/showcase", dependencies=[Depends(require("manage_showcase"))])
def showcase(investigation_id: UUID, req: ShowcaseRequest, session: DbSession) -> dict[str, Any]:
    if not set_showcase(session.connection(), investigation_id, req.showcase):
        raise HTTPException(
            status_code=409,
            detail="Only completed, replayable runs of the current pack can be showcased",
        )
    session.commit()
    return {"investigation_id": investigation_id, "showcase": req.showcase}
