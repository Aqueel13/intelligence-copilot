"""Materialize per-case activity counts so case_facts is fast under any filter.

Postgres cannot estimate selectivity of filters on JSONB attributes (e.g. team = 'Team B'),
so for narrow filters it estimated 1 row and chose a nested loop that re-aggregated every event
for every matching case (minutes instead of milliseconds). With the counts in an indexed
materialized view, any join strategy is cheap. The loader refreshes it after every load.

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-10
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_CASE_FACTS_SELECT = """
    SELECT
        c.case_id, c.domain, c.amount, c.opened_at, c.closed_at, c.sla_due_at, c.attributes,
        extract(epoch FROM c.closed_at - c.opened_at) / 3600.0 AS cycle_hours,
        c.closed_at > c.sla_due_at                            AS breached,
        coalesce(ac.counts, '{}'::jsonb)                      AS activity_counts
    FROM operational.cases c
"""


def upgrade() -> None:
    op.execute(f"""
        CREATE MATERIALIZED VIEW operational.case_activity_counts AS
        SELECT case_id, jsonb_object_agg(activity, n) AS counts
        FROM (
            SELECT case_id, activity, count(*) AS n
            FROM operational.events
            GROUP BY case_id, activity
        ) per_activity
        GROUP BY case_id;
        CREATE UNIQUE INDEX case_activity_counts_pk
            ON operational.case_activity_counts (case_id);

        CREATE OR REPLACE VIEW operational.case_facts AS
        {_CASE_FACTS_SELECT}
        LEFT JOIN operational.case_activity_counts ac USING (case_id);
    """)


def downgrade() -> None:
    op.execute(f"""
        CREATE OR REPLACE VIEW operational.case_facts AS
        {_CASE_FACTS_SELECT}
        LEFT JOIN (
            SELECT case_id, jsonb_object_agg(activity, n) AS counts
            FROM (
                SELECT case_id, activity, count(*) AS n
                FROM operational.events
                GROUP BY case_id, activity
            ) per_activity
            GROUP BY case_id
        ) ac USING (case_id);
        DROP MATERIALIZED VIEW IF EXISTS operational.case_activity_counts;
    """)
