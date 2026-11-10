"""Accounts, sessions and the current principal."""

import hashlib
import secrets
import time
from contextvars import ContextVar
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any

from pydantic import BaseModel
from sqlalchemy import Connection, text

from watchdog_backend.config import get_settings
from watchdog_backend.identity import rbac
from watchdog_backend.identity.passwords import check_strength, hash_password, verify_password


class UserOut(BaseModel):
    user_id: str
    email: str
    name: str
    platform_role: str
    active: bool
    pack_roles: dict[str, str]  # domain -> business role
    last_login_at: datetime | None = None


@dataclass(frozen=True)
class Principal:
    """Who is making the request. `user` is the effective identity (what permissions and
    approvals use); `real` differs only while an admin acts as someone else."""

    user: UserOut
    real: UserOut

    @property
    def impersonating(self) -> bool:
        return self.user.user_id != self.real.user_id

    def can(self, permission: str) -> bool:
        return rbac.allowed(self.user.platform_role, permission)


_principal: ContextVar[Principal | None] = ContextVar("principal", default=None)


def current_principal() -> Principal | None:
    return _principal.get()


def set_principal(p: Principal | None):
    return _principal.set(p)


def reset_principal(token) -> None:
    _principal.reset(token)


class IdentityError(Exception):
    def __init__(self, code: str, message: str) -> None:
        self.code = code  # unauthorized | forbidden | not_found | conflict | invalid
        super().__init__(message)


# ---------------------------------------------------------------------------- users


def _users(
    conn: Connection, where: str = "", params: dict[str, Any] | None = None
) -> list[UserOut]:
    rows = conn.execute(
        text(f"""SELECT u.user_id, u.email, u.name, u.platform_role, u.active, u.last_login_at,
                        coalesce(jsonb_object_agg(r.domain, r.business_role)
                                 FILTER (WHERE r.domain IS NOT NULL), '{{}}') AS pack_roles
                 FROM identity.users u
                 LEFT JOIN identity.pack_roles r USING (user_id)
                 {where}
                 GROUP BY u.user_id
                 ORDER BY array_position(ARRAY['admin', 'analyst', 'viewer'], u.platform_role),
                          u.name"""),
        params or {},
    ).mappings()
    return [UserOut(**r) for r in rows]


def list_users(conn: Connection) -> list[UserOut]:
    return _users(conn)


def get_user(conn: Connection, user_id: str) -> UserOut | None:
    found = _users(conn, "WHERE u.user_id = :id", {"id": user_id})
    return found[0] if found else None


def create_user(
    conn: Connection,
    user_id: str,
    email: str,
    name: str,
    platform_role: str,
    password: str | None,
    pack_roles: dict[str, str] | None = None,
) -> UserOut:
    if platform_role not in rbac.ROLES:
        raise IdentityError("invalid", f"Unknown platform role '{platform_role}'")
    if password is not None:
        try:
            check_strength(password)
        except ValueError as exc:
            raise IdentityError("invalid", str(exc)) from exc
    exists = conn.execute(
        text("SELECT 1 FROM identity.users WHERE user_id = :id OR lower(email) = lower(:e)"),
        {"id": user_id, "e": email},
    ).first()
    if exists:
        raise IdentityError("conflict", "A user with this id or email already exists")
    conn.execute(
        text("""INSERT INTO identity.users (user_id, email, name, password_hash, platform_role)
                VALUES (:id, lower(:e), :n, :h, :r)"""),
        {
            "id": user_id,
            "e": email,
            "n": name,
            "h": hash_password(password) if password else None,
            "r": platform_role,
        },
    )
    _set_pack_roles(conn, user_id, pack_roles or {})
    conn.commit()
    return get_user(conn, user_id)  # type: ignore[return-value]


def update_user(conn: Connection, user_id: str, **changes: Any) -> UserOut:
    if get_user(conn, user_id) is None:
        raise IdentityError("not_found", f"User '{user_id}' not found")
    if "platform_role" in changes and changes["platform_role"] not in rbac.ROLES:
        raise IdentityError("invalid", "Unknown platform role")
    sets, params = [], {"id": user_id}
    for col in ("name", "platform_role", "active"):
        if changes.get(col) is not None:
            sets.append(f"{col} = :{col}")
            params[col] = changes[col]
    if changes.get("password"):
        try:
            check_strength(changes["password"])
        except ValueError as exc:
            raise IdentityError("invalid", str(exc)) from exc
        sets.append("password_hash = :h")
        params["h"] = hash_password(changes["password"])
    if sets:
        conn.execute(
            text(f"UPDATE identity.users SET {', '.join(sets)} WHERE user_id = :id"), params
        )
    if changes.get("pack_roles") is not None:
        _set_pack_roles(conn, user_id, changes["pack_roles"])
    if changes.get("active") is False or changes.get("password"):
        # Deactivating or resetting a password ends every session.
        conn.execute(text("DELETE FROM identity.sessions WHERE user_id = :id"), {"id": user_id})
    conn.commit()
    return get_user(conn, user_id)  # type: ignore[return-value]


