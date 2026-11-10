"""The investigation graph end to end with a scripted model (no LLM server needed).

The script plays the LLM's part, including its mistakes (calling a confounded effect
supported, inventing a number), so the code's safeguards are what is being tested.
"""

import json
from collections import defaultdict, deque
from typing import Any

import pytest
from fastapi.testclient import TestClient
from langchain_core.messages import AIMessage

from watchdog_backend.analytics.metrics import MetricsEngine
from watchdog_backend.investigation import llm
from watchdog_backend.investigation.graph import Deps, run
from watchdog_backend.investigation.scoring import score
from watchdog_backend.knowledge.models import get_reranker
from watchdog_backend.knowledge.service import get_retriever


class ScriptedModel:
    """Duck-types the bits of a chat model the graph uses."""

    def __init__(self, structured: dict[type, list[Any]], texts: list[str]) -> None:
        self.structured = defaultdict(deque, {k: deque(v) for k, v in structured.items()})
        self.texts = deque(texts)
        self.calls: list[str] = []

    def with_structured_output(self, schema, method=None):
        outer = self

        class Runnable:
            def invoke(self, messages):
                outer.calls.append(schema.__name__)
                queue = outer.structured[schema]
                if not queue:
                    raise ValueError(f"no scripted answer for {schema.__name__}")
                answer = queue[0] if len(queue) == 1 else queue.popleft()
                if isinstance(answer, Exception):
                    raise answer
                return answer

        return Runnable()

    def invoke(self, messages):
        self.calls.append("text")
        return AIMessage(self.texts.popleft() if len(self.texts) > 1 else self.texts[0])


PLAN = llm.PlanOut(
    hypotheses=[
        llm.HypothesisOut(
            statement="Health claims breach more because health processing is slower.",
            checks=[
                llm.CheckOut(
                    type="segment", dimension="line_of_business", value="health", outcome="breached"
                ),
                llm.CheckOut(type="policy", query="health claim adjudication time"),
            ],
        ),
        llm.HypothesisOut(
            statement="Team B rework drives breaches.",
            checks=[
                llm.CheckOut(type="segment", dimension="team", value="Team B", outcome="rework"),
                llm.CheckOut(type="segment", dimension="team", value="Team Z"),
            ],  # invalid
        ),
        llm.HypothesisOut(
            statement="Senior approval is slow.",
            checks=[
                llm.CheckOut(type="activity_wait", activity="Senior Approval"),
                llm.CheckOut(type="policy", query="senior approval turnaround"),
            ],
        ),
    ]
)
ALWAYS_SUPPORTED = llm.VerdictOut(verdict="supported", confidence="high", reasoning="Looks right.")
PICKS = llm.RecommendOut(
    selections=[
        llm.SelectionOut(
            action_id="delegate_mid_value_approvals",
            hypothesis_ids=["H3"],
            rationale="Cuts the approval queue.",
        ),
        llm.SelectionOut(
            action_id="retrain_team_b", hypothesis_ids=["H2", "H99"], rationale="Reduces rework."
        ),
        llm.SelectionOut(action_id="invent_a_robot", hypothesis_ids=["H1"], rationale="?"),
    ]
)
SUMMARY_BAD = "Breaches fell by 42% after hiring 7 robots."
SUMMARY_GOOD = "The SLA breach rate is 31.0% across 5000 claims."


def _model(planner=PLAN) -> ScriptedModel:
    return ScriptedModel(
        {
            llm.RouteOut: [llm.RouteOut(route="investigation")],
            llm.PlanOut: [planner],
            llm.VerdictOut: [ALWAYS_SUPPORTED],
            llm.RecommendOut: [PICKS],
        },
        [SUMMARY_BAD, SUMMARY_GOOD],
    )


def _run(db_engine, pack, model) -> dict:
    with db_engine.connect() as conn:
        deps = Deps(
            conn,
            MetricsEngine(pack),
            get_retriever(),
            get_reranker(),
            {"default": (model, "scripted:model")},
        )
        state: dict = {}
        for _, update in run(deps, "Why are claims breaching the SLA?"):
            state.update(update)
    return state


