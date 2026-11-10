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
