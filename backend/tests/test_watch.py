"""Watch layer: monitor evaluation, alert lifecycle, follow-ups and the closed loop."""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import text

from watchdog_backend.analytics.metrics import MetricsEngine
from watchdog_backend.config import get_settings
from watchdog_backend.enterprise_mock.app import app as enterprise_app
from watchdog_backend.governance import service as gov
from watchdog_backend.governance.executor import http_executor
from watchdog_backend.watch.engine import Monitor, evaluate, get_monitors, run_monitors
from watchdog_backend.watch.followups import follow_ups
from watchdog_backend.watch.simulate import simulate_next_month

PERIOD = "2026-09"  # last month of the seed-42 dataset


@pytest.fixture(autouse=True)
def fresh_alerts(db_engine):
    """Alerts persist in the shared test database; each test starts without any."""
    with db_engine.begin() as c:
        c.execute(text("DELETE FROM intelligence.alerts"))


@pytest.fixture
def conn(db_engine):
    with db_engine.connect() as c:
        yield c


def _eval(conn, pack, monitor_id: str) -> dict:
    m = next(m for m in get_monitors() if m.id == monitor_id)
    return {e.segment: e for e in evaluate(conn, MetricsEngine(pack), m, PERIOD)}


# --- evaluation ----------------------------------------------------------------------


def test_monitors_flag_the_planted_problems(conn, pack) -> None:
    assert _eval(conn, pack, "sla_breach")[""].status == "critical"
    assert _eval(conn, pack, "senior_approval_wait")[""].status == "critical"  # RC1
    docs = _eval(conn, pack, "documents_requested")
    assert docs["channel=broker"].status == "critical"  # RC2
    assert docs["channel=direct"].status == "ok"
    rework = _eval(conn, pack, "verification_rework")
    assert rework["team=Team B"].status == "critical"  # RC3
    assert rework["team=Team A"].status == "ok"
    assert _eval(conn, pack, "friday_backlog")[""].status in ("warning", "critical")  # RC4


def test_alert_message_and_scope(conn, pack) -> None:
    e = _eval(conn, pack, "documents_requested")["channel=broker"]
    assert "broker" in e.message and "critical threshold" in e.message
    assert e.scope == {"channel": ["broker"]}  # what "Investigate" will scope to
    assert "broker" in e.question
    assert e.policy_ref == "SOP-101 §4"
    assert [p.period for p in e.series][-1] == PERIOD


def test_critical_needs_consecutive_months(conn, pack) -> None:
    base = next(m for m in get_monitors() if m.id == "senior_approval_wait")
    longer = base.model_copy(update={"critical_months": 99})  # more months than exist
    (e,) = evaluate(conn, MetricsEngine(pack), longer, PERIOD)
    assert e.status == "warning"  # bad, but not sustained long enough to be critical


def test_small_samples_never_alert(conn, pack) -> None:
    m = Monitor(
        id="t",
        title="t",
        metric="sla_breach_rate",
        direction="above",
        warning=0.0,
        critical=0.0,
        min_sample=10**6,
        question="q",
    )
    (e,) = evaluate(conn, MetricsEngine(pack), m, PERIOD)
    assert e.status == "insufficient_data"


def test_below_direction(conn, pack) -> None:
    m = Monitor(
        id="t",
        title="CSAT",
        metric="avg_csat",
        direction="below",
        warning=5.0,
        critical=1.0,
        min_sample=10,
        question="q",
    )
    (e,) = evaluate(conn, MetricsEngine(pack), m, PERIOD)
    assert e.status == "warning"  # any CSAT is below 5.0 but not below 1.0


# --- alert lifecycle -----------------------------------------------------------------


def test_runs_open_once_then_update(conn, db_engine, pack) -> None:
    first = run_monitors(conn, "manual")
    second = run_monitors(conn, "manual")
    assert second.opened == 0
    assert second.updated == first.opened + first.updated
    with db_engine.connect() as c:
        dupes = c.execute(
            text("""SELECT monitor_id, segment, count(*) FROM intelligence.alerts
                                   WHERE status <> 'resolved' GROUP BY 1, 2
                                   HAVING count(*) > 1""")
        ).all()
    assert dupes == []


# --- API -----------------------------------------------------------------------------


@pytest.fixture
def client(db_engine, kb) -> TestClient:
    from watchdog_backend.main import app

    return TestClient(app)


def test_watch_status_api(client) -> None:
    client.post("/api/watch/run")
    body = client.get("/api/watch").json()
    assert body["summary"]["period"] >= PERIOD
    assert any(a["monitor_id"] == "documents_requested" for a in body["alerts"])


def test_acknowledge_rules(client) -> None:
    client.post("/api/watch/run")
    open_alert = next(a for a in client.get("/api/watch").json()["alerts"] if a["status"] == "open")
    url = f"/api/watch/alerts/{open_alert['alert_id']}/acknowledge"
    assert client.post(url, json={"user_id": "mallory"}).status_code == 403
    r = client.post(url, json={"user_id": "s.iyer"})
    assert r.status_code == 200 and r.json()["acknowledged_by"] == "s.iyer"
    assert client.post(url, json={"user_id": "s.iyer"}).status_code == 409


# --- the closed loop: execute actions, a month passes, the Watch layer checks ----------


@pytest.fixture
def october(db_engine, pack, monkeypatch):
    """Execute delegation and Team B retraining, then simulate October. Cleans up after."""
    monkeypatch.setattr(get_settings(), "enterprise_api_key", "k")
    executor = http_executor(TestClient(enterprise_app))
    with db_engine.connect() as c:
        for action, approver in [
            ("delegate_mid_value_approvals", "a.rao"),
            ("retrain_team_b", "p.nair"),
        ]:
            req = gov.propose(c, gov.user_actor("m.khan"), action, "loop test")
            gov.decide(c, gov.user_actor(approver), req.request_id, "approved")
            gov.execute(c, gov.user_actor(approver), req.request_id, executor)
        month = simulate_next_month(c)
        yield c, month
    with db_engine.begin() as c:  # leave the shared test database as it was
        c.execute(text("DELETE FROM operational.cases WHERE opened_at >= '2026-10-01'"))
        c.execute(text("DELETE FROM intelligence.simulated_months"))


def test_closed_loop(october, pack) -> None:
    conn, month = october
    assert month.month == "2026-10"
    assert {"delegate_mid_value_approvals", "retrain_team_b"} <= set(month.applied_actions)

    engine = MetricsEngine(pack)
    rework = {
        e.segment: e
        for e in evaluate(
            conn,
            engine,
            next(m for m in get_monitors() if m.id == "verification_rework"),
            "2026-10",
        )
    }
    assert rework["team=Team B"].status == "ok"  # retraining worked
    docs = {
        e.segment: e
        for e in evaluate(
            conn,
            engine,
            next(m for m in get_monitors() if m.id == "documents_requested"),
            "2026-10",
        )
    }
    assert docs["channel=broker"].status == "critical"  # nothing was done about brokers

    verdicts = {f.action_id: f for f in follow_ups(conn)}
    assert verdicts["delegate_mid_value_approvals"].verdict == "on_target"
    assert verdicts["delegate_mid_value_approvals"].after < 24
    assert verdicts["retrain_team_b"].verdict == "on_target"


def test_follow_up_waits_for_data(db_engine) -> None:
    with db_engine.connect() as c:
        pending = [f for f in follow_ups(c) if f.effective_month is None]
    assert all(f.verdict == "awaiting_data" for f in pending)
