"""Deterministic parts of the investigation: statistics, scan, what-if engine, number checks."""

import json

import numpy as np
import pandas as pd
import pytest

from watchdog_backend.analytics.metrics import MetricsEngine
from watchdog_backend.analytics.process import ProcessAnalyzer, ProcessQuery
from watchdog_backend.investigation.actions import evaluate_action, get_catalogue
from watchdog_backend.investigation.data import load_frames
from watchdog_backend.investigation.scan import scan
from watchdog_backend.investigation.stats import compare_proportions, stratified_difference
from watchdog_backend.investigation.verify import verify_numbers

DIMS = ["line_of_business", "channel", "region", "team", "amount_band"]


@pytest.fixture(scope="module")
def frames(db_engine, pack):
    with db_engine.connect() as c:
        return load_frames(c, MetricsEngine(pack), ProcessQuery())


@pytest.fixture(scope="module")
def activities(db_engine, pack):
    with db_engine.connect() as c:
        return ProcessAnalyzer(MetricsEngine(pack)).activities(c, ProcessQuery())


@pytest.fixture(scope="module")
def since_april(db_engine, pack):
    """Since POL-002 v2 (April 2026): the period where health looks slower (DC1)."""
    from datetime import date

    with db_engine.connect() as c:
        return load_frames(c, MetricsEngine(pack), ProcessQuery(period_from=date(2026, 4, 1)))


@pytest.fixture(scope="module")
def truth(dataset):
    return json.loads(json.dumps(dataset.summary(), default=str))


# --- statistics ----------------------------------------------------------------------


def test_proportion_test_detects_a_real_difference() -> None:
    y = pd.Series([1] * 60 + [0] * 40 + [1] * 30 + [0] * 70, dtype=float)
    mask = pd.Series([True] * 100 + [False] * 100)
    r = compare_proportions(mask, y, "x")
    assert r.rate_in == 0.6 and r.rate_out == 0.3
    assert r.significant and r.p_value < 0.001


def test_stratification_exposes_a_confounder() -> None:
    # Outcome depends only on `big`; segment A is mostly big. Raw A effect is spurious.
    rng = np.random.default_rng(0)
    n = 4000
    seg = rng.random(n) < 0.5
    big = np.where(seg, rng.random(n) < 0.8, rng.random(n) < 0.2)
    y = (rng.random(n) < np.where(big, 0.7, 0.2)).astype(float)
    df = pd.DataFrame({"seg": seg, "big": big, "y": y})
    r = stratified_difference(df, df["seg"], "y", "big", "seg")
    assert r.raw_difference > 0.2
    assert abs(r.adjusted_difference) < 0.05
    assert r.explained_by_control


# --- scan ----------------------------------------------------------------------------


def test_scan_finds_every_planted_pattern(frames, activities) -> None:
    ids = {s.id for s in scan(frames, activities, DIMS).signals}
    assert "bottleneck:Senior Approval" in ids  # RC1
    assert "seg:doc_requested:channel:broker" in ids  # RC2
    assert "seg:rework:team:Team B" in ids  # RC3
    assert "weekday:Fri" in ids  # RC4
    assert "bottleneck:Survey & Loss Assessment" in ids  # RC5
    assert "seg:rework:region:Kolkata" in ids  # DC4 shows up as a signal…


def test_kolkata_signal_is_explained_by_team(frames) -> None:
    # …and controlling for team rules it out.
    df = frames.cases.assign(y=frames.cases["rework"].astype(float))
    r = stratified_difference(df, df["region"] == "Kolkata", "y", "team", "k")
    assert r.raw_difference > 0.03 and r.explained_by_control


def test_dc1_health_signal_since_the_threshold_change(since_april, activities) -> None:
    ids = {s.id for s in scan(since_april, activities, DIMS).signals}
    assert "seg:breached:line_of_business:health" in ids  # DC1 shows up as a signal…


def test_scan_reports_only_the_adverse_side(frames, activities) -> None:
    ids = {s.id for s in scan(frames, activities, DIMS).signals}
    assert "seg:breached:line_of_business:motor" not in ids


def test_health_signal_is_explained_by_amount(since_april) -> None:
    # …and the confounder check is what lets the agent rule DC1 out.
    df = since_april.cases.assign(y=since_april.cases["breached"].astype(float))
    r = stratified_difference(df, df["line_of_business"] == "health", "y", "amount_band", "h")
    assert r.explained_by_control


# --- what-if engine vs the generator's exact counterfactuals ---------------------------


@pytest.mark.parametrize(
    ("action", "truth_key", "low", "high"),
    [
        ("delegate_mid_value_approvals", ("delegation_scenario", "breaches_avoided"), 0.7, 1.1),
        ("add_senior_adjuster_capacity", ("root_causes", "RC1", "breaches_attributable"), 0.7, 1.1),
        ("enforce_broker_checklist", ("root_causes", "RC2", "breaches_attributable"), 0.6, 1.3),
        ("retrain_team_b", ("root_causes", "RC3", "breaches_attributable"), 0.6, 1.4),
        ("saturday_rota", ("root_causes", "RC4", "breaches_attributable"), 0.3, 1.2),
        (
            "activate_monsoon_survey_panel",
            ("root_causes", "RC5", "breaches_attributable"),
            0.5,
            1.3,
        ),
    ],
)
def test_what_if_tracks_ground_truth(frames, truth, action, truth_key, low, high) -> None:
    cat = get_catalogue()
    estimate = evaluate_action(frames, cat.actions[action], cat.economics).breaches_avoided
    actual = truth
    for k in truth_key:
        actual = actual[k]
    assert low * actual <= estimate <= high * actual, (action, estimate, actual)