def _set_pack_roles(conn: Connection, user_id: str, roles: dict[str, str]) -> None:
    conn.execute(text("DELETE FROM identity.pack_roles WHERE user_id = :id"), {"id": user_id})
    for domain, role in roles.items():
        if role:
            conn.execute(
                text("""INSERT INTO identity.pack_roles (user_id, domain, business_role)
                        VALUES (:id, :d, :r)"""),
                {"id": user_id, "d": domain, "r": role},
            )


def admin_count(conn: Connection) -> int:
    return conn.execute(
        text("SELECT count(*) FROM identity.users WHERE platform_role = 'admin' AND active")
    ).scalar_one()


# ------------------------------------------------------------------------- sessions


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode()).hexdigest()


def login(conn: Connection, email: str, password: str) -> tuple[str, UserOut]:
    row = (
        conn.execute(
            text("""SELECT user_id, password_hash, active FROM identity.users
                WHERE lower(email) = lower(:e)"""),
            {"e": email.strip()},
        )
        .mappings()
        .one_or_none()
    )
    ok = verify_password(password, row["password_hash"] if row else None)
    if not row or not ok or not row["active"]:
        time.sleep(0.3)  # same response, same-ish time, for every failure
        raise IdentityError("unauthorized", "Wrong email or password")
    token = create_session(conn, row["user_id"])
    conn.execute(
        text("UPDATE identity.users SET last_login_at = now() WHERE user_id = :id"),
        {"id": row["user_id"]},
    )
    conn.commit()
    return token, get_user(conn, row["user_id"])  # type: ignore[return-value]


def create_session(conn: Connection, user_id: str) -> str:
    token = secrets.token_urlsafe(32)
    expires = datetime.now(UTC) + timedelta(hours=get_settings().session_hours)
    conn.execute(
        text("""INSERT INTO identity.sessions (token_hash, user_id, expires_at)
                VALUES (:t, :u, :x)"""),
        {"t": _hash(token), "u": user_id, "x": expires},
    )
    conn.commit()
    return token


def logout(conn: Connection, token: str) -> None:
    conn.execute(text("DELETE FROM identity.sessions WHERE token_hash = :t"), {"t": _hash(token)})
    conn.commit()


def resolve(conn: Connection, token: str) -> Principal | None:
    """The principal for a session cookie; extends the session (sliding expiry)."""
    row = (
        conn.execute(
            text("""SELECT s.user_id, s.acting_as FROM identity.sessions s
                JOIN identity.users u USING (user_id)
                WHERE s.token_hash = :t AND s.expires_at > now() AND u.active"""),
            {"t": _hash(token)},
        )
        .mappings()
        .one_or_none()
    )
    if row is None:
        return None
    hours = get_settings().session_hours
    conn.execute(
        text("""UPDATE identity.sessions
                SET last_seen_at = now(), expires_at = now() + make_interval(hours => :h)
                WHERE token_hash = :t"""),
        {"t": _hash(token), "h": hours},
    )
    conn.commit()
    real = get_user(conn, row["user_id"])
    effective = get_user(conn, row["acting_as"]) if row["acting_as"] else None
    if real is None:
        return None
    if effective is None or not effective.active or real.platform_role != "admin":
        effective = real
    return Principal(user=effective, real=real)


def act_as(conn: Connection, token: str, principal: Principal, user_id: str | None) -> None:
    if principal.real.platform_role != "admin":
        raise IdentityError("forbidden", "Only an admin can act as another user")
    if user_id is not None and user_id != principal.real.user_id:
        target = get_user(conn, user_id)
        if target is None or not target.active:
            raise IdentityError("not_found", f"User '{user_id}' not found")
    else:
        user_id = None
    conn.execute(
        text("UPDATE identity.sessions SET acting_as = :a WHERE token_hash = :t"),
        {"a": user_id, "t": _hash(token)},
    )
    conn.commit()
