from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import Connection
from sqlalchemy.orm import Session

from watchdog_backend.analytics import process_cache
from watchdog_backend.analytics.metrics import MetricQueryError, MetricsEngine
from watchdog_backend.analytics.process import (
    ActivityAnalysis,
    ProcessAnalyzer,
    ProcessMap,
    ProcessQuery,
    VariantSummary,
)
from watchdog_backend.api.metrics import get_engine
from watchdog_backend.db import get_session

router = APIRouter(prefix="/process", tags=["process"])


def get_analyzer(engine: Annotated[MetricsEngine, Depends(get_engine)]) -> ProcessAnalyzer:
    return ProcessAnalyzer(engine)


Analyzer = Annotated[ProcessAnalyzer, Depends(get_analyzer)]
DbSession = Annotated[Session, Depends(get_session)]


def _cached[T: BaseModel](
    analyzer: ProcessAnalyzer,
    session: Session,
    kind: str,
    q: ProcessQuery,
    fn: Callable[[Connection], T],
) -> T:
    """Serve from the process cache; invalid filters still answer 422 (never cached)."""
    try:
        conn = session.connection()
        return process_cache.cached(conn, analyzer.metrics.pack.domain, kind, q, lambda: fn(conn))
    except MetricQueryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/map", response_model=ProcessMap)
def process_map(q: ProcessQuery, analyzer: Analyzer, session: DbSession) -> ProcessMap:
    return _cached(analyzer, session, "map", q, lambda c: analyzer.process_map(c, q))


@router.post("/variants", response_model=VariantSummary)
def variants(
    q: ProcessQuery,
    analyzer: Analyzer,
    session: DbSession,
    top: Annotated[int, Query(ge=1, le=50)] = 10,
) -> VariantSummary:
    return _cached(analyzer, session, f"variants:{top}", q, lambda c: analyzer.variants(c, q, top))


@router.post("/activities", response_model=ActivityAnalysis)
def activities(q: ProcessQuery, analyzer: Analyzer, session: DbSession) -> ActivityAnalysis:
    return _cached(analyzer, session, "activities", q, lambda c: analyzer.activities(c, q))
