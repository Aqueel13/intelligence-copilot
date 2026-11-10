"""Evaluation suites. Each returns plain dicts (JSON-ready) so results can be merged later.

- investigation: full agent runs scored against planted ground truth
- qa:            grounded answers (citation accuracy, grounding, refusals of unanswerable)
- retrieval:     Hit@k / MRR per method (no LLM)
- whatif:        what-if estimates vs exact counterfactuals (no LLM)
"""

import re
import time
import traceback
from pathlib import Path
from typing import Any

import yaml

from watchdog_backend.analytics.metrics import MetricsEngine
from watchdog_backend.analytics.process import ProcessQuery
from watchdog_backend.config import get_settings
from watchdog_backend.db import get_engine
from watchdog_backend.domain.pack import get_pack
from watchdog_backend.evaluation.usage import UsageCounter
from watchdog_backend.investigation.actions import evaluate_action, get_catalogue
from watchdog_backend.investigation.data import load_frames
from watchdog_backend.investigation.graph import Deps, run
from watchdog_backend.investigation.scoring import score
from watchdog_backend.knowledge.answer import answer_question
from watchdog_backend.knowledge.evaluation import evaluate, is_relevant, load_benchmark
from watchdog_backend.knowledge.models import get_reranker
from watchdog_backend.knowledge.service import benchmark_path, get_retriever
from watchdog_backend.llm.gateway import ModelSpec, build_chat_model

ROLES = ("router", "planner", "assessor", "recommender", "synthesizer", "answer", "default")
_ACCOUNT_ID = re.compile(r"org_[a-z0-9]{10,}")


def _redact(text: str) -> str:
    """Provider errors can name the account (e.g. Groq organisation ids): never record them."""
    return _ACCOUNT_ID.sub("org_<redacted>", text)


def load_spec() -> dict[str, Any]:
    path = (
        Path(get_settings().domain_packs_dir)
        / get_pack().domain
        / "evaluation"
        / "investigations.yaml"
    )
    return yaml.safe_load(path.read_text(encoding="utf-8"))


def _model(spec: ModelSpec, counter: UsageCounter):
    model = build_chat_model(spec)
    model.callbacks = [counter]
    return model


# ------------------------------------------------------------------------- investigation


def investigation_run(model_id: str, seed: int, q: dict[str, Any], spec: dict[str, Any]) -> dict:
    counter = UsageCounter()
    model = _model(ModelSpec.parse(model_id), counter)
    record: dict[str, Any] = {
        "suite": "investigation",
        "model": model_id,
        "seed": seed,
        "question_id": q["id"],
        "question": q["question"],
    }
    started = time.perf_counter()
    try:
        with get_engine().connect() as conn:
            deps = Deps(
                conn,
                MetricsEngine(get_pack()),
                get_retriever(),
                get_reranker(),
                {role: (model, model_id) for role in ROLES},
            )
            state: dict[str, Any] = {}
            for _, update in run(
                deps, q["question"], ProcessQuery.model_validate(q.get("scope") or {})
            ):
                state.update(update)
    except Exception as exc:  # recorded, never fatal: a failed run is a result too
        record |= {
            "ok": False,
            "error": _redact(f"{type(exc).__name__}: {str(exc)[:300]}"),
            "traceback": _redact(traceback.format_exc()[-1500:]),
            "duration_s": round(time.perf_counter() - started, 1),
            **counter.snapshot(),
        }
        return record

    hypotheses = state.get("hypotheses", [])
    s = score(hypotheses)
    expected = q["expect_found"]
    recommended = [r.action_id for r in state.get("recommendations", []) if r.recommended]
    remedies = spec["remedies"]
    remedied = {
        rc: any(a in recommended for a in remedies.get(rc, [])) for rc in expected if s.found[rc]
    }
    negative = [
        r.action_id
        for r in state.get("recommendations", [])
        if r.recommended and not r.cost_effective
    ]
    check = state.get("number_check")
    record |= {
        "ok": True,
        "route": state.get("route"),
        "duration_s": round(time.perf_counter() - started, 1),
        "steps": {st.node: round(st.ms / 1000, 2) for st in state.get("steps", [])},
        "notes": [f"{st.node}: {st.note}" for st in state.get("steps", []) if st.note],
        **counter.snapshot(),
        "found": s.found,
        "expected": expected,
        "expected_found": sum(s.found[rc] for rc in expected),
        "recall": sum(s.found[rc] for rc in expected) / len(expected),
        "decoys": q.get("decoys", []),
        "decoys_accepted": [d for d in q.get("decoys", []) if s.decoys_accepted[d]],
        "hypotheses": len(hypotheses),
        "supported": sum(h.verdict == "supported" for h in hypotheses),
        "coverage_added": sum(h.auto for h in hypotheses),
        "overrides": [
            {
                "id": h.id,
                "statement": h.statement[:160],
                "model_said": h.model_verdict,
                "reason": h.override,
            }
            for h in hypotheses
            if h.override
        ],
        "recommended": recommended,
        "remedied": remedied,
        "negative_value_recommended": negative,
        "numbers_found": check.numbers_found if check else 0,
        "numbers_unverified": check.unverified if check else [],
        "hypothesis_detail": [
            {"id": h.id, "verdict": h.verdict, "auto": h.auto, "statement": h.statement[:200]}
            for h in hypotheses
        ],
    }
    return record


