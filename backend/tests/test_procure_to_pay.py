"""The second domain pack (Procure-to-Pay) on the same engine.

What this proves: a new process is configuration plus a generator. The same scan, checks,
confounder controls, safeguards, what-if engine, monitors, governance and API serve it, side
by side with Insurance Claims, selected per request.
"""

import pandas as pd
import pytest

from watchdog_backend.analytics.metrics import MetricQuery, MetricsEngine
from watchdog_backend.analytics.process import ProcessAnalyzer, ProcessQuery
from watchdog_backend.domain.pack import (
    UnknownDomainError,
    available_domains,
    current_domain,
    get_pack,
    use_domain,
)
from watchdog_backend.generator.procure_to_pay import GeneratorConfig, ProcureToPayGenerator
from watchdog_backend.investigation import llm
from watchdog_backend.investigation.actions import evaluate_action, get_catalogue
from watchdog_backend.investigation.data import load_frames
from watchdog_backend.investigation.evidence import (
    ActivityWaitCheck,
    EvidenceContext,
    SegmentCheck,
    run_check,
    strong_support,
)
from watchdog_backend.investigation.graph import Deps, run
from watchdog_backend.investigation.scan import scan
from watchdog_backend.investigation.scoring import pack_ground_truth, score
from watchdog_backend.knowledge.models import get_reranker
from watchdog_backend.knowledge.service import get_retriever
from watchdog_backend.watch.engine import evaluate, get_monitors

from .test_investigation_graph import ScriptedModel

P2P = "procure_to_pay"
PERIOD = "2026-09"


@pytest.fixture(scope="module")
def p2p_ctx(p2p_db, p2p_pack):
    # Yield OUTSIDE use_domain: a module-scoped fixture must not leave the pack active.
    with p2p_db.connect() as conn:
        with use_domain(P2P):
            metrics = MetricsEngine(p2p_pack)
            frames = load_frames(conn, metrics, ProcessQuery())
            activities = ProcessAnalyzer(metrics).activities(conn, ProcessQuery())
        values = {
            d: sorted(map(str, frames.cases[d].dropna().unique()))
            for d in p2p_pack.analysis.dimensions
        }
        yield EvidenceContext(
            conn,
            frames,
            activities,
            get_retriever(),
            values,
            p2p_pack.analysis.wait_targets,
        )


# --- the pack and the active-pack mechanism ---------------------------------------------


def test_both_packs_are_available_default_first() -> None:
    assert available_domains()[:2] == ["insurance_claims", P2P]
    assert current_domain() == "insurance_claims"


def test_use_domain_switches_and_restores(p2p_pack) -> None:
    with use_domain(P2P):
        assert get_pack() is p2p_pack
        assert get_catalogue().actions.keys() >= {"restore_twice_weekly_runs"}
    assert get_pack().domain == "insurance_claims"
    with pytest.raises(UnknownDomainError), use_domain("no_such_pack"):
        pass


def test_pack_declares_its_analysis(p2p_pack) -> None:
    a = p2p_pack.analysis
    assert set(a.outcomes) == {"price_exception", "recapture", "grn_pending"}
    assert p2p_pack.outcome_labels["breached"] == "SLA breach rate"
    assert p2p_pack.feedback is None and p2p_pack.approval is None
    assert p2p_pack.case.labels == "invoices"


# --- generator ------------------------------------------------------------------------------


def test_generator_is_deterministic(p2p_pack) -> None:
    cfg = GeneratorConfig(n_invoices=200, seed=3)
    a = ProcureToPayGenerator(p2p_pack, cfg).generate()
    b = ProcureToPayGenerator(p2p_pack, cfg).generate()
    pd.testing.assert_frame_equal(a.events, b.events)


def test_every_invoice_starts_received_and_ends_paid(p2p_dataset) -> None:
    ev = p2p_dataset.events.sort_values(["case_id", "seq"])
    assert (ev.groupby("case_id")["activity"].first() == "Invoice Received").all()
    assert (ev.groupby("case_id")["activity"].last() == "Payment Released").all()


