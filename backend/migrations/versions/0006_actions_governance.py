"""Action requests, approvals, tamper-evident audit log, and the mock enterprise system.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-10
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE operations.action_requests (
            request_id        uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            domain            text NOT NULL,
            action_id         text NOT NULL,                  -- catalogue action
            title             text NOT NULL,
            operation         jsonb NOT NULL,                 -- {type, params} to execute
            impact            jsonb,                          -- what-if snapshot at proposal
            policy_refs       text[] NOT NULL DEFAULT '{}',
            approver_roles    text[] NOT NULL,
            investigation_id  uuid REFERENCES intelligence.investigations ON DELETE SET NULL,
            rationale         text,
            status            text NOT NULL CHECK (status IN
                ('proposed', 'approved', 'rejected', 'executing', 'executed', 'failed')),
            requested_by      text NOT NULL,
            requested_via     text NOT NULL,                  -- ui | api | mcp:<client>
            created_at        timestamptz NOT NULL DEFAULT now(),
            executed_by       text,
            executed_at       timestamptz,
            result            jsonb,
            error             text
        );
        CREATE INDEX action_requests_status_idx
            ON operations.action_requests (domain, status, created_at DESC);

        CREATE TABLE operations.approvals (
            approval_id  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            request_id   uuid NOT NULL UNIQUE
                         REFERENCES operations.action_requests ON DELETE CASCADE,
            decision     text NOT NULL CHECK (decision IN ('approved', 'rejected')),
            decided_by   text NOT NULL,
            role         text NOT NULL,
            note         text,
            decided_at   timestamptz NOT NULL DEFAULT now()
        );

        -- Append-only, hash-chained: each entry's hash covers its content and the previous
        -- hash, so editing or deleting any past entry breaks verification.
        CREATE TABLE governance.audit_log (
            entry_id    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            at          timestamptz NOT NULL DEFAULT now(),
            actor       text NOT NULL,
            actor_type  text NOT NULL
                        CHECK (actor_type IN ('user', 'agent', 'mcp_client', 'system')),
            event       text NOT NULL,
            request_id  uuid,
            details     jsonb NOT NULL DEFAULT '{}'::jsonb,
            prev_hash   text NOT NULL,
            hash        text NOT NULL UNIQUE
        );
        CREATE INDEX audit_request_idx ON governance.audit_log (request_id);

        -- A stand-in for the client's claims administration system (what actions change).
        CREATE SCHEMA IF NOT EXISTS mock_enterprise;
        CREATE TABLE mock_enterprise.records (
            record_id    uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            kind         text NOT NULL,
            payload      jsonb NOT NULL,
            reference    text NOT NULL UNIQUE,      -- idempotency key from the caller
            created_by   text NOT NULL,
            created_at   timestamptz NOT NULL DEFAULT now()
        );
    """)


def downgrade() -> None:
    op.execute("""
        DROP SCHEMA IF EXISTS mock_enterprise CASCADE;
        DROP TABLE IF EXISTS governance.audit_log;
        DROP TABLE IF EXISTS operations.approvals;
        DROP TABLE IF EXISTS operations.action_requests;
    """)