def test_saturday_rota_is_not_cost_effective(frames) -> None:
    cat = get_catalogue()
    assert evaluate_action(frames, cat.actions["saturday_rota"], cat.economics).annual_net_inr < 0
    best = evaluate_action(frames, cat.actions["delegate_mid_value_approvals"], cat.economics)
    assert best.annual_net_inr > 0


# --- number verification -------------------------------------------------------------

FACTS = "Breach rate 31.0% (1,548 breaches); avoids 426 in the period (852 a year); ₹12.3 lakh."


def test_numbers_from_the_facts_are_verified() -> None:
    assert verify_numbers("Breach rate is 31.0%, 1,548 breaches; 852 a year; ₹12.3 lakh.", FACTS).ok


def test_invented_numbers_and_wrong_units_are_flagged() -> None:
    check = verify_numbers("Hiring 20% more staff saves ₹12.3 crore and 220 claims.", FACTS)
    assert set(check.unverified) == {"20%", "₹12.3 crore", "220"}


# --- scoped investigations compare the scope with the rest of the business ------------


def test_scoped_segment_check_uses_the_population(db_engine, pack, activities) -> None:
    from watchdog_backend.investigation.evidence import EvidenceContext, SegmentCheck, run_check
    from watchdog_backend.knowledge.service import get_retriever

    engine = MetricsEngine(pack)
    scope = ProcessQuery(filters={"channel": ["broker"]})
    with db_engine.connect() as c:
        scoped = load_frames(c, engine, scope)
        population = load_frames(c, engine, ProcessQuery())
        ctx = EvidenceContext(
            c,
            scoped,
            activities,
            get_retriever(),
            {"channel": ["broker"]},
            {},
            population=population,
        )
        alone = EvidenceContext(c, scoped, activities, get_retriever(), {"channel": ["broker"]}, {})
        check = SegmentCheck(dimension="channel", value="broker", outcome="doc_requested")
        with_population = run_check(ctx, check)
        without = run_check(alone, check)
    assert "outside this scope" in with_population.summary
    assert with_population.data["significant"] and with_population.data["difference"] > 0.1
    assert not without.data["significant"]  # inside the scope there is nothing to compare with


def test_scoped_what_if_uses_the_population_baseline(db_engine, pack) -> None:
    engine = MetricsEngine(pack)
    with db_engine.connect() as c:
        broker = load_frames(c, engine, ProcessQuery(filters={"channel": ["broker"]}))
        population = load_frames(c, engine, ProcessQuery())
    cat = get_catalogue()
    action = cat.actions["enforce_broker_checklist"]
    alone = evaluate_action(broker, action, cat.economics)
    scoped = evaluate_action(broker, action, cat.economics, population)
    full = evaluate_action(population, action, cat.economics)
    assert alone.breaches_avoided == 0  # no baseline inside the scope: unknown, not guessed
    assert scoped.breaches_avoided == pytest.approx(full.breaches_avoided, rel=0.01)


# --- many comparisons: chance patterns are not causes ---------------------------------------


def test_family_threshold_scales_with_the_number_of_comparisons() -> None:
    from watchdog_backend.investigation.stats import family_alpha

    assert family_alpha(1) == 0.01 and family_alpha(50) == pytest.approx(0.0002)


@pytest.mark.parametrize("seed", [7, 1234])
def test_pune_by_chance_is_not_a_cause(pack, seed) -> None:
    """In these seeds Pune breaches ~10 points more: partly its broker mix (RC2), the rest
    chance (12 other seeds average -2 points once channel is held equal). Raw it can pass a
    single 1% test; across the scan's comparisons, with channel controlled, it does not."""
    from watchdog_backend.generator.registry import generate
    from watchdog_backend.investigation.stats import family_alpha

    t = generate(pack, seed=seed).joined_truth()
    y = t["breached"].astype(float)
    pune = t["region"] == "Pune"
    alpha = family_alpha(57)  # 3 outcomes × 19 values of the 5 scanned dimensions
    assert compare_proportions(pune, y, "p").significant  # a naive test is fooled
    r = stratified_difference(t.assign(y=y), pune, "y", "channel", "p", alpha=alpha)
    assert r.explained_by_control and "may be chance" in r.note


def test_a_real_cause_survives_the_stricter_tests(frames) -> None:
    from watchdog_backend.investigation.scan import segment_alpha

    df = frames.cases.assign(y=frames.cases["doc_requested"].astype(float))
    broker = df["channel"] == "broker"
    alpha = segment_alpha(frames)
    assert compare_proportions(broker, df["y"], "b", alpha=alpha).significant
    for control in ("amount_band", "line_of_business", "team"):
        assert not stratified_difference(
            df, broker, "y", control, "b", alpha=alpha
        ).explained_by_control
