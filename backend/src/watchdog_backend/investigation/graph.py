"""The investigation graph (LangGraph).

    route ─┬─ metric ─────────────────────────────────────────────▶ END
           ├─ policy ─────────────────────────────────────────────▶ END
           └─ scan ─▶ plan ─▶ gather ─▶ assess ─▶ recommend ─▶ synthesize ─▶ END

Code does every computation (scan, checks, confounders, what-if, ROI, number checks).
The LLM routes, writes hypotheses, judges evidence, picks catalogue actions and writes prose.
Rule overrides keep the LLM honest: a segment effect explained by a confounder cannot be
"supported", whatever the model says.
"""

import time
from collections.abc import Callable, Iterator
from dataclasses import dataclass
from typing import Any, TypedDict

from langchain_core.language_models import BaseChatModel
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field, TypeAdapter, ValidationError
from sqlalchemy import Connection

from watchdog_backend.analytics.metrics import MetricQuery, MetricQueryError, MetricsEngine
from watchdog_backend.analytics.process import ProcessAnalyzer, ProcessQuery
from watchdog_backend.investigation import llm
from watchdog_backend.investigation.actions import (
    ActionImpact,
    evaluate_action,
    get_catalogue,
)
from watchdog_backend.investigation.data import load_frames
from watchdog_backend.investigation.evidence import (
    ActivityWaitCheck,
    Check,
    EvidenceContext,
    EvidenceItem,
    PolicyCheck,
    SegmentCheck,
    WeekdayCheck,
    describe_check,
    run_check,
)
from watchdog_backend.investigation.policy_refs import PolicyClause, resolve
from watchdog_backend.investigation.scan import Overview, Signal, scan, segment_signals
from watchdog_backend.investigation.verify import NumberCheck, verify_numbers
from watchdog_backend.knowledge.answer import Answer, answer_question
from watchdog_backend.knowledge.models import Reranker
from watchdog_backend.knowledge.retrieval import Retriever

DIMENSIONS = ["line_of_business", "channel", "region", "team", "amount_band"]
MAX_SIGNALS_FOR_PLANNER = 12
MAX_HYPOTHESES = 7
COVERAGE_MIN_STRENGTH = 0.08  # only strong signals are auto-added if the planner skips them
_CHECK = TypeAdapter(Check)


# ------------------------------------------------------------------------------ models


class Hypothesis(BaseModel):
    id: str
    statement: str
    auto: bool = False  # added by the coverage rule, not proposed by the planner
    signal_ids: list[str] = Field(default_factory=list)
    checks: list[Check] = Field(default_factory=list)
    dropped_checks: list[str] = Field(default_factory=list)
    evidence: list[EvidenceItem] = Field(default_factory=list)
    verdict: str | None = None  # supported | refuted | inconclusive
    confidence: str | None = None
    reasoning: str | None = None
    model_verdict: str | None = None  # what the LLM said, if a rule overrode it
    override: str | None = None


class Recommendation(BaseModel):
    action_id: str
    title: str
    description: str
    effort: str
    hypothesis_ids: list[str]
    rationale: str
    impact: ActionImpact
    policy: list[PolicyClause]
    recommended: bool  # chosen for a supported root cause (vs. evaluated for comparison)
    cost_effective: bool  # estimated annual net value > 0 under the stated assumptions


class Step(BaseModel):
    node: str
    ms: float
    model: str | None = None
    note: str | None = None


class InvestigationState(TypedDict, total=False):
    question: str
    scope: dict[str, Any]
    route: str
    overview: Overview
    signals: list[Signal]
    hypotheses: list[Hypothesis]
    recommendations: list[Recommendation]
    summary: str
    number_check: NumberCheck
    answer: Answer | None
    metric_answer: dict[str, Any] | None
    steps: list[Step]


@dataclass
class Deps:
    conn: Connection
    metrics: MetricsEngine
    retriever: Retriever
    reranker: Reranker
    models: dict[str, tuple[BaseChatModel, str]]  # role -> (model, model id)

    def model(self, role: str) -> tuple[BaseChatModel, str]:
        return self.models.get(role) or self.models["default"]


# --------------------------------------------------------------------------- helpers


