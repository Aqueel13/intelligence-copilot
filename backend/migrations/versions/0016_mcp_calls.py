"""Observability: every MCP tool call (server, tool, client, pack, outcome, latency).

Arguments are not stored: they can carry a client's SQL or search text.

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE observability.mcp_calls (
            call_id      bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            at           timestamptz NOT NULL DEFAULT now(),
            server       text NOT NULL,                  -- analytics | knowledge | operations
            tool         text NOT NULL,
            client       text NOT NULL,                  -- the name its token maps to
            domain       text,                           -- NULL: the tool takes no pack
            status       text NOT NULL,                  -- ok | error
            duration_ms  integer NOT NULL,
            error        text
        );
        CREATE INDEX mcp_calls_at_idx ON observability.mcp_calls (at DESC);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS observability.mcp_calls;")
