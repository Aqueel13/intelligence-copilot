"""Automatic triage: the Watch layer investigates new alerts without waiting for a click.

After monitors run, open alerts that nobody has investigated are ranked (critical before
warning, then by how far past its threshold the KPI is, then oldest first) and the top ones
are investigated with the alert's own question and scope, as the system user.

Cost guards:
- An identical earlier run (same question, scope, models, data, documents, pack) is linked
  instead of re-run ("reused"): no tokens.
- At most WATCH_AUTO_INVESTIGATE_MAX_PER_RUN new investigations per pack per monitor run; the
  rest wait for the next run.
- The shared daily investigation budget applies (identity/limits.py): when it is used up the
  alert is marked "skipped" with the reason and reconsidered on later runs; a person can
  still investigate it. A "failed" run is not retried automatically (a persistent error would
  otherwise repeat every run); its note says why, and the alert stays open to investigate.
- WATCH_AUTO_INVESTIGATE: off | critical (default) | all (warnings too).

An alert is claimed with a conditional UPDATE before any work, so the watcher and the web app
never investigate the same alert twice.
"""

import logging
import threading
from contextvars import copy_context
from dataclasses import dataclass
from typing import Any

from sqlalchemy import Connection, text

from watchdog_backend.analytics.metrics import MetricsEngine
from watchdog_backend.analytics.process import ProcessQuery
from watchdog_backend.config import get_settings
from watchdog_backend.db import get_engine
from watchdog_backend.domain.pack import current_domain, get_pack
from watchdog_backend.identity import limits
from watchdog_backend.investigation.service import find_previous_run, run_investigation
from watchdog_backend.watch.engine import Evaluation, evaluate, get_monitors, latest_period

log = logging.getLogger("watchdog.triage")
SYSTEM_USER = "watchdog-watch"


@dataclass(frozen=True)
class Outcome:
    alert_id: str
    status: str  # investigated | reused | skipped | failed
    note: str
    investigation_id: str | None


def _excess(alert: dict[str, Any], e: Evaluation) -> float:
    """How far past its threshold the KPI is, relative to the threshold."""
    t = alert["threshold"] or 1e-9
    gap = alert["value"] - t if e.direction == "above" else t - alert["value"]
    return gap / abs(t)


def ranked(conn: Connection, evaluations: list[Evaluation], severities: set[str]) -> list[tuple]:
    """(alert row, its evaluation, excess) for open alerts not yet investigated (new, or skipped
    earlier for budget), highest priority first."""
    rows = conn.execute(
        text("""SELECT alert_id, monitor_id, segment, severity, value, threshold, opened_at
                FROM intelligence.alerts
                WHERE domain = :d AND status = 'open' AND investigation_id IS NULL
                  AND (triage_status IS NULL OR triage_status = 'skipped')"""),
        {"d": get_pack().domain},
    ).mappings()
    by_key = {(e.monitor_id, e.segment): e for e in evaluations}
    out = []
    for r in rows:
        e = by_key.get((r["monitor_id"], r["segment"]))
        if e is not None and r["severity"] in severities:
            out.append((dict(r), e, _excess(r, e)))
    out.sort(key=lambda x: (x[0]["severity"] != "critical", -x[2], x[0]["opened_at"]))
    return out


def _claim(conn: Connection, alert_id: Any) -> bool:
    claimed = conn.execute(
        text("""UPDATE intelligence.alerts SET triage_status = 'running', triaged_at = now()
                WHERE alert_id = :id AND investigation_id IS NULL
                  AND (triage_status IS NULL OR triage_status = 'skipped')"""),
        {"id": alert_id},
    ).rowcount
    conn.commit()
    return claimed == 1


def _finish(conn: Connection, alert_id: Any, status: str, note: str, inv_id: str | None) -> None:
    conn.execute(
        text("""UPDATE intelligence.alerts
                SET triage_status = :s, triage_note = :n, triaged_at = now(),
                    investigation_id = coalesce(CAST(:i AS uuid), investigation_id)
                WHERE alert_id = :id"""),
        {"id": alert_id, "s": status, "n": note, "i": inv_id},
    )
    conn.commit()


