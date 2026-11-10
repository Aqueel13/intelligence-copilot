"""Investigation runs: question, scope, models, every step and the final result.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-10
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE intelligence.investigations (
            investigation_id  uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            domain            text NOT NULL,
            question          text NOT NULL,
            scope             jsonb NOT NULL DEFAULT '{}'::jsonb,
            status            text NOT NULL CHECK (status IN ('running', 'completed', 'failed')),
            route             text,
            models            jsonb NOT NULL DEFAULT '{}'::jsonb,
            result            jsonb,
            error             text,
            created_at        timestamptz NOT NULL DEFAULT now(),
            completed_at      timestamptz,
            duration_ms       integer
        );
        CREATE INDEX investigations_created_idx
            ON intelligence.investigations (domain, created_at DESC);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS intelligence.investigations")