def _timed(name: str, deps: Deps, role: str | None, fn: Callable[[InvestigationState], dict]):
    def node(state: InvestigationState) -> dict:
        started = time.perf_counter()
        update = fn(state)
        step = Step(
            node=name,
            ms=(time.perf_counter() - started) * 1000,
            model=deps.model(role)[1] if role else None,
            note=update.pop("_note", None),
        )
        return {**update, "steps": [*state.get("steps", []), step]}

    return node


def _scope(state: InvestigationState) -> ProcessQuery:
    return ProcessQuery.model_validate(state.get("scope") or {})


def _to_check(c: llm.CheckOut) -> Check:
    data = {k: v for k, v in c.model_dump().items() if v is not None}
    if c.type == "segment":
        data.setdefault("outcome", "breached")
    return _CHECK.validate_python(data)


def _tidy_reasoning(text: str) -> str:
    """Small models often end with "…the key points are:" and then nothing. Drop that tail."""
    text = text.strip()
    while text.endswith(":"):
        cut = max(text.rfind(". ", 0, len(text) - 1), text.rfind("\n", 0, len(text) - 1))
        if cut <= 0:
            break
        text = text[: cut + 1].strip()
    return text


def _covers(h: Hypothesis, s: Signal) -> bool:
    d = s.data
    for c in h.checks:
        same_segment = (
            s.kind == "segment"
            and isinstance(c, SegmentCheck)
            and (c.dimension, c.value, c.outcome) == (d["dimension"], d["value"], d["outcome"])
        )
        if same_segment:
            return True
        if s.kind == "bottleneck" and getattr(c, "activity", None) == d.get("activity"):
            return True
        if s.kind == "weekday" and getattr(c, "weekday", None) == d.get("weekday"):
            return True
    return False


def _signal_checks(s: Signal) -> list[Check]:
    d = s.data
    if s.kind == "segment":
        check: Check = SegmentCheck(
            dimension=d["dimension"], value=d["value"], outcome=d["outcome"]
        )
    elif s.kind == "bottleneck":
        check = ActivityWaitCheck(activity=d["activity"])
    else:
        check = WeekdayCheck(weekday=d["weekday"])
    return [check, PolicyCheck(query=s.statement[:200])]


def _facts(state: InvestigationState) -> str:
    o = state["overview"]
    lines = [
        f"Scope: {o.cases} claims over {o.months:.0f} months; SLA breach rate {o.breach_rate:.1%} "
        f"({o.breaches} breaches); average cycle time {o.mean_cycle_days:.1f} days vs a "
        f"{o.sla_days:.0f}-day SLA."
    ]
    for h in state.get("hypotheses", []):
        key = next((e.summary for e in h.evidence if e.ok and not e.policy), "")
        lines.append(f"{h.id} [{h.verdict}] {h.statement} Evidence: {key[:500]}")
        if h.override:
            lines.append(f"  (Rule override: {h.override})")
    for r in state.get("recommendations", []):
        if r.recommended:
            i = r.impact
            net_l = i.annual_net_inr / 1e5
            lines.append(
                f"Action '{r.title}': would avoid about {i.breaches_avoided:.0f} breaches in the "
                f"{o.months:.0f} months analysed (about {i.annual_breaches_avoided:.0f} a year); "
                f"breach rate {i.breach_rate_now:.1%} → {i.breach_rate_after:.1%}; estimated net "
                f"value ₹{net_l:.1f} lakh a year (₹{net_l / 10:.2f} million) under illustrative "
                f"cost assumptions."
            )
    return "\n".join(lines)


# ----------------------------------------------------------------------------- graph


