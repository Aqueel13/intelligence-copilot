"""Generic process data: cases, events, feedback, and analytical fact views.

Domain-specific attributes (channel, region, ...) live in `cases.attributes` (JSONB), so the
same tables serve every domain pack.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-10
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE operational.cases (
            case_id     text PRIMARY KEY,
            domain      text NOT NULL,
            amount      numeric(14, 2) NOT NULL CHECK (amount >= 0),
            opened_at   timestamptz NOT NULL,
            closed_at   timestamptz,
            sla_due_at  timestamptz NOT NULL,
            attributes  jsonb NOT NULL DEFAULT '{}'::jsonb,
            CHECK (closed_at IS NULL OR closed_at >= opened_at)
        );
        CREATE INDEX cases_domain_opened_idx ON operational.cases (domain, opened_at);
        CREATE INDEX cases_attributes_idx ON operational.cases USING gin (attributes);

        CREATE TABLE operational.events (
            event_id    bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            case_id     text NOT NULL REFERENCES operational.cases ON DELETE CASCADE,
            seq         integer NOT NULL,
            activity    text NOT NULL,
            resource    text NOT NULL,
            started_at  timestamptz NOT NULL,
            ended_at    timestamptz NOT NULL,
            UNIQUE (case_id, seq),
            CHECK (ended_at >= started_at)
        );
        CREATE INDEX events_activity_idx ON operational.events (activity);

        CREATE TABLE operational.feedback (
            case_id       text PRIMARY KEY REFERENCES operational.cases ON DELETE CASCADE,
            sent_at       timestamptz NOT NULL,
            responded_at  timestamptz,
            csat          smallint CHECK (csat BETWEEN 1 AND 5),
            nps           smallint CHECK (nps BETWEEN 0 AND 10),
            comment       text,
            CHECK ((responded_at IS NULL) = (csat IS NULL))
        );
    """)

    op.execute("""
        CREATE VIEW operational.case_facts AS
        SELECT
            c.case_id, c.domain, c.amount, c.opened_at, c.closed_at, c.sla_due_at, c.attributes,
            extract(epoch FROM c.closed_at - c.opened_at) / 3600.0 AS cycle_hours,
            c.closed_at > c.sla_due_at                            AS breached,
            coalesce(ac.counts, '{}'::jsonb)                      AS activity_counts
        FROM operational.cases c
        LEFT JOIN LATERAL (
            SELECT jsonb_object_agg(activity, n) AS counts
            FROM (
                SELECT activity, count(*) AS n
                FROM operational.events e
                WHERE e.case_id = c.case_id
                GROUP BY activity
            ) per_activity
        ) ac ON true;

        CREATE VIEW operational.event_facts AS
        SELECT
            e.event_id, e.case_id, e.seq, e.activity, e.resource, e.started_at, e.ended_at,
            c.domain, c.amount, c.opened_at, c.attributes,
            prev.handoff_at,
            coalesce(extract(epoch FROM e.started_at - prev.handoff_at) / 3600.0, 0) AS wait_hours,
            extract(epoch FROM e.ended_at - e.started_at) / 3600.0                AS work_hours,
            row_number() OVER (PARTITION BY e.case_id, e.activity ORDER BY e.seq) AS occurrence
        FROM operational.events e
        JOIN operational.cases c USING (case_id)
        LEFT JOIN LATERAL (
            SELECT p.ended_at AS handoff_at
            FROM operational.events p
            WHERE p.case_id = e.case_id AND p.seq < e.seq
            ORDER BY p.seq DESC
            LIMIT 1
        ) prev ON true;

        CREATE VIEW operational.feedback_facts AS
        SELECT
            f.case_id, f.sent_at, f.responded_at, f.csat, f.nps, f.comment,
            f.responded_at IS NOT NULL AS responded,
            c.domain, c.amount, c.opened_at, c.attributes
        FROM operational.feedback f
        JOIN operational.cases c USING (case_id);
    """)


def downgrade() -> None:
    op.execute("""
        DROP VIEW IF EXISTS operational.feedback_facts;
        DROP VIEW IF EXISTS operational.event_facts;
        DROP VIEW IF EXISTS operational.case_facts;
        DROP TABLE IF EXISTS operational.feedback;
        DROP TABLE IF EXISTS operational.events;
        DROP TABLE IF EXISTS operational.cases;
    """)