def test_every_planted_cause_drives_breaches(p2p_dataset) -> None:
    s = p2p_dataset.summary()
    for cause, v in s["root_causes"].items():
        # RC4 (weekly payment runs) covers only the last three of the 18 months
        assert v["share_of_breaches"] >= (0.05 if cause == "RC4" else 0.08), cause
    assert s["breach_rate_without_any_planted_cause"] < 0.12


def test_decoys_look_bad_but_vanish_within_their_confounder(p2p_dataset) -> None:
    d = p2p_dataset.summary()["decoys"]
    dc1, dc2 = d["DC1_services"], d["DC2_msme"]
    assert dc1["breach_rate"] > dc1["breach_rate_other_categories"] + 0.05
    for po_type, rate in dc1["breach_rate_by_po_type_services"].items():
        assert rate <= dc1["breach_rate_by_po_type_other"][po_type] + 0.02
    assert dc2["breach_rate"] > dc2["breach_rate_large"] + 0.04
    for team, rate in dc2["breach_rate_by_ap_team_msme"].items():
        assert rate <= dc2["breach_rate_by_ap_team_large"][team] + 0.03
    dc3 = d["DC3_sanand"]
    assert dc3["breach_rate"] > dc3["breach_rate_other_plants"] + 0.05
    assert dc3["paper_share"] > 0.5 > 0.2 > dc3["paper_share_other_plants"]
    for channel, rate in dc3["breach_rate_by_channel_sanand"].items():
        assert rate <= dc3["breach_rate_by_channel_other"][channel] + 0.03


def test_march_year_end_rush(p2p_dataset) -> None:
    by_month = p2p_dataset.summary()["seasonality"]["invoices_by_month"]
    others = [n for m, n in by_month.items() if not m.endswith("-03")]
    assert by_month["2026-03"] > 1.25 * (sum(others) / len(others))


def test_weekly_payment_run_starts_in_july(p2p_dataset) -> None:
    ev = p2p_dataset.events
    runs = ev[ev["activity"] == "Payment Run"]
    weekday = runs["started_at"].dt.day_of_week
    month = runs["started_at"].dt.strftime("%Y-%m")
    assert set(weekday[month == "2026-05"]) == {1, 4}  # Tuesday and Friday
    assert set(weekday[month == "2026-08"]) == {4}  # Fridays only (RC4)


# --- the same engine finds what was planted -----------------------------------------------


def test_scan_surfaces_every_planted_cause(p2p_ctx, p2p_pack) -> None:
    result = scan(p2p_ctx.frames, p2p_ctx.activities, p2p_pack.analysis.dimensions)
    ids = {s.id for s in result.signals}
    assert "seg:grn_pending:plant:Chakan" in ids  # RC1
    assert "seg:breached:plant:Chakan" in ids  # RC1
    assert "seg:price_exception:po_type:free_text" in ids  # RC2
    assert "seg:recapture:ap_team:BPO Partner" in ids  # RC3
    assert "bottleneck:Payment Run" in ids  # RC4: a queue that changed over time
    assert "seg:breached:invoice_channel:paper" in ids  # RC5
    assert "seg:breached:plant:Sanand" in ids  # DC3 shows up as a signal (explained below)


@pytest.mark.parametrize(
    "check",
    [
        # RC1: since paper invoices lengthened capture waits, the goods-receipt queue is no
        # longer 2× the median queue (not a "bottleneck"); Chakan's pending rate shows it.
        SegmentCheck(dimension="plant", value="Chakan", outcome="grn_pending"),
        SegmentCheck(dimension="plant", value="Chakan"),
        SegmentCheck(dimension="po_type", value="free_text", outcome="price_exception"),
        SegmentCheck(dimension="ap_team", value="BPO Partner", outcome="recapture"),
        ActivityWaitCheck(activity="Payment Run"),
        SegmentCheck(dimension="invoice_channel", value="paper"),
    ],
)
def test_planted_causes_meet_the_strict_support_rule(p2p_ctx, check) -> None:
    with use_domain(P2P):
        e = run_check(p2p_ctx, check)
        assert e.ok and strong_support(e), e.summary


