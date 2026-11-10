"""A stand-in for the client's systems of record (claims administration, ERP, HR).

It is deliberately dumb: it records what it is told to do, keyed by the caller's idempotency
reference, so retrying the same action request never creates a second change. In a real
deployment this is the client's system (Guidewire, a core admin platform, an HR system…) and
only `governance/executor.py` would change.

Runs as its own process (`uvicorn watchdog_backend.enterprise_mock.app:app --port 8201`).
"""

import json
import secrets
from typing import Annotated, Any

from fastapi import Depends, FastAPI, Header, HTTPException
from pydantic import BaseModel
from sqlalchemy import text

from watchdog_backend.config import get_settings
from watchdog_backend.db import get_engine

app = FastAPI(title="Mock enterprise systems", docs_url="/docs")

KINDS = {
    "approval-routing": "Approval routing rule",
    "staffing-requests": "Staffing request",
    "change-requests": "IT change request",
    "training-sessions": "Training session",
    "roster-shifts": "Roster shift",
    "payment-schedules": "Payment run schedule",
    "matching-rules": "Invoice matching rule",
}


def require_key(x_api_key: Annotated[str | None, Header()] = None) -> None:
    expected = get_settings().enterprise_api_key
    if not expected or not x_api_key or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(status_code=401, detail="Invalid or missing API key")


class ChangeIn(BaseModel):
    reference: str  # idempotency key (the action request id)
    requested_by: str
    payload: dict[str, Any]


class Record(BaseModel):
    record_id: str
    kind: str
    reference: str
    payload: dict[str, Any]
    created_by: str
    created_at: str
    created: bool  # False when this reference was already applied (idempotent replay)


@app.post("/{kind}", response_model=Record, dependencies=[Depends(require_key)])
def create(kind: str, body: ChangeIn) -> Record:
    if kind not in KINDS:
        raise HTTPException(status_code=404, detail=f"Unknown resource '{kind}'")
    with get_engine().begin() as conn:
        row = (
            conn.execute(
                text("""
                INSERT INTO mock_enterprise.records (kind, payload, reference, created_by)
                VALUES (:k, CAST(:p AS jsonb), :ref, :by)
                ON CONFLICT (reference) DO NOTHING
                RETURNING record_id, kind, reference, payload, created_by, created_at,
                          true AS created
            """),
                {
                    "k": kind,
                    "p": json.dumps(body.payload),
                    "ref": body.reference,
                    "by": body.requested_by,
                },
            )
            .mappings()
            .one_or_none()
        )
        if row is None:  # already applied: return the original record
            row = (
                conn.execute(
                    text("""SELECT record_id, kind, reference, payload, created_by, created_at,
                               false AS created
                        FROM mock_enterprise.records WHERE reference = :ref"""),
                    {"ref": body.reference},
                )
                .mappings()
                .one()
            )
    return Record(
        **{**row, "record_id": str(row["record_id"]), "created_at": str(row["created_at"])}
    )


@app.get("/records", response_model=list[Record], dependencies=[Depends(require_key)])
def records() -> list[Record]:
    with get_engine().connect() as conn:
        rows = conn.execute(
            text("""SELECT record_id, kind, reference, payload, created_by, created_at,
                           true AS created
                    FROM mock_enterprise.records ORDER BY created_at DESC LIMIT 100""")
        ).mappings()
        return [
            Record(**{**r, "record_id": str(r["record_id"]), "created_at": str(r["created_at"])})
            for r in rows
        ]


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