@pytest.fixture(scope="module")
def result(db_engine, pack, kb):
    return _run(db_engine, pack, _model())


def _h(result, needle: str):
    return next(h for h in result["hypotheses"] if needle in h.statement)


def test_confounded_hypothesis_is_overridden(result) -> None:
    health = _h(result, "Health claims")
    assert health.model_verdict == "supported" and health.verdict == "refuted"
    assert "amount_band" in health.override


def test_unconfounded_hypotheses_stay_supported(result) -> None:
    assert _h(result, "Team B").verdict == "supported"
    assert _h(result, "Senior approval").verdict == "supported"


def test_invalid_checks_are_dropped_and_recorded(result) -> None:
    team_b = _h(result, "Team B")
    assert any("Team Z" in e.summary for e in team_b.evidence if not e.ok)


def test_planner_gets_a_policy_check_added_when_missing(result) -> None:
    team_b = _h(result, "Team B")
    assert any(e.check.type == "policy" for e in team_b.evidence)


def test_coverage_rule_adds_strong_untested_signals(result) -> None:
    auto = [h for h in result["hypotheses"] if h.auto]
    targets = {s for h in auto for s in h.signal_ids}
    assert "seg:doc_requested:channel:broker" in targets  # RC2 was not in the plan
    assert "weekday:Fri" in targets  # nor was RC4
    assert not any("Pune" in s for s in targets)  # low-sample signals are never auto-added


def test_recommendations_only_use_catalogue_actions_and_known_hypotheses(result) -> None:
    recs = {r.action_id: r for r in result["recommendations"]}
    assert "invent_a_robot" not in recs
    assert recs["delegate_mid_value_approvals"].recommended
    assert recs["retrain_team_b"].hypothesis_ids == ["H2"]  # H99 dropped
    assert not recs["saturday_rota"].recommended
    assert not recs["saturday_rota"].cost_effective
    assert recs["delegate_mid_value_approvals"].policy[0].ref == "POL-002 §4.3"
    assert "Team Leads" in recs["delegate_mid_value_approvals"].policy[0].text


def test_summary_with_invented_numbers_is_rewritten(result) -> None:
    assert result["summary"] == SUMMARY_GOOD
    assert result["number_check"].ok
    synth = next(s for s in result["steps"] if s.node == "synthesize")
    assert "rewritten" in synth.note


def test_score_against_ground_truth(result) -> None:
    s = score(result["hypotheses"])
    assert s.found["RC1"] and s.found["RC3"]
    assert not s.decoys_accepted["DC1"]  # the override prevented accepting the decoy


def test_planner_failure_falls_back_to_signals(db_engine, pack, kb) -> None:
    model = _model(planner=ValueError("model returned garbage"))
    state = _run(db_engine, pack, model)
    assert state["hypotheses"] and all(h.auto for h in state["hypotheses"])
    plan_step = next(s for s in state["steps"] if s.node == "plan")
    assert "planner failed" in plan_step.note


def test_metric_route_uses_the_metrics_engine(db_engine, pack, kb) -> None:
    model = ScriptedModel(
        {
            llm.RouteOut: [llm.RouteOut(route="metric")],
            llm.MetricOut: [llm.MetricOut(metric="sla_breach_rate", group_by=["channel"])],
        },
        ["unused"],
    )
    state = _run(db_engine, pack, model)
    rows = {r["group"]["channel"]: r["value"] for r in state["metric_answer"]["rows"]}
    assert set(rows) == {"agent", "broker", "direct"}
    assert "hypotheses" not in state


# --- API: streaming and persistence ----------------------------------------------------


