"""Rate limits on the requests that spend model tokens.

Two rolling windows per action: per user per hour, and for everyone together per day (free
tiers cap tokens per model per day, shared by every visitor). Only requests that actually call
a model count: cache hits and showcase replays are free. Admins are exempt. While an admin acts
as someone else, the limits of the real person apply (they are the one spending).

Counts live in Postgres (`identity.usage_events`), so they survive restarts and hold with
several workers. Check and charge are separate statements, so two simultaneous requests can
overshoot a limit by one; that is acceptable for a cost guard.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Literal

from sqlalchemy import Connection, text

from watchdog_backend.config import get_settings
from watchdog_backend.identity.service import Principal

Action = Literal["investigate", "ask"]
ACTIONS: tuple[Action, ...] = ("investigate", "ask")
HOUR = timedelta(hours=1)
DAY = timedelta(days=1)


class RateLimited(Exception):
    def __init__(self, message: str, retry_after: int) -> None:
        super().__init__(message)
        self.retry_after = retry_after


@dataclass(frozen=True)
class Window:
    scope: Literal["user", "everyone"]
    limit: int  # 0 = no limit
    used: int
    resets_in: int  # seconds until the oldest counted request leaves the window (0 if none)


def _limits(action: Action) -> tuple[int, int]:
    s = get_settings()
    if action == "investigate":
        return s.rate_limit_investigations_per_user_hour, s.rate_limit_investigations_per_day
    return s.rate_limit_questions_per_user_hour, s.rate_limit_questions_per_day


def _window(
    conn: Connection, action: Action, period: timedelta, limit: int, user_id: str | None
) -> Window:
    row = conn.execute(
        text(f"""SELECT count(*), min(at) FROM identity.usage_events
                 WHERE action = :a AND at > now() - :p
                 {"AND user_id = :u" if user_id else ""}"""),
        {"a": action, "p": period, "u": user_id},
    ).one()
    used, oldest = row
    resets_in = 0
    if oldest is not None:
        resets_in = max(1, int((oldest + period - datetime.now(UTC)).total_seconds()) + 1)
    return Window("user" if user_id else "everyone", limit, used, resets_in)


def exempt(who: Principal) -> bool:
    return who.real.platform_role == "admin"


def status(conn: Connection, who: Principal, action: Action) -> list[Window]:
    per_user, per_day = _limits(action)
    return [
        _window(conn, action, HOUR, per_user, who.real.user_id),
        _window(conn, action, DAY, per_day, None),
    ]


def check(conn: Connection, who: Principal, action: Action) -> None:
    """Raise RateLimited if another request of this kind would exceed a limit."""
    if exempt(who):
        return
    what = "investigations" if action == "investigate" else "questions"
    user, everyone = status(conn, who, action)
    if user.limit and user.used >= user.limit:
        raise RateLimited(
            f"You have started {user.used} {what} in the last hour (limit {user.limit}). "
            f"Try again in {_minutes(user.resets_in)}. Showcase runs and repeated questions "
            "do not count.",
            user.resets_in,
        )
    if everyone.limit and everyone.used >= everyone.limit:
        raise RateLimited(
            f"The demo's daily budget of {everyone.limit} new {what} is used up. Try again in "
            f"{_minutes(everyone.resets_in)}; showcase runs can still be replayed.",
            everyone.resets_in,
        )


def charge(conn: Connection, who: Principal, action: Action) -> None:
    """Count one request that spent model tokens."""
    conn.execute(
        text("INSERT INTO identity.usage_events (user_id, action) VALUES (:u, :a)"),
        {"u": who.real.user_id, "a": action},
    )
    # Nothing older than the longest window is ever read.
    conn.execute(text("DELETE FROM identity.usage_events WHERE at < now() - interval '2 days'"))


def _minutes(seconds: int) -> str:
    if seconds < 90:
        return f"{seconds} s"
    if seconds < 2 * 3600:
        return f"{round(seconds / 60)} min"
    return f"{round(seconds / 3600)} h"