# ----------------------------------------------------------------------------------- qa


def qa_suite(model_id: str, spec: dict[str, Any], pause_s: float = 0.0) -> list[dict]:
    counter = UsageCounter()
    model = _model(ModelSpec.parse(model_id), counter)
    questions = [(q.q, q) for q in load_benchmark(benchmark_path())]
    questions += [(text, None) for text in spec.get("unanswerable", [])]
    out = []
    for text, bench in questions:
        counter.reset()
        rec: dict[str, Any] = {
            "suite": "qa",
            "model": model_id,
            "question": text,
            "answerable": bench is not None,
        }
        try:
            with get_engine().connect() as conn:
                a = answer_question(conn, get_retriever(), model, model_id, text, get_reranker())
            cited = [c for c in a.sources if any(c.chunk_id == x.chunk_id for x in a.citations)]
            rec |= {
                "ok": True,
                "found": a.found,
                "grounded": a.grounded,
                "model_citation_accuracy": a.model_citation_accuracy,
                "statuses": [c.status for c in a.checks],
                "cites_relevant": bool(bench) and any(is_relevant(c, bench) for c in cited),
                "generation_ms": round(a.generation_ms),
                **counter.snapshot(),
            }
        except Exception as exc:
            rec |= {"ok": False, "error": _redact(f"{type(exc).__name__}: {str(exc)[:300]}")}
        out.append(rec)
        if pause_s:
            time.sleep(pause_s)
    return out


# ---------------------------------------------------------------------- no-LLM suites


def retrieval_suite() -> list[dict]:
    with get_engine().connect() as conn:
        results = evaluate(conn, get_retriever(), load_benchmark(benchmark_path()))
    return [{"suite": "retrieval", **r.model_dump()} for r in results]


TRUTH_KEYS = {
    "delegate_mid_value_approvals": ("delegation_scenario", "breaches_avoided"),
    "add_senior_adjuster_capacity": ("root_causes", "RC1", "breaches_attributable"),
    "enforce_broker_checklist": ("root_causes", "RC2", "breaches_attributable"),
    "retrain_team_b": ("root_causes", "RC3", "breaches_attributable"),
    "saturday_rota": ("root_causes", "RC4", "breaches_attributable"),
}


def whatif_suite(seed: int, dataset) -> list[dict]:
    truth = dataset.summary()
    with get_engine().connect() as conn:
        frames = load_frames(conn, MetricsEngine(get_pack()), ProcessQuery())
    cat = get_catalogue()
    out = []
    for action_id, keys in TRUTH_KEYS.items():
        actual: Any = truth
        for k in keys:
            actual = actual[k]
        est = evaluate_action(frames, cat.actions[action_id], cat.economics).breaches_avoided
        out.append(
            {
                "suite": "whatif",
                "seed": seed,
                "action": action_id,
                "estimate": round(est, 1),
                "truth": actual,
                "ratio": round(est / actual, 3) if actual else None,
            }
        )
    return out