def test_stream_and_fetch_investigation(db_engine, kb, monkeypatch) -> None:
    from watchdog_backend.api import investigations as api
    from watchdog_backend.investigation import service
    from watchdog_backend.llm.gateway import ModelSpec
    from watchdog_backend.main import app

    model = _model()
    fake = lambda role: (model, ModelSpec("ollama", "scripted"))  # noqa: E731
    monkeypatch.setattr(service, "get_chat_model", fake)
    monkeypatch.setattr(api, "get_chat_model", fake)

    client = TestClient(app)
    body = client.post(
        "/api/investigations/stream",
        json={
            "question": "Why are broker claims breaching?",
            "scope": {"filters": {"channel": ["broker"]}},
        },
    ).text
    events = [
        (block.split("\n")[0][7:], json.loads(block.split("\n")[1][6:]))
        for block in body.strip().split("\n\n")
    ]
    names = [e for e, _ in events]
    assert names[0] == "start" and names[-1] == "done"
    assert [d["node"] for e, d in events if e == "step"][:3] == ["route", "scan", "plan"]

    inv_id = events[0][1]["id"]
    record = client.get(f"/api/investigations/{inv_id}").json()
    assert record["status"] == "completed"
    assert record["result"]["overview"]["cases"] < 5000  # the broker scope was applied
    assert any(r["investigation_id"] == inv_id for r in client.get("/api/investigations").json())


def test_invalid_scope_is_rejected_before_streaming(db_engine) -> None:
    from watchdog_backend.main import app

    r = TestClient(app).post(
        "/api/investigations/stream",
        json={"question": "Why?????", "scope": {"filters": {"activity": ["QA"]}}},
    )
    assert r.status_code == 422


def test_dangling_list_lead_in_is_removed() -> None:
    from watchdog_backend.investigation.graph import _tidy_reasoning

    text = "Breaches are 84% with it vs 14% without. The key points are as follows:"
    assert _tidy_reasoning(text) == "Breaches are 84% with it vs 14% without."
    assert _tidy_reasoning("Fine as is.") == "Fine as is."


# --- structured output: malformed model output is retried, real errors are not -------------


class _ProviderError(Exception):
    def __init__(self, status_code: int, message: str):
        self.status_code = status_code
        super().__init__(message)


class _MethodModel:
    """Fails with a given error for json_schema; answers correctly via function_calling."""

    def __init__(self, error: Exception):
        self.error = error
        self.methods: list[str] = []

    def with_structured_output(self, schema, method=None):
        outer = self

        class R:
            def invoke(self, messages):
                outer.methods.append(method)
                if method == "json_schema":
                    raise outer.error
                return schema(route="metric")

        return R()


def test_malformed_output_falls_back_to_tool_calling() -> None:
    model = _MethodModel(_ProviderError(400, "{'code': 'json_validate_failed'}"))
    out = llm.structured(model, llm.RouteOut, "s", "u")
    assert out.route == "metric"
    assert model.methods == ["json_schema", "json_schema", "function_calling"]


def test_evaluation_never_records_provider_account_ids() -> None:
    from watchdog_backend.evaluation.suites import _redact

    msg = "Rate limit reached for model `x` in organization `org_0123456789abcdefghijklmn`"
    assert "org_0123" not in _redact(msg) and "org_<redacted>" in _redact(msg)


def test_real_errors_are_not_retried() -> None:
    model = _MethodModel(_ProviderError(401, "Invalid API Key"))
    with pytest.raises(_ProviderError):
        llm.structured(model, llm.RouteOut, "s", "u")
    assert model.methods == ["json_schema"]


# --- upgrade rules: a timid model still surfaces strong, unconfounded causes ---------------


def _timid(verdict: str = "inconclusive") -> ScriptedModel:
    return ScriptedModel(
        {
            llm.RouteOut: [llm.RouteOut(route="investigation")],
            llm.PlanOut: [PLAN],
            llm.VerdictOut: [
                llm.VerdictOut(verdict=verdict, confidence="low", reasoning="Unsure.")
            ],
            llm.RecommendOut: [llm.RecommendOut(selections=[])],
        },
        [SUMMARY_GOOD],
    )


@pytest.fixture(scope="module")
def timid_result(db_engine, pack, kb):
    return _run(db_engine, pack, _timid())


def test_timid_model_still_finds_every_planted_cause(timid_result) -> None:
    s = score(timid_result["hypotheses"])
    assert all(s.found.values()), s.found
    assert not any(s.decoys_accepted.values())