def _budget_left(conn: Connection) -> str | None:
    """None if the shared daily budget allows another investigation, else the reason."""
    _, per_day = limits._limits("investigate")
    w = limits._window(conn, "investigate", limits.DAY, per_day, None)
    if w.limit and w.used >= w.limit:
        return (
            f"The daily budget of {w.limit} new investigations is used up "
            "(resets within 24 hours). Investigate it from the alert when needed."
        )
    return None


def triage(conn: Connection, evaluations: list[Evaluation] | None = None) -> list[Outcome]:
    """Triage the active pack's open alerts. Returns what was done with each one touched."""
    s = get_settings()
    if s.watch_auto_investigate == "off":
        return []
    severities = {"critical"} if s.watch_auto_investigate == "critical" else {"critical", "warning"}
    if evaluations is None:
        period = latest_period(conn)
        if period is None:
            return []
        engine = MetricsEngine(get_pack())
        evaluations = [e for m in get_monitors() for e in evaluate(conn, engine, m, period)]
    queue = ranked(conn, evaluations, severities)
    conn.commit()  # end the read transaction before long-running work
    outcomes: list[Outcome] = []
    started = 0
    for position, (alert, e, _excess) in enumerate(queue, start=1):
        if started >= s.watch_auto_investigate_max_per_run:
            break
        if not _claim(conn, alert["alert_id"]):
            continue
        why = (
            f"Ranked {position} of {len(queue)} alerts awaiting triage ({alert['severity']}, "
            f"{e.message})."
        )
        scope = ProcessQuery(filters=e.scope)
        try:
            key, _, previous = find_previous_run(conn, e.question, scope)
            conn.commit()
            if previous is not None:
                inv, status = str(previous["investigation_id"]), "reused"
                note = (
                    f"{why} The same question on the same data was investigated on "
                    f"{previous['completed_at']:%d %b %Y}; that run is linked (no new model calls)."
                )
            elif reason := _budget_left(conn):
                inv, status, note = None, "skipped", f"{why} {reason}"
            else:
                conn.execute(
                    text("INSERT INTO identity.usage_events (user_id, action) VALUES (:u, :a)"),
                    {"u": SYSTEM_USER, "a": "investigate"},
                )
                conn.commit()
                started += 1
                inv, error = run_investigation(e.question, scope, {"user_id": SYSTEM_USER}, key)
                if error:  # not linked: the alert stays open for a person (or the next run)
                    status = "failed"
                    note = f"{why} The automatic investigation {inv} failed: {error}"
                    inv = None
                else:
                    status, note = "investigated", f"{why} Investigated automatically."
        except Exception as exc:  # never leave an alert stuck in "running"
            conn.rollback()
            inv, status, note = None, "failed", f"{why} Could not start: {str(exc)[:300]}"
        _finish(conn, alert["alert_id"], status, note, inv)
        outcomes.append(Outcome(str(alert["alert_id"]), status, note, inv))
        log.info("%s alert %s: %s", get_pack().domain, alert["alert_id"], status)
    return outcomes


_running: set[str] = set()
_lock = threading.Lock()


def triage_in_background() -> bool:
    """Triage the active pack in a background thread (after a run from the web app), unless
    one is already running for this pack or triage is off. True if one was started."""
    if get_settings().watch_auto_investigate == "off":
        return False
    domain = current_domain()
    with _lock:
        if domain in _running:
            return False
        _running.add(domain)

    def work() -> None:
        try:
            with get_engine().connect() as conn:
                triage(conn)
        except Exception:
            log.exception("background triage failed")
        finally:
            with _lock:
                _running.discard(domain)

    ctx = copy_context()  # carries the active pack into the thread
    threading.Thread(target=ctx.run, args=(work,), daemon=True, name=f"triage-{domain}").start()
    return True
