"""event_facts: partition its windows by pack and open date so scope filters apply first.

Postgres can only move a filter below a window function when the filtered column is in every
PARTITION BY. The 0003 view partitioned by case alone, so each query computed waiting times
for every event of every pack before keeping one pack and one period. A case has one pack and
one open date, so adding them to the partitions changes no result; the pack filter (always
present) and period filters on `opened_at` now run before the windows. Filtered process
queries are 3-4x faster; unfiltered ones skip the other packs' events.

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _view(partition: str) -> str:
    return f"""
        CREATE OR REPLACE VIEW operational.event_facts AS
        SELECT
            e.event_id, e.case_id, e.seq, e.activity, e.resource, e.started_at, e.ended_at,
            c.domain, c.amount, c.opened_at, c.attributes,
            lag(e.ended_at) OVER by_case AS handoff_at,
            coalesce(extract(epoch FROM e.started_at - lag(e.ended_at) OVER by_case) / 3600.0, 0)
                AS wait_hours,
            extract(epoch FROM e.ended_at - e.started_at) / 3600.0 AS work_hours,
            row_number() OVER (PARTITION BY {partition}, e.activity ORDER BY e.seq) AS occurrence
        FROM operational.events e
        JOIN operational.cases c USING (case_id)
        WINDOW by_case AS (PARTITION BY {partition} ORDER BY e.seq);
    """


def upgrade() -> None:
    op.execute(_view("c.domain, c.opened_at, e.case_id"))


def downgrade() -> None:
    op.execute(_view("e.case_id"))
