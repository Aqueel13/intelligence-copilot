"""Investigation cache and showcase runs; usage events for rate limits.

Investigations now keep the stream they produced (`events`), so a run can be replayed step by
step without any model call: as a cache hit for an identical request, or as a showcase run an
admin picked for visitors. `cache_key` hashes everything the result depends on.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE intelligence.investigations
            ADD COLUMN events    jsonb,                          -- the recorded SSE steps
            ADD COLUMN cache_key text,
            ADD COLUMN user_id   text,
            ADD COLUMN showcase  boolean NOT NULL DEFAULT false;
        CREATE INDEX investigations_cache_idx
            ON intelligence.investigations (cache_key, completed_at DESC)
            WHERE status = 'completed';
        CREATE INDEX investigations_showcase_idx
            ON intelligence.investigations (domain) WHERE showcase;

        -- One row per request that spent model tokens (cache hits are free and not counted).
        CREATE TABLE identity.usage_events (
            event_id  bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            user_id   text NOT NULL,
            action    text NOT NULL,                             -- investigate | ask
            at        timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX usage_events_user_idx ON identity.usage_events (user_id, action, at DESC);
        CREATE INDEX usage_events_action_idx ON identity.usage_events (action, at DESC);
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE IF EXISTS identity.usage_events;
        DROP INDEX IF EXISTS intelligence.investigations_showcase_idx;
        DROP INDEX IF EXISTS intelligence.investigations_cache_idx;
        ALTER TABLE intelligence.investigations
            DROP COLUMN IF EXISTS events,
            DROP COLUMN IF EXISTS cache_key,
            DROP COLUMN IF EXISTS user_id,
            DROP COLUMN IF EXISTS showcase;
    """)