@pytest.mark.parametrize(
    ("value", "confounder"),
    [
        (("category", "IT services"), "po_type"),  # DC1
        (("vendor_size", "MSME"), "ap_team"),  # DC2
        (("plant", "Sanand"), "invoice_channel"),  # DC3
    ],
)
def test_decoys_are_explained_by_their_confounder(p2p_ctx, value, confounder) -> None:
    with use_domain(P2P):
        e = run_check(p2p_ctx, SegmentCheck(dimension=value[0], value=value[1]))
        assert confounder in e.explained_by
        assert strong_support(e) is None


def test_payment_run_evidence_reports_the_monthly_change(p2p_ctx) -> None:
    with use_domain(P2P):
        e = run_check(p2p_ctx, ActivityWaitCheck(activity="Payment Run"))
    monthly = e.data["monthly"]
    waits = monthly["wait_by_month"]
    assert waits["2026-08"] > 1.3 * waits["2026-05"]
    assert monthly["r"] > 0.8 and "Mean wait by month" in e.summary


def test_unknown_outcome_is_reported_not_raised(p2p_ctx) -> None:
    with use_domain(P2P):
        e = run_check(p2p_ctx, SegmentCheck(dimension="plant", value="Chakan", outcome="rework"))
    assert not e.ok and "Unknown outcome" in e.summary


# --- what-if, monitors ------------------------------------------------------------------------


def test_whatif_estimates_track_the_counterfactual_truth(p2p_ctx, p2p_dataset) -> None:
    truth = p2p_dataset.summary()["root_causes"]
    with use_domain(P2P):
        cat = get_catalogue()
        for action_id, cause in [
            ("chakan_grn_discipline", "RC1"),
            ("enforce_catalogue_buying", "RC2"),
            ("retrain_bpo_capture", "RC3"),
            ("restore_twice_weekly_runs", "RC4"),
            ("enforce_e_invoicing", "RC5"),
        ]:
            est = evaluate_action(p2p_ctx.frames, cat.actions[action_id], cat.economics)
            actual = truth[cause]["breaches_attributable"]
            assert 0.3 * actual <= est.breaches_avoided <= 2.0 * actual, (action_id, est, actual)


def test_monitors_flag_the_planted_problems(p2p_db, p2p_pack) -> None:
    with use_domain(P2P), p2p_db.connect() as conn:
        engine = MetricsEngine(p2p_pack)

        def ev(monitor_id: str) -> dict:
            m = next(m for m in get_monitors() if m.id == monitor_id)
            return {e.segment: e for e in evaluate(conn, engine, m, PERIOD)}

        assert ev("invoice_to_pay_breach")[""].status == "critical"
        assert ev("payment_run_wait")[""].status == "critical"  # RC4
        assert ev("grn_wait")["plant=Chakan"].status == "critical"  # RC1
        assert ev("grn_wait")["plant=Hosur"].status in ("ok", "insufficient_data")
        assert ev("price_exceptions")["po_type=free_text"].status == "critical"  # RC2
        assert ev("price_exceptions")["po_type=contract"].status == "ok"
        assert ev("capture_rework")["ap_team=BPO Partner"].status == "critical"  # RC3


# --- the full graph: safeguards work on a pack they were not written for ---------------------


def _timid() -> ScriptedModel:
    return ScriptedModel(
        {
            llm.RouteOut: [llm.RouteOut(route="investigation")],
            llm.PlanOut: [
                llm.PlanOut(
                    hypotheses=[
                        llm.HypothesisOut(
                            statement="IT services invoices are slow because IT approvals lag.",
                            checks=[
                                llm.CheckOut(
                                    type="segment", dimension="category", value="IT services"
                                ),
                                llm.CheckOut(type="policy", query="IT services invoice approval"),
                            ],
                        ),
                        llm.HypothesisOut(
                            statement="MSME suppliers are paid late.",
                            checks=[
                                llm.CheckOut(type="segment", dimension="vendor_size", value="MSME"),
                                llm.CheckOut(type="policy", query="MSME payment terms"),
                            ],
                        ),
                        llm.HypothesisOut(
                            statement="Large invoices wait for the Finance Controller.",
                            checks=[
                                llm.CheckOut(
                                    type="activity_wait", activity="Finance Controller Approval"
                                ),
                                llm.CheckOut(type="policy", query="Finance Controller approval"),
                            ],
                        ),
                    ]
                )
            ],
            llm.VerdictOut: [
                llm.VerdictOut(verdict="inconclusive", confidence="low", reasoning="Unsure.")
            ],
            llm.RecommendOut: [llm.RecommendOut(selections=[])],
        },
        ["Invoices breach the target."],
    )


