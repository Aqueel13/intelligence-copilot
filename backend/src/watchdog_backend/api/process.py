from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

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


def _guard[T](fn: Callable[[], T]) -> T:
    try:
        return fn()
    except MetricQueryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc


@router.post("/map", response_model=ProcessMap)
def process_map(q: ProcessQuery, analyzer: Analyzer, session: DbSession) -> ProcessMap:
    return _guard(lambda: analyzer.process_map(session.connection(), q))


@router.post("/variants", response_model=VariantSummary)
def variants(
    q: ProcessQuery,
    analyzer: Analyzer,
    session: DbSession,
    top: Annotated[int, Query(ge=1, le=50)] = 10,
) -> VariantSummary:
    return _guard(lambda: analyzer.variants(session.connection(), q, top))


@router.post("/activities", response_model=ActivityAnalysis)
def activities(q: ProcessQuery, analyzer: Analyzer, session: DbSession) -> ActivityAnalysis:
    return _guard(lambda: analyzer.activities(session.connection(), q))