def build_graph(deps: Deps):
    pack = deps.metrics.pack
    analyzer = ProcessAnalyzer(deps.metrics)
    catalogue = get_catalogue()
    targets = {"Senior Approval": pack.approval.senior_target_hours}
    cache: dict[str, Any] = {}

    def frames_and_activities(state: InvestigationState):
        if "frames" not in cache:
            scope = _scope(state)
            cache["frames"] = load_frames(deps.conn, deps.metrics, scope)
            cache["activities"] = analyzer.activities(deps.conn, scope)
            # A scoped question ("why are BROKER claims…") needs the rest of the business as
            # its comparison group; the same period, without the dimension filters.
            cache["population"] = (
                load_frames(
                    deps.conn,
                    deps.metrics,
                    ProcessQuery(period_from=scope.period_from, period_to=scope.period_to),
                )
                if scope.filters
                else None
            )
        return cache["frames"], cache["activities"]

    # -- route -------------------------------------------------------------------------
    def route(state: InvestigationState) -> dict:
        model, _ = deps.model("router")
        try:
            out = llm.structured(model, llm.RouteOut, llm.ROUTER_SYSTEM, state["question"])
            return {"route": out.route}
        except ValueError:
            return {"route": "investigation", "_note": "router failed; defaulted to investigation"}

    # -- simple routes -----------------------------------------------------------------
    def metric(state: InvestigationState) -> dict:
        model, _ = deps.model("router")
        catalogue_text = "\n".join(
            f"- {m.name}: {m.description}" for m in deps.metrics.pack.metrics.values()
        )
        dims = ", ".join(d.name for d in deps.metrics.dimensions.values())
        prompt = (
            f"Question: {state['question']}\n\nMetrics:\n{catalogue_text}\n\n"
            f"Dimensions for group_by/filters: {dims}\nPick one metric and at most 2 group_by."
        )
        try:
            out = llm.structured(model, llm.MetricOut, "Choose the metric query.", prompt)
            scope = _scope(state)
            q = MetricQuery(
                metric=out.metric,
                group_by=out.group_by[:2],
                filters={**scope.filters, **out.filters},
                period_from=scope.period_from,
                period_to=scope.period_to,
            )
            result = deps.metrics.run(deps.conn, q)
            return {"metric_answer": result.model_dump(mode="json")}
        except (ValueError, MetricQueryError) as exc:
            return {"metric_answer": {"error": str(exc)}}

    def policy(state: InvestigationState) -> dict:
        model, model_id = deps.model("answer")
        return {
            "answer": answer_question(
                deps.conn, deps.retriever, model, model_id, state["question"], deps.reranker
            )
        }

    # -- investigation -----------------------------------------------------------------
    def scan_node(state: InvestigationState) -> dict:
        frames, activities = frames_and_activities(state)
        result = scan(frames, activities, DIMENSIONS)
        signals = list(result.signals)
        population = cache["population"]
        if population is not None:  # how does the scope compare with everyone else?
            for dim, values in _scope(state).filters.items():
                if dim in DIMENSIONS and len(values) == 1:
                    signals += [
                        sig.model_copy(
                            update={
                                "statement": f"Compared with the rest of the "
                                f"business: {sig.statement}"
                            }
                        )
                        for sig in segment_signals(population, [dim])
                        if sig.data["value"] == values[0]
                    ]
            signals.sort(key=lambda sig: sig.strength, reverse=True)
        return {"overview": result.overview, "signals": signals}

    def plan(state: InvestigationState) -> dict:
        model, _ = deps.model("planner")
        frames, activities = frames_and_activities(state)
        o = state["overview"]
        values = {d: sorted(map(str, frames.cases[d].dropna().unique())) for d in DIMENSIONS}
        signals = "\n".join(
            f"- [{s.id}] {s.statement}" for s in state["signals"][:MAX_SIGNALS_FOR_PLANNER]
        )
        prompt = (
            f"Question: {state['question']}\n\n"
            f"Overview: {o.cases} claims, SLA breach rate {o.breach_rate:.1%}, average cycle "
            f"{o.mean_cycle_days:.1f} days, SLA {o.sla_days:.0f} days.\n\nSignals:\n{signals}\n\n"
            f"Dimension values: {values}\n"
            f"Activities: {[a.activity for a in activities.internal]}"
        )
        try:
            planned = llm.structured(model, llm.PlanOut, llm.PLANNER_SYSTEM, prompt).hypotheses
            failure = None
        except ValueError as exc:  # the coverage rule below still builds a plan from signals
            planned, failure = [], f"planner failed ({exc}); hypotheses built from signals"
        hypotheses = []
        for i, h in enumerate(planned[:6], start=1):
            checks, dropped = [], []
            for c in h.checks[:4]:
                try:
                    checks.append(_to_check(c))
                except ValidationError as exc:
                    dropped.append(f"{c.type}: {exc.errors()[0]['msg']}")
            if not any(isinstance(c, PolicyCheck) for c in checks):
                checks.append(PolicyCheck(query=h.statement))
            hypotheses.append(
                Hypothesis(
                    id=f"H{i}",
                    statement=h.statement,
                    signal_ids=h.signal_ids,
                    checks=checks,
                    dropped_checks=dropped,
                )
            )

        # Coverage rule: a significant signal no hypothesis tests gets its own hypothesis,
        # so a strong pattern can never be silently dropped by the planner.
        added = 0
        for sig in state["signals"]:
            if len(hypotheses) >= MAX_HYPOTHESES or sig.kind == "trend":
                break
            low_sample = sig.kind == "segment" and sig.data.get("low_sample")
            weak = sig.strength < COVERAGE_MIN_STRENGTH
            if low_sample or weak or any(_covers(h, sig) for h in hypotheses):
                continue
            hypotheses.append(
                Hypothesis(
                    id=f"H{len(hypotheses) + 1}",
                    statement=f"{sig.statement} This contributes to SLA breaches.",
                    signal_ids=[sig.id],
                    checks=_signal_checks(sig),
                    auto=True,
                )
            )
            added += 1
        notes = [n for n in (failure, f"{added} added by coverage rule" if added else None) if n]
        return {"hypotheses": hypotheses, **({"_note": "; ".join(notes)} if notes else {})}

    def gather(state: InvestigationState) -> dict:
        frames, activities = frames_and_activities(state)
        values = {d: sorted(map(str, frames.cases[d].dropna().unique())) for d in DIMENSIONS}
        ctx = EvidenceContext(
            deps.conn,
            frames,
            activities,
            deps.retriever,
            values,
            targets,
            population=cache["population"],
        )
        hypotheses = []
        for h in state["hypotheses"]:
            evidence = [run_check(ctx, c) for c in h.checks]
            hypotheses.append(h.model_copy(update={"evidence": evidence}))
        return {"hypotheses": hypotheses}

    def assess(state: InvestigationState) -> dict:
        model, _ = deps.model("assessor")
        assessed = []
        for h in state["hypotheses"]:
            evidence = "\n".join(
                f"- {describe_check(e.check)}: {e.summary[:700]}" for e in h.evidence
            )
            try:
                out = llm.structured(
                    model,
                    llm.VerdictOut,
                    llm.ASSESSOR_SYSTEM,
                    f"Hypothesis: {h.statement}\n\nEvidence:\n{evidence}",
                )
                verdict, confidence = out.verdict, out.confidence
                reasoning = _tidy_reasoning(out.reasoning)
            except ValueError as exc:
                verdict, confidence, reasoning = "inconclusive", "low", f"Assessment failed: {exc}"
            update = {"verdict": verdict, "confidence": confidence, "reasoning": reasoning}

            # Rule overrides (deterministic): confounding and small samples.
            segs = [e for e in h.evidence if e.ok and isinstance(e.check, SegmentCheck)]
            confounded = [e for e in segs if e.explained_by]
            if verdict == "supported" and confounded:
                e = confounded[0]
                update |= {
                    "model_verdict": verdict,
                    "verdict": "refuted",
                    "override": f"The {describe_check(e.check).lower()} effect is explained by "
                    f"{', '.join(e.explained_by)} (confounder check).",
                }
            elif (
                verdict == "supported"
                and segs
                and all(e.data.get("low_sample") and not e.data.get("significant") for e in segs)
            ):
                update |= {
                    "model_verdict": verdict,
                    "verdict": "inconclusive",
                    "override": "Only small, non-significant samples support it.",
                }
            assessed.append(h.model_copy(update=update))
        return {"hypotheses": assessed}

    def recommend(state: InvestigationState) -> dict:
        frames, _ = frames_and_activities(state)
        supported = [h for h in state["hypotheses"] if h.verdict == "supported"]
        impacts = {
            a.id: evaluate_action(frames, a, catalogue.economics, cache["population"])
            for a in catalogue.actions.values()
        }
        chosen: dict[str, llm.SelectionOut] = {}
        note = None
        if supported:
            model, _ = deps.model("recommender")
            actions_text = "\n".join(
                f"- {a.id}: {a.title}. {a.description} (policy: {', '.join(a.policy_refs)}; "
                f"effort {a.effort}; est. {impacts[a.id].breaches_avoided:.0f} breaches avoided; "
                f"est. net value {impacts[a.id].annual_net_inr / 1e5:+.1f} lakh a year)"
                for a in catalogue.actions.values()
            )
            hyps = "\n".join(f"- {h.id}: {h.statement}" for h in supported)
            try:
                out = llm.structured(
                    model,
                    llm.RecommendOut,
                    llm.RECOMMENDER_SYSTEM,
                    f"Supported hypotheses:\n{hyps}\n\nAction catalogue:\n{actions_text}",
                )
                valid_h = {h.id for h in supported}
                for s in out.selections:
                    if s.action_id in catalogue.actions:
                        s.hypothesis_ids = [i for i in s.hypothesis_ids if i in valid_h]
                        chosen[s.action_id] = s
            except ValueError as exc:
                note = f"recommender failed: {exc}"
        recs = []
        for a in catalogue.actions.values():
            sel = chosen.get(a.id)
            clauses = [c for ref in a.policy_refs if (c := resolve(deps.conn, pack.domain, ref))]
            recs.append(
                Recommendation(
                    action_id=a.id,
                    title=a.title,
                    description=a.description,
                    effort=a.effort,
                    hypothesis_ids=sel.hypothesis_ids if sel else [],
                    rationale=sel.rationale if sel else "",
                    impact=impacts[a.id],
                    policy=clauses,
                    recommended=sel is not None,
                    cost_effective=impacts[a.id].annual_net_inr > 0,
                )
            )
        recs.sort(key=lambda r: (not r.recommended, -r.impact.annual_net_inr))
        return {"recommendations": recs, **({"_note": note} if note else {})}

    def synthesize(state: InvestigationState) -> dict:
        model, _ = deps.model("synthesizer")
        facts = _facts(state)
        prompt = f"Question: {state['question']}\n\nFacts:\n{facts}"
        summary = llm.plain(model, llm.SYNTHESIS_SYSTEM, prompt).strip()
        check = verify_numbers(summary, facts)
        note = None
        if not check.ok:  # one self-correction round, then show the result with flags
            retry = llm.plain(
                model,
                llm.SYNTHESIS_SYSTEM,
                f"{prompt}\n\nYour previous summary used numbers that are not in the facts: "
                f"{', '.join(check.unverified)}. Rewrite it using only numbers from the facts, "
                f"with the same units (lakh, %, breaches in the period vs a year).",
            ).strip()
            retry_check = verify_numbers(retry, facts)
            note = f"summary rewritten after {len(check.unverified)} unverified number(s)"
            if len(retry_check.unverified) <= len(check.unverified):
                summary, check = retry, retry_check
        return {"summary": summary, "number_check": check, **({"_note": note} if note else {})}

    g = StateGraph(InvestigationState)
    for name, fn, role in [
        ("route", route, "router"),
        ("metric", metric, "router"),
        ("policy", policy, "answer"),
        ("scan", scan_node, None),
        ("plan", plan, "planner"),
        ("gather", gather, None),
        ("assess", assess, "assessor"),
        ("recommend", recommend, "recommender"),
        ("synthesize", synthesize, "synthesizer"),
    ]:
        g.add_node(name, _timed(name, deps, role, fn))
    g.add_edge(START, "route")
    g.add_conditional_edges(
        "route",
        lambda s: {"metric": "metric", "policy": "policy"}.get(s["route"], "scan"),
        {"metric": "metric", "policy": "policy", "scan": "scan"},
    )
    g.add_edge("metric", END)
    g.add_edge("policy", END)
    for a, b in [
        ("scan", "plan"),
        ("plan", "gather"),
        ("gather", "assess"),
        ("assess", "recommend"),
        ("recommend", "synthesize"),
        ("synthesize", END),
    ]:
        g.add_edge(a, b)
    return g.compile()


def run(deps: Deps, question: str, scope: ProcessQuery | None = None) -> Iterator[tuple[str, dict]]:
    """Run the graph, yielding (node name, state update) as each node finishes."""
    graph = build_graph(deps)
    initial: InvestigationState = {
        "question": question,
        "scope": (scope or ProcessQuery()).model_dump(mode="json"),
        "steps": [],
    }
    for chunk in graph.stream(initial, stream_mode="updates"):
        yield from chunk.items()