def test_timid_model_still_finds_every_planted_cause_and_no_decoy(p2p_db, p2p_pack) -> None:
    model = _timid()
    with use_domain(P2P), p2p_db.connect() as conn:
        deps = Deps(
            conn,
            MetricsEngine(p2p_pack),
            get_retriever(),
            get_reranker(),
            {"default": (model, "scripted:model")},
        )
        state: dict = {}
        for _, update in run(deps, "Why are invoices paid late?"):
            state.update(update)
        s = score(state["hypotheses"], pack_ground_truth())
    assert all(s.found.values()), s.found
    assert not any(s.decoys_accepted.values()), s.decoys_accepted
    # Regression: hypotheses are assessed in parallel threads, and the active pack must
    # follow them (upgrade reasons are worded with the pack's labels).
    reasons = " ".join(h.override or "" for h in state["hypotheses"])
    assert "invoices through it" in reasons and "claims through it" not in reasons
    assert {r.action_id for r in state["recommendations"]} == {
        "chakan_grn_discipline",
        "add_chakan_stores_clerk",
        "enforce_catalogue_buying",
        "retrain_bpo_capture",
        "restore_twice_weekly_runs",
        "enforce_e_invoicing",
        "scan_paper_invoices_at_plants",
    }  # the P2P catalogue, valued by the same what-if engine


# --- API: the pack is chosen per request ------------------------------------------------------


@pytest.fixture(scope="module")
def client(p2p_db, client_as):
    return client_as("admin")


def test_domains_endpoint_lists_both_packs(client) -> None:
    rows = {d["domain"]: d for d in client.get("/api/domains").json()}
    assert rows[P2P]["cases"] == 18000 and rows[P2P]["case_label_plural"] == "invoices"
    assert rows["insurance_claims"]["cases"] > 0


def test_header_selects_the_pack(client) -> None:
    default = client.get("/api/domain").json()
    p2p = client.get("/api/domain", headers={"X-Domain": P2P}).json()
    assert default["domain"] == "insurance_claims"
    assert p2p["domain"] == P2P and p2p["sla_start"] == "Invoice Received"
    assert p2p["senior_threshold"] is None and p2p["investigate_examples"]


def test_metrics_are_isolated_per_pack(client) -> None:
    body = MetricQuery(metric="case_count").model_dump(mode="json")
    p2p = client.post("/api/metrics/query", json=body, headers={"X-Domain": P2P}).json()
    assert p2p["rows"][0]["value"] == 18000
    wrong = MetricQuery(metric="price_exception_rate").model_dump(mode="json")
    # not an insurance metric: the default pack rejects it
    assert client.post("/api/metrics/query", json=wrong).status_code == 422


def test_unknown_pack_is_a_400(client) -> None:
    r = client.get("/api/domain", headers={"X-Domain": "nope"})
    assert r.status_code == 400 and "Available" in r.json()["detail"]


def test_governance_is_per_pack(client) -> None:
    roles = client.get("/api/auth/roles").json()["business_roles"]
    assert "Treasury Head" in roles[P2P] and "Head of Claims" not in roles[P2P]
    assert "Head of Claims" in roles["insurance_claims"]


def test_restoring_the_payment_run_is_valued_at_its_current_rate(p2p_ctx) -> None:
    """The weekly runs began in July 2026 (3 of 18 months): averaged over the window, their
    remedy looked not cost-effective; at the current run-rate it pays."""
    with use_domain(P2P):
        cat = get_catalogue()
        i = evaluate_action(p2p_ctx.frames, cat.actions["restore_twice_weekly_runs"], cat.economics)
    assert "2026-07" in i.annual_basis and i.annual_net_inr > 0