def test_rule_a_upgrades_only_code_worded_hypotheses(timid_result) -> None:
    upgraded = [
        h
        for h in timid_result["hypotheses"]
        if h.model_verdict == "inconclusive"
        and h.verdict == "supported"
        and not h.statement.startswith("Evidence-confirmed")
    ]
    assert upgraded and all(h.auto for h in upgraded)
    planner = [h for h in timid_result["hypotheses"] if not h.auto]
    assert all(h.verdict == "inconclusive" for h in planner)  # the model's own words untouched


def test_rule_b_adds_separate_findings_never_the_decoy(timid_result) -> None:
    confirmed = [
        h for h in timid_result["hypotheses"] if h.statement.startswith("Evidence-confirmed")
    ]
    assert confirmed
    assert all(h.verdict == "supported" and h.override for h in confirmed)
    keys = {(e.check.type, getattr(e.check, "value", None)) for h in confirmed for e in h.evidence}
    assert ("segment", "health") not in keys  # confounded: never confirmed
    assert ("activity_wait", None) in keys or any(
        getattr(e.check, "activity", None) == "Senior Approval"
        for h in confirmed
        for e in h.evidence
    )


def test_refuting_model_cannot_suppress_strong_evidence(db_engine, pack, kb) -> None:
    s = score(_run(db_engine, pack, _timid("refuted"))["hypotheses"])
    assert s.found["RC1"] and s.found["RC3"]
    assert not s.decoys_accepted["DC1"]


def test_assessment_runs_in_parallel(db_engine, pack, kb, monkeypatch) -> None:
    import time as _time

    from watchdog_backend.config import get_settings

    monkeypatch.setattr(get_settings(), "llm_parallel_calls", 4)

    class Slow(ScriptedModel):
        def with_structured_output(self, schema, method=None):
            inner = super().with_structured_output(schema, method)
            if schema is not llm.VerdictOut:
                return inner

            class R:
                def invoke(self, messages):
                    _time.sleep(0.6)
                    return inner.invoke(messages)

            return R()

    model = Slow(
        {
            llm.RouteOut: [llm.RouteOut(route="investigation")],
            llm.PlanOut: [PLAN],
            llm.VerdictOut: [ALWAYS_SUPPORTED],
            llm.RecommendOut: [PICKS],
        },
        [SUMMARY_GOOD],
    )
    state = _run(db_engine, pack, model)
    assess = next(s for s in state["steps"] if s.node == "assess")
    n = sum(1 for h in state["hypotheses"] if not h.statement.startswith("Evidence-confirmed"))
    assert n >= 4
    assert assess.ms / 1000 < 0.6 * n * 0.6  # well under the sequential time


def _signal(id_, kind, strength, **data):
    from watchdog_backend.investigation.scan import Signal

    return Signal(id=id_, kind=kind, statement=id_, strength=strength, data=data)


def test_coverage_skips_trends_instead_of_stopping() -> None:
    from watchdog_backend.investigation.graph import apply_coverage

    signals = [
        _signal("trend:breach", "trend", 0.9),
        _signal(
            "seg:rework:team:Team B",
            "segment",
            0.5,
            dimension="team",
            value="Team B",
            outcome="rework",
            low_sample=False,
        ),
    ]
    hypotheses, added = apply_coverage([], signals)
    assert added == 1 and hypotheses[0].signal_ids == ["seg:rework:team:Team B"]


def test_coverage_never_adds_weak_or_small_sample_signals() -> None:
    from watchdog_backend.investigation.graph import apply_coverage

    signals = [
        _signal(
            "seg:breached:region:Pune",
            "segment",
            0.5,
            dimension="region",
            value="Pune",
            outcome="breached",
            low_sample=True,
        ),
        _signal(
            "seg:doc_requested:amount_band:> ₹5L",
            "segment",
            0.05,
            dimension="amount_band",
            value="> ₹5L",
            outcome="doc_requested",
            low_sample=False,
        ),
    ]
    assert apply_coverage([], signals) == ([], 0)
