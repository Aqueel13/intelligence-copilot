"""Metrics engine: exact against an independent pandas computation, and it recovers the
planted causes. Requires the test database (see conftest)."""

import pandas as pd
import pytest

from watchdog_backend.analytics.metrics import MetricQuery, MetricQueryError, MetricsEngine


@pytest.fixture(scope="module")
def engine(pack) -> MetricsEngine:
    return MetricsEngine(pack)


@pytest.fixture(scope="module")
def run(engine, db_engine):
    def _run(**kwargs):
        with db_engine.connect() as conn:
            return engine.run(conn, MetricQuery(**kwargs))

    return _run


def by(result, dim: str) -> dict[str, float]:
    return {r.group[dim]: r.value for r in result.rows}


@pytest.fixture(scope="module")
def frame(dataset) -> pd.DataFrame:
    """Case-level frame computed independently in pandas."""
    cases = dataset.cases.copy()
    attrs = pd.json_normalize(cases.pop("attributes").tolist())
    cases = pd.concat([cases, attrs], axis=1)
    cases["cycle_hours"] = (cases["closed_at"] - cases["opened_at"]).dt.total_seconds() / 3600
    cases["breached"] = cases["closed_at"] > cases["sla_due_at"]
    counts = dataset.events.groupby(["case_id", "activity"]).size().unstack(fill_value=0)
    return cases.join(counts, on="case_id")


# --- Exactness: SQL == pandas --------------------------------------------------------


def test_breach_rate_matches_pandas(run, frame) -> None:
    assert run(metric="sla_breach_rate").rows[0].value == pytest.approx(frame["breached"].mean())


def test_cycle_days_by_team_matches_pandas(run, frame) -> None:
    expected = (frame.groupby("team")["cycle_hours"].mean() / 24).to_dict()
    assert by(run(metric="avg_cycle_days", group_by=["team"]), "team") == pytest.approx(expected)


def test_rework_rate_by_team_matches_pandas(run, frame) -> None:
    expected = frame.groupby("team")["Verification"].apply(lambda s: (s > 1).mean()).to_dict()
    assert by(run(metric="rework_rate", group_by=["team"]), "team") == pytest.approx(expected)


def test_senior_approval_wait_matches_pandas(run, dataset) -> None:
    ev = dataset.events.sort_values(["case_id", "seq"]).copy()
    ev["handoff"] = ev.groupby("case_id")["ended_at"].shift()
    ev["wait"] = (ev["started_at"] - ev["handoff"]).dt.total_seconds().fillna(0) / 3600
    expected = ev.loc[ev["activity"] == "Senior Approval", "wait"].mean()
    result = run(metric="avg_wait_hours", filters={"activity": ["Senior Approval"]})
    assert result.rows[0].value == pytest.approx(expected)


def test_filters_and_period_match_pandas(run, frame) -> None:
    sub = frame[
        (frame["channel"] == "broker")
        & (
            frame["opened_at"].dt.tz_convert("Asia/Kolkata").dt.date
            >= pd.Timestamp("2026-06-01").date()
        )
    ]
    result = run(metric="case_count", filters={"channel": ["broker"]}, period_from="2026-06-01")
    assert result.rows[0].value == len(sub)


def test_csat_sample_counts_respondents_only(run, dataset) -> None:
    result = run(metric="avg_csat")
    assert result.rows[0].n == dataset.public_feedback()["responded_at"].notna().sum()


# --- Planted causes are recoverable through the metrics alone ------------------------


def test_rc1_senior_approval_is_the_longest_wait(run) -> None:
    waits = by(run(metric="avg_wait_hours", group_by=["activity"]), "activity")
    assert max(waits, key=lambda k: waits[k]) == "Senior Approval"
    assert waits["Senior Approval"] > 24  # breaches the 24h policy


def test_rc2_broker_doc_requests(run) -> None:
    rates = by(run(metric="doc_request_rate", group_by=["channel"]), "channel")
    assert rates["broker"] > 2.5 * max(rates["direct"], rates["agent"])


def test_rc3_team_b_rework(run) -> None:
    rates = by(run(metric="rework_rate", group_by=["team"]), "team")
    assert rates["Team B"] > 2.5 * max(rates["Team A"], rates["Team C"])


def test_rc4_friday_handoffs_wait_longer(run) -> None:
    waits = by(
        run(
            metric="avg_wait_hours",
            group_by=["handoff_weekday"],
            filters={"activity": ["Verification", "QA", "Settlement"]},
        ),
        "handoff_weekday",
    )
    assert waits["Fri"] > 2 * max(waits[d] for d in ("Mon", "Tue", "Wed", "Thu"))


def test_dc2_pune_flagged_as_low_sample_within_a_month(run) -> None:
    # Pune is tiny: about 15 claims a month, too few to judge a monthly rate on.
    rows = {
        r.group["region"]: r
        for r in run(
            metric="sla_breach_rate",
            group_by=["region"],
            period_from="2026-09-01",
            period_to="2026-09-30",
        ).rows
    }
    assert rows["Pune"].low_sample
    assert not rows["Mumbai"].low_sample


def test_groups_follow_natural_order(run) -> None:
    result = run(metric="case_count", group_by=["amount_band"])
    assert [r.group["amount_band"] for r in result.rows] == [
        "< ₹50K",
        "₹50K–₹2L",
        "₹2L–₹5L",
        "> ₹5L",
    ]


# --- Safety and validation -----------------------------------------------------------


@pytest.mark.parametrize(
    ("query", "message"),
    [
        ({"metric": "drop_tables"}, "Unknown metric"),
        ({"metric": "case_count", "group_by": ["password"]}, "Unknown group_by dimension"),
        ({"metric": "case_count", "group_by": ["activity"]}, "Unknown group_by dimension"),
        ({"metric": "case_count", "filters": {"channel": ["telepathy"]}}, "Unknown value"),
        ({"metric": "case_count", "filters": {"channel": []}}, "at least one value"),
        ({"metric": "case_count", "filters": {"month": ["2026-13"]}}, "Invalid value"),
        ({"metric": "case_count", "period_from": "2026-09-01", "period_to": "2026-04-01"}, "after"),
    ],
)
def test_invalid_queries_are_rejected_with_guidance(engine, query, message) -> None:
    with pytest.raises(MetricQueryError, match=message):
        engine.build(MetricQuery(**query))


def test_filter_values_are_bound_not_interpolated(engine) -> None:
    sql, params = engine.build(
        MetricQuery(metric="event_count", filters={"resource": ["x' OR '1'='1"]})
    )
    assert "OR '1'='1" not in sql
    assert ["x' OR '1'='1"] in params.values()


def test_injection_attempt_returns_no_rows(run) -> None:
    result = run(metric="event_count", filters={"resource": ["x' OR '1'='1"]})
    assert result.rows[0].value == 0
