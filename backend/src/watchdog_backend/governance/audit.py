"""Tamper-evident audit log.

Each entry stores the hash of the previous entry and a hash over its own content plus that
previous hash. Changing, inserting or deleting any past entry breaks the chain from that point
on, which `verify` reports. Writers take a transaction-scoped advisory lock so entries are
chained in order even under concurrency.
"""

import hashlib
import json
from datetime import datetime
from typing import Any, Literal
from uuid import UUID

from pydantic import BaseModel
from sqlalchemy import Connection, text

GENESIS = "0" * 64
_LOCK_KEY = 7_316_441  # arbitrary constant: "audit log writer"

ActorType = Literal["user", "agent", "mcp_client", "system"]


def _digest(
    prev_hash: str,
    at: datetime,
    actor: str,
    actor_type: str,
    event: str,
    request_id: UUID | None,
    details: dict[str, Any],
) -> str:
    canonical = json.dumps(
        {
            "prev": prev_hash,
            "at": at.isoformat(),
            "actor": actor,
            "actor_type": actor_type,
            "event": event,
            "request_id": str(request_id) if request_id else None,
            "details": details,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        default=str,
    )
    return hashlib.sha256(canonical.encode()).hexdigest()


def append(
    conn: Connection,
    actor: str,
    actor_type: ActorType,
    event: str,
    request_id: UUID | None = None,
    details: dict[str, Any] | None = None,
) -> str:
    details = json.loads(json.dumps(details or {}, default=str))
    conn.execute(text("SELECT pg_advisory_xact_lock(:k)"), {"k": _LOCK_KEY})
    prev = (
        conn.execute(
            text("SELECT hash FROM governance.audit_log ORDER BY entry_id DESC LIMIT 1")
        ).scalar_one_or_none()
        or GENESIS
    )
    at = conn.execute(text("SELECT date_trunc('milliseconds', now())")).scalar_one()
    digest = _digest(prev, at, actor, actor_type, event, request_id, details)
    conn.execute(
        text("""
            INSERT INTO governance.audit_log
                (at, actor, actor_type, event, request_id, details, prev_hash, hash)
            VALUES (:at, :actor, :actor_type, :event, :request_id, CAST(:details AS jsonb),
                    :prev, :hash)
        """),
        {
            "at": at,
            "actor": actor,
            "actor_type": actor_type,
            "event": event,
            "request_id": request_id,
            "details": json.dumps(details),
            "prev": prev,
            "hash": digest,
        },
    )
    return digest


class AuditEntry(BaseModel):
    entry_id: int
    at: datetime
    actor: str
    actor_type: str
    event: str
    request_id: UUID | None
    details: dict[str, Any]
    prev_hash: str
    hash: str


class Verification(BaseModel):
    ok: bool
    entries: int
    first_broken_entry: int | None = None
    reason: str | None = None


def entries(conn: Connection, request_id: UUID | None = None, limit: int = 200) -> list[AuditEntry]:
    where = "WHERE request_id = :rid" if request_id else ""
    rows = conn.execute(
        text(f"SELECT * FROM governance.audit_log {where} ORDER BY entry_id DESC LIMIT :n"),
        {"rid": request_id, "n": limit},
    ).mappings()
    return [AuditEntry(**r) for r in rows]


def verify(conn: Connection) -> Verification:
    prev = GENESIS
    n = 0
    for r in conn.execute(text("SELECT * FROM governance.audit_log ORDER BY entry_id")).mappings():
        n += 1
        if r["prev_hash"] != prev:
            return Verification(
                ok=False,
                entries=n,
                first_broken_entry=r["entry_id"],
                reason="previous-hash link does not match (entry removed or inserted)",
            )
        expected = _digest(
            prev, r["at"], r["actor"], r["actor_type"], r["event"], r["request_id"], r["details"]
        )
        if r["hash"] != expected:
            return Verification(
                ok=False,
                entries=n,
                first_broken_entry=r["entry_id"],
                reason="entry content does not match its hash (entry edited)",
            )
        prev = r["hash"]
    return Verification(ok=True, entries=n)
