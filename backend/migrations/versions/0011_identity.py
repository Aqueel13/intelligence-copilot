"""Identity: user accounts, per-pack business roles, sessions.

Platform role (viewer | analyst | admin) decides what someone may do in the app; the business
role in each pack (e.g. "Head of Claims") decides which actions they may approve there.

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-11
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        CREATE SCHEMA IF NOT EXISTS identity;

        CREATE TABLE identity.users (
            user_id        text PRIMARY KEY,                 -- short handle, e.g. a.rao
            email          text NOT NULL UNIQUE,
            name           text NOT NULL,
            password_hash  text,                             -- NULL: cannot sign in with a password
            platform_role  text NOT NULL CHECK (platform_role IN ('viewer', 'analyst', 'admin')),
            active         boolean NOT NULL DEFAULT true,
            auth_provider  text NOT NULL DEFAULT 'local',    -- local | github (later)
            created_at     timestamptz NOT NULL DEFAULT now(),
            last_login_at  timestamptz
        );

        CREATE TABLE identity.pack_roles (
            user_id        text NOT NULL REFERENCES identity.users ON DELETE CASCADE,
            domain         text NOT NULL,
            business_role  text NOT NULL,
            PRIMARY KEY (user_id, domain)
        );

        CREATE TABLE identity.sessions (
            token_hash     text PRIMARY KEY,                 -- sha256 of the cookie value
            user_id        text NOT NULL REFERENCES identity.users ON DELETE CASCADE,
            acting_as      text REFERENCES identity.users ON DELETE SET NULL,  -- admins only
            created_at     timestamptz NOT NULL DEFAULT now(),
            expires_at     timestamptz NOT NULL,
            last_seen_at   timestamptz NOT NULL DEFAULT now()
        );
        CREATE INDEX sessions_user_idx ON identity.sessions (user_id);
    """)


def downgrade() -> None:
    op.execute("DROP SCHEMA IF EXISTS identity CASCADE;")
