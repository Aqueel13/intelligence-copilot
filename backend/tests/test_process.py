"""Process mining: exact against pandas, and the planted story is visible in the process."""

from datetime import date

import pandas as pd
import pytest
from fastapi.testclient import TestClient

from watchdog_backend.analytics.metrics import MetricQueryError, MetricsEngine
from watchdog_backend.analytics.process import ProcessAnalyzer, ProcessQuery


@pytest.fixture(scope="module")
def analyzer(pack) -> ProcessAnalyzer:
    return ProcessAnalyzer(MetricsEngine(pack))


@pytest.fixture(scope="module")
def conn(db_engine):
    with db_engine.connect() as c:
        yield c


@pytest.fixture(scope="module")
def pmap(analyzer, conn):
    return analyzer.process_map(conn, ProcessQuery())


@pytest.fixture(scope="module")
def acts(analyzer, conn):
    return analyzer.activities(conn, ProcessQuery())


@pytest.fixture(scope="module")
def pairs(dataset) -> pd.DataFrame:
    ev = dataset.events.sort_values(["case_id", "seq"])
    ev = ev.assign(target=ev.groupby("case_id")["activity"].shift(-1)).dropna(subset=["target"])
    return ev.groupby(["activity", "target"]).size().rename("n").reset_index()


# --- Process map -----------------------------------------------------------------------


def test_edges_match_pandas_directly_follows(pmap, pairs) -> None:
    ours = {(e.source, e.target): e.transitions for e in pmap.edges}
    theirs = {(r.activity, r.target): r.n for r in pairs.itertuples()}
    assert ours == theirs


def test_every_case_starts_at_fnol_and_ends_closed(pmap, dataset) -> None:
    assert pmap.cases == len(dataset.cases)
    assert pmap.start_activities == {"FNOL": len(dataset.cases)}
    assert pmap.end_activities == {"Closed": len(dataset.cases)}


def test_flow_is_conserved_at_every_inner_activity(pmap) -> None:
    inflow: dict[str, int] = {}
    outflow: dict[str, int] = {}
    for e in pmap.edges:
        outflow[e.source] = outflow.get(e.source, 0) + e.transitions
        inflow[e.target] = inflow.get(e.target, 0) + e.transitions
    for node in pmap.nodes:
        if node.activity not in ("FNOL", "Closed"):
            assert inflow[node.activity] == outflow[node.activity] == node.instances


def test_rework_and_document_loops_appear_as_edges(pmap) -> None:
    edges = {(e.source, e.target) for e in pmap.edges}
    assert ("QA", "Verification") in edges
    assert ("Request Additional Documents", "Document Check") in edges


# --- Variants --------------------------------------------------------------------------


def test_variant_counts_match_pandas(analyzer, conn, dataset) -> None:
    traces = (
        dataset.events.sort_values(["case_id", "seq"])
        .groupby("case_id")["activity"]
        .agg(tuple)
        .value_counts()
    )
    result = analyzer.variants(conn, ProcessQuery(), top=50)
    assert result.distinct_variants == len(traces)
    assert result.variants[0].cases == traces.iloc[0]
    assert tuple(result.variants[0].activities) == traces.index[0]
    assert sum(v.cases for v in result.variants) == min(traces.sum(), traces.head(50).sum())


def test_senior_approval_variants_breach_far_more(analyzer, conn) -> None:
    # Health claims since the ₹2L threshold (April 2026): no monsoon survey backlog to blur it.
    scope = ProcessQuery(filters={"line_of_business": ["health"]}, period_from=date(2026, 4, 1))
    variants = analyzer.variants(conn, scope, top=4).variants
    with_senior = [v for v in variants if "Senior Approval" in v.activities]
    without = [v for v in variants if "Senior Approval" not in v.activities]
    assert with_senior and without
    assert min(v.breach_rate for v in with_senior) > max(v.breach_rate for v in without)


# --- Activities and bottlenecks --------------------------------------------------------


def test_senior_approval_and_survey_are_the_bottlenecks(acts) -> None:
    flagged = {a.activity for a in acts.internal if a.is_bottleneck}
    assert flagged == {"Senior Approval", "Survey & Loss Assessment"}  # RC1, RC5
    assert acts.internal[0].activity == "Senior Approval"  # sorted by mean wait


def test_customer_time_is_reported_separately(acts) -> None:
    assert [a.activity for a in acts.customer_time] == ["Request Additional Documents"]
    assert "Request Additional Documents" not in {a.activity for a in acts.internal}
    assert not acts.customer_time[0].is_bottleneck


def test_internal_wait_shares_sum_to_one(acts) -> None:
    assert sum(a.share_of_internal_wait for a in acts.internal) == pytest.approx(1.0)


def test_breach_rates_with_and_without_are_consistent(acts, dataset) -> None:
    overall = (dataset.cases["closed_at"] > dataset.cases["sla_due_at"]).mean()
    senior = next(a for a in acts.internal if a.activity == "Senior Approval")
    n = len(dataset.cases)
    blended = (
        senior.breach_rate_with * senior.cases + senior.breach_rate_without * (n - senior.cases)
    ) / n
    assert blended == pytest.approx(overall)


def test_verification_repeat_rate_equals_rework_metric(acts, pack, db_engine) -> None:
    from watchdog_backend.analytics.metrics import MetricQuery

    with db_engine.connect() as c:
        rework = MetricsEngine(pack).run(c, MetricQuery(metric="rework_rate")).rows[0].value
    verification = next(a for a in acts.internal if a.activity == "Verification")
    assert verification.repeat_rate == pytest.approx(rework)


# --- Filters ---------------------------------------------------------------------------


def test_filters_select_whole_cases(analyzer, conn, dataset) -> None:
    broker = sum(a["channel"] == "broker" for a in dataset.cases["attributes"])
    result = analyzer.process_map(conn, ProcessQuery(filters={"channel": ["broker"]}))
    assert result.cases == broker
    assert result.end_activities == {"Closed": broker}


def test_activity_filters_are_rejected(analyzer, conn) -> None:
    with pytest.raises(MetricQueryError, match="Unknown filter dimension 'activity'"):
        analyzer.process_map(conn, ProcessQuery(filters={"activity": ["QA"]}))


# --- API -------------------------------------------------------------------------------


@pytest.fixture(scope="module")
def client(db_engine, client_as) -> TestClient:
    return client_as("guest")


@pytest.mark.parametrize(
    "path", ["/api/process/map", "/api/process/variants", "/api/process/activities"]
)
def test_process_endpoints(client, path) -> None:
    assert client.post(path, json={}).status_code == 200
    assert client.post(path, json={"filters": {"activity": ["QA"]}}).status_code == 422


def test_domain_endpoint_describes_filters_and_data_range(client, dataset) -> None:
    body = client.get("/api/domain").json()
    names = [f["name"] for f in body["filters"]]
    assert "channel" in names and "month" not in names
    assert body["cases"] == len(dataset.cases)
    assert body["data_from"] >= "2025-04-01" and body["data_to"] <= "2026-09-30"
