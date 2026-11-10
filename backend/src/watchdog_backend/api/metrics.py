from functools import lru_cache
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from watchdog_backend.analytics.metrics import (
    MetricQuery,
    MetricQueryError,
    MetricResult,
    MetricsEngine,
)
from watchdog_backend.db import get_session
from watchdog_backend.domain.pack import get_pack

router = APIRouter(prefix="/metrics", tags=["metrics"])


@lru_cache
def get_engine() -> MetricsEngine:
    return MetricsEngine(get_pack())


class DimensionInfo(BaseModel):
    name: str
    label: str
    values: list[str] | None


class MetricInfo(BaseModel):
    name: str
    label: str
    description: str
    unit: str
    dimensions: list[DimensionInfo]


@router.get("", response_model=list[MetricInfo])
def list_metrics(engine: Annotated[MetricsEngine, Depends(get_engine)]) -> list[MetricInfo]:
    return [
        MetricInfo(
            name=m.name,
            label=m.label,
            description=m.description,
            unit=m.unit,
            dimensions=[
                DimensionInfo(
                    name=d.name, label=d.label, values=list(d.values) if d.values else None
                )
                for d in engine.dimensions_for(m.base)
            ],
        )
        for m in engine.pack.metrics.values()
    ]


@router.post("/query", response_model=MetricResult)
def query_metric(
    q: MetricQuery,
    engine: Annotated[MetricsEngine, Depends(get_engine)],
    session: Annotated[Session, Depends(get_session)],
) -> MetricResult:
    try:
        return engine.run(session.connection(), q)
    except MetricQueryError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
