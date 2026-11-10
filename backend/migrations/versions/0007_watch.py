"""Watch layer: monitor runs, alerts, and the record of simulated (synthetic) months.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-10
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE TABLE intelligence.monitor_runs (
            run_id        bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
            domain        text NOT NULL,
            started_at    timestamptz NOT NULL DEFAULT now(),
            duration_ms   integer NOT NULL,
            period        text NOT NULL,              -- latest month evaluated (YYYY-MM)
            trigger       text NOT NULL,              -- schedule | manual | simulation
            evaluated     integer NOT NULL,
            opened        integer NOT NULL,
            updated       integer NOT NULL,
            resolved      integer NOT NULL
        );

        -- One open alert per (monitor, segment); updated while the condition holds,
        -- resolved when it clears.
        CREATE TABLE intelligence.alerts (
            alert_id          uuid PRIMARY KEY DEFAULT gen_random_uuid(),
            domain            text NOT NULL,
            monitor_id        text NOT NULL,
            segment           text NOT NULL DEFAULT '',     -- e.g. "channel=broker"; '' = all
            severity          text NOT NULL CHECK (severity IN ('warning', 'critical')),
            status            text NOT NULL CHECK (status IN ('open', 'acknowledged', 'resolved')),
            value             double precision NOT NULL,
            threshold         double precision NOT NULL,
            first_period      text NOT NULL,
            last_period       text NOT NULL,
            message           text NOT NULL,
            opened_at         timestamptz NOT NULL DEFAULT now(),
            updated_at        timestamptz NOT NULL DEFAULT now(),
            acknowledged_by   text,
            acknowledged_at   timestamptz,
            resolved_at       timestamptz,
            investigation_id  uuid REFERENCES intelligence.investigations ON DELETE SET NULL
        );
        CREATE UNIQUE INDEX alerts_one_open_per_key
            ON intelligence.alerts (domain, monitor_id, segment)
            WHERE status <> 'resolved';

        -- Synthetic months appended by the demo simulator, with the actions applied to them.
        CREATE TABLE intelligence.simulated_months (
            month           text PRIMARY KEY,           -- YYYY-MM
            domain          text NOT NULL,
            generated_at    timestamptz NOT NULL DEFAULT now(),
            claims          integer NOT NULL,
            applied_actions text[] NOT NULL DEFAULT '{}',
            seed            integer NOT NULL
        );
    """)


def downgrade() -> None:
    op.execute("""
        DROP TABLE IF EXISTS intelligence.simulated_months;
        DROP TABLE IF EXISTS intelligence.alerts;
        DROP TABLE IF EXISTS intelligence.monitor_runs;
    """)
