"""GitHub sign-in for accounts an admin created.

`github_login` is what an admin types (a GitHub user name); `github_id` is GitHub's numeric
user id, recorded at the first GitHub sign-in. Later sign-ins match the id, so renaming a
GitHub account, or someone else taking over a freed user name, cannot move the link.

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-12
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("""
        ALTER TABLE identity.users
            ADD COLUMN github_login text,
            ADD COLUMN github_id    bigint UNIQUE;
        CREATE UNIQUE INDEX users_github_login_idx ON identity.users (lower(github_login));
    """)


def downgrade() -> None:
    op.execute("""
        DROP INDEX IF EXISTS identity.users_github_login_idx;
        ALTER TABLE identity.users DROP COLUMN IF EXISTS github_login,
                                   DROP COLUMN IF EXISTS github_id;
    """)
