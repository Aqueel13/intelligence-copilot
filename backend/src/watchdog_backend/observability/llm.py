"""A LangChain callback that records every LLM call: role, model, latency, tokens, status,
and what it was part of (pack, investigation, user)."""

import re
import time
from typing import Any
from uuid import UUID

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult

from watchdog_backend.domain.pack import current_domain
from watchdog_backend.observability.context import add_usage, current_trace
from watchdog_backend.observability.recorder import record

_ACCOUNT_ID = re.compile(r"org_[a-z0-9]{10,}")  # provider errors can name the account


def tokens(response: LLMResult) -> tuple[int, int]:
    inp = out = 0
    for generations in response.generations:
        for g in generations:
            usage = getattr(getattr(g, "message", None), "usage_metadata", None) or {}
            inp += int(usage.get("input_tokens", 0) or 0)
            out += int(usage.get("output_tokens", 0) or 0)
    return inp, out


class LLMTracer(BaseCallbackHandler):
    def __init__(self, role: str, model_id: str, tier: str = "standard") -> None:
        self.role = role
        self.model_id = model_id
        self.tier = tier
        self._started: dict[UUID, float] = {}

    def _start(self, run_id: UUID) -> None:
        self._started[run_id] = time.perf_counter()

    def on_llm_start(self, serialized: Any, prompts: Any, *, run_id: UUID, **_: Any) -> None:
        self._start(run_id)

    def on_chat_model_start(
        self, serialized: Any, messages: Any, *, run_id: UUID, **_: Any
    ) -> None:
        self._start(run_id)

    def _record(self, run_id: UUID, status: str, **extra: Any) -> None:
        started = self._started.pop(run_id, None)
        trace = current_trace()
        record(
            "llm_calls",
            {
                "domain": current_domain(),
                "role": self.role,
                "model": self.model_id,
                "provider": self.model_id.split(":", 1)[0],
                "tier": self.tier,
                "purpose": trace.purpose,
                "investigation_id": trace.investigation_id,
                "user_id": trace.user_id,
                "duration_ms": int((time.perf_counter() - started) * 1000) if started else 0,
                "status": status,
                "tokens_saved": 0,
                **extra,
            },
        )

    def on_llm_end(self, response: LLMResult, *, run_id: UUID, **_: Any) -> None:
        inp, out = tokens(response)
        add_usage(inp, out)
        self._record(run_id, "ok", input_tokens=inp, output_tokens=out)

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **_: Any) -> None:
        self._record(
            run_id,
            "error",
            input_tokens=0,
            output_tokens=0,
            error=_ACCOUNT_ID.sub("org_<redacted>", str(error))[:300],
        )
