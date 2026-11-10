"""LLM output schemas (kept flat so small local models fill them reliably) and prompts."""

from typing import Literal

from langchain_core.language_models import BaseChatModel
from langchain_core.messages import HumanMessage, SystemMessage
from pydantic import BaseModel, Field, ValidationError


class RouteOut(BaseModel):
    route: Literal["investigation", "metric", "policy"] = Field(
        description="investigation = why/root cause/what to do; metric = one number or breakdown; "
        "policy = what a rule or procedure says"
    )


class MetricOut(BaseModel):
    metric: str
    group_by: list[str] = Field(default_factory=list)
    filters: dict[str, list[str]] = Field(default_factory=dict)


class CheckOut(BaseModel):
    type: Literal["segment", "activity_wait", "weekday_handoff", "policy"]
    dimension: str | None = None
    value: str | None = None
    outcome: Literal["breached", "doc_requested", "rework"] | None = None
    activity: str | None = None
    weekday: str | None = None
    query: str | None = None


class HypothesisOut(BaseModel):
    statement: str = Field(description="One testable sentence: what causes the problem and how")
    signal_ids: list[str] = Field(default_factory=list)
    checks: list[CheckOut] = Field(
        min_length=2, max_length=4, description="2-4 checks that could confirm or refute it"
    )


class PlanOut(BaseModel):
    hypotheses: list[HypothesisOut] = Field(
        min_length=3, max_length=6, description="3-6 distinct hypotheses"
    )


class VerdictOut(BaseModel):
    verdict: Literal["supported", "refuted", "inconclusive"]
    confidence: Literal["low", "medium", "high"]
    reasoning: str = Field(
        description="2-3 complete sentences of plain prose citing the evidence numbers; "
        "no lists, no headings, never end with a colon"
    )


class SelectionOut(BaseModel):
    action_id: str
    hypothesis_ids: list[str]
    rationale: str


class RecommendOut(BaseModel):
    selections: list[SelectionOut]


def structured[T: BaseModel](
    model: BaseChatModel, schema: type[T], system: str, user: str, retries: int = 1
) -> T:
    """Call the model for a structured answer; retry once with the validation error."""
    from langchain_ollama import ChatOllama

    method = "json_schema" if isinstance(model, ChatOllama) else "function_calling"
    runnable = model.with_structured_output(schema, method=method)
    messages = [SystemMessage(system), HumanMessage(user)]
    last: Exception | None = None
    for _ in range(retries + 1):
        try:
            out = runnable.invoke(messages)
            if isinstance(out, schema):
                return out
            return schema.model_validate(out)
        except (ValidationError, ValueError, TypeError) as exc:
            last = exc
            messages = [
                *messages,
                HumanMessage(
                    f"Your previous answer was invalid: {exc}. "
                    "Answer again using exactly the schema."
                ),
            ]
    raise ValueError(f"Model did not return a valid {schema.__name__}: {last}")


ROUTER_SYSTEM = """Classify the user's question about claims operations.
- investigation: asks WHY something happens, for root causes, or what to do about a problem
- metric: asks for a number, rate, count, trend or breakdown, without asking why
- policy: asks what a policy, rule, procedure, threshold or target says"""

PLANNER_SYSTEM = """You are a senior operations analyst planning a root-cause investigation of an \
insurance claims process. You are given an overview and SIGNALS found by a statistical scan.

Write 3 to 6 distinct, testable hypotheses that could explain the problem in the question. \
Base them on the signals. Include at least one hypothesis that a signal might be misleading \
(for example a difference that could be explained by claim amount or channel mix).

For each hypothesis give 2 to 4 checks. Check types:
- segment: compare a rate for one dimension value against the rest. Needs dimension, value and \
outcome (breached, doc_requested or rework). Use only the dimension values listed.
- activity_wait: waiting time before an activity. Needs activity (use the exact name listed).
- weekday_handoff: waiting after handoffs on a weekday. Needs weekday (Mon-Fri).
- policy: search policies and procedures. Needs query (a short natural-language question).
Every hypothesis should include one policy check."""

ASSESSOR_SYSTEM = """You judge one hypothesis about an insurance claims process using ONLY the \
evidence given. A hypothesis can be supported as a contributing cause even if it is not the \
largest cause. Lines starting "Mechanism:" show whether the pattern goes with more SLA breaches. \
Verdicts:
- supported: the evidence shows the effect and a mechanism linking it to breaches, and it is \
not explained away by other factors
- refuted: the evidence contradicts it, or the difference disappears when controlling for \
another factor (a confounder)
- inconclusive: too little data, not statistically significant, or mixed evidence
Quote the key numbers from the evidence in your reasoning. Never invent numbers."""

RECOMMENDER_SYSTEM = """You recommend corrective actions for confirmed root causes in a claims \
process. Choose ONLY from the action catalogue, by action_id. For each chosen action list the \
hypothesis ids it addresses and a one-sentence rationale. Choose actions only for supported \
hypotheses. Prefer actions with positive net value. Only choose an action with negative net \
value if no positive alternative addresses that hypothesis, and say so in the rationale. When \
two actions address the same cause, prefer the one with the higher net value. Do not invent \
actions."""

SYNTHESIS_SYSTEM = """Write an executive summary of a root-cause investigation for a Head of \
Claims, in 4 to 6 sentences of plain business English. State the problem, the confirmed root \
causes in order of impact, anything that looked like a cause but was ruled out and why, and \
the recommended actions with their estimated effect. Use ONLY numbers that appear in the facts \
provided, written the same way and with the same units: keep "in the months analysed" and "a \
year" figures distinct, and write money as given (₹ lakh). Do not use bullet points or headings."""


def plain(model: BaseChatModel, system: str, user: str) -> str:
    reply = model.invoke([SystemMessage(system), HumanMessage(user)])
    return reply.content if isinstance(reply.content, str) else str(reply.content)
