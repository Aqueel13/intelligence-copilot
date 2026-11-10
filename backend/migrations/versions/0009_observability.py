"""Observability: every LLM call (including knowledge-cache hits) and every API request.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE SCHEMA IF NOT EXISTS observability;

        CREATE TABLE observability.llm_calls (
            call_id          bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            at               timestamptz NOT NULL DEFAULT now(),
            domain           text,
            role             text NOT NULL,              -- router, planner, assessor, answer…
            model            text NOT NULL,              -- provider:model
            provider         text NOT NULL,
            tier             text NOT NULL DEFAULT 'standard',  -- standard | light
            purpose          text,                       -- investigation | qa | evaluation …
            investigation_id uuid,
            user_id          text,
            duration_ms      integer NOT NULL,
            input_tokens     integer NOT NULL DEFAULT 0,
            output_tokens    integer NOT NULL DEFAULT 0,
            status           text NOT NULL,              -- ok | error | cache_hit
            error            text,
            tokens_saved     integer NOT NULL DEFAULT 0  -- cache hits: tokens not spent
        );
        CREATE INDEX llm_calls_at_idx ON observability.llm_calls (at DESC);
        CREATE INDEX llm_calls_investigation_idx
            ON observability.llm_calls (investigation_id) WHERE investigation_id IS NOT NULL;

        CREATE TABLE observability.api_requests (
            request_id   bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            at           timestamptz NOT NULL DEFAULT now(),
            method       text NOT NULL,
            route        text NOT NULL,                  -- the route template, not the raw path
            status       integer NOT NULL,
            duration_ms  integer NOT NULL,
            domain       text,
            user_id      text
        );
        CREATE INDEX api_requests_at_idx ON observability.api_requests (at DESC);
    """)


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS observability CASCADE;")
