"""Knowledge answer cache: reuse an answer for the same or a near-identical question, as long
as the pack's documents have not changed.

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE knowledge.answer_cache (
            cache_id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            domain          text NOT NULL,
            question        text NOT NULL,
            question_norm   text NOT NULL,          -- lower case, single spaces, no end punctuation
            embedding       vector NOT NULL,
            embedding_model text NOT NULL,
            corpus_version  text NOT NULL,          -- hash of the pack's document versions
            params_key      text NOT NULL,          -- retrieval settings the answer was made with
            answer          jsonb NOT NULL,
            model           text NOT NULL,
            tokens          integer NOT NULL DEFAULT 0,  -- what generating it cost
            created_at      timestamptz NOT NULL DEFAULT now(),
            hits            integer NOT NULL DEFAULT 0,
            last_hit_at     timestamptz
        );
        CREATE INDEX answer_cache_lookup_idx
            ON knowledge.answer_cache (domain, corpus_version, params_key, question_norm);
    """)


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS knowledge.answer_cache;")
