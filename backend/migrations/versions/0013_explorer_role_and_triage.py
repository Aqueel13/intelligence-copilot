"""Exploratory SQL role; automatic triage of alerts.

`watchdog_explorer` can only SELECT the three fact views. The app switches to it (SET LOCAL
ROLE) for exploratory queries, so a query cannot read accounts, sessions, the audit log or
anything else, whatever it says. Roles are cluster-wide, so it is created only if missing and
left in place on downgrade (other databases on the server may use it).

Alerts record what automatic triage did with them.

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VIEWS = "operational.case_facts, operational.event_facts, operational.feedback_facts"


def upgrade() -> None:
    op.execute("""
        DO $$
        BEGIN
            IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'watchdog_explorer') THEN
                CREATE ROLE watchdog_explorer NOLOGIN NOINHERIT;
            END IF;
        END $$;
    """)
    op.execute(f"""
        GRANT USAGE ON SCHEMA operational TO watchdog_explorer;
        GRANT SELECT ON {VIEWS} TO watchdog_explorer;
        GRANT watchdog_explorer TO CURRENT_USER;

        ALTER TABLE intelligence.alerts
            ADD COLUMN triage_status text CHECK (triage_status IN
                ('running', 'investigated', 'reused', 'skipped', 'failed')),
            ADD COLUMN triage_note   text,
            ADD COLUMN triaged_at    timestamptz;
    """)


def downgrade() -> None:
    op.execute(f"""
        ALTER TABLE intelligence.alerts
            DROP COLUMN IF EXISTS triage_status,
            DROP COLUMN IF EXISTS triage_note,
            DROP COLUMN IF EXISTS triaged_at;
        REVOKE SELECT ON {VIEWS} FROM watchdog_explorer;
        REVOKE USAGE ON SCHEMA operational FROM watchdog_explorer;
    """)
