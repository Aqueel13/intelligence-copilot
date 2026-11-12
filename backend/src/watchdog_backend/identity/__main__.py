"""Seed accounts: one admin, plus the demo users named in each pack's governance.yaml.

uv run python -m watchdog_backend.identity seed

Passwords come from ADMIN_PASSWORD and DEMO_PASSWORD (`make secrets` generates them). If one
is missing, a random one is generated and printed once. ADMIN_GITHUB_LOGIN, if set, lets that
GitHub user sign in as the admin. Existing users are never overwritten;
missing per-pack business roles are added.
"""

import argparse
import secrets

from sqlalchemy import text

from watchdog_backend.config import get_settings
from watchdog_backend.db import get_engine
from watchdog_backend.domain.pack import available_domains
from watchdog_backend.governance.config import get_governance
from watchdog_backend.identity import service as ids

GUEST = ("guest", "Guest Viewer")  # a read-only account, to show role-based access


def seed() -> None:
    s = get_settings()
    admin_pw = s.admin_password or secrets.token_urlsafe(12)
    demo_pw = s.demo_password or secrets.token_urlsafe(12)
    created = []
    with get_engine().connect() as conn:
        admin = ids.get_user(conn, "admin")
        if admin is None:
            ids.create_user(
                conn,
                "admin",
                s.admin_email,
                "Administrator",
                "admin",
                admin_pw,
                github_login=s.admin_github_login,
            )
            created.append(("admin", s.admin_email, "admin", not s.admin_password, admin_pw))
        elif s.admin_github_login and not admin.github_login:
            ids.update_user(conn, "admin", github_login=s.admin_github_login)
            print(f"  linked admin to GitHub user {s.admin_github_login}")

        people: dict[str, tuple[str, dict[str, str]]] = {}
        for domain in available_domains():
            for u in get_governance(domain).users:
                name, roles = people.get(u.id, (u.name, {}))
                roles[domain] = u.role
                people[u.id] = (name, roles)
        for user_id, (name, roles) in people.items():
            existing = ids.get_user(conn, user_id)
            if existing is None:
                ids.create_user(
                    conn, user_id, f"{user_id}@demo.watchdog", name, "analyst", demo_pw, roles
                )
                created.append(
                    (user_id, f"{user_id}@demo.watchdog", "analyst", not s.demo_password, demo_pw)
                )
            else:
                missing = {d: r for d, r in roles.items() if d not in existing.pack_roles}
                if missing:
                    ids.update_user(conn, user_id, pack_roles={**existing.pack_roles, **missing})
        if ids.get_user(conn, GUEST[0]) is None:
            ids.create_user(conn, GUEST[0], "guest@demo.watchdog", GUEST[1], "viewer", demo_pw)
            created.append(
                (GUEST[0], "guest@demo.watchdog", "viewer", not s.demo_password, demo_pw)
            )
        conn.execute(text("SELECT 1"))

    if not created:
        print("All accounts already exist.")
    for user_id, email, role, generated, pw in created:
        shown = f"password {pw} (generated: save it)" if generated else "password from .env"
        print(f"  created {user_id:12} {email:28} {role:8} {shown}")


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawTextHelpFormatter
    )
    parser.add_argument("command", choices=["seed"])
    parser.parse_args()
    seed()


if __name__ == "__main__":
    main()
