"""Count LLM calls and tokens for any chat model, via a LangChain callback."""

from typing import Any

from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult


class UsageCounter(BaseCallbackHandler):
    def __init__(self) -> None:
        self.calls = 0
        self.input_tokens = 0
        self.output_tokens = 0
        self.errors = 0

    def on_llm_end(self, response: LLMResult, **_: Any) -> None:
        self.calls += 1
        for generations in response.generations:
            for g in generations:
                usage = getattr(getattr(g, "message", None), "usage_metadata", None) or {}
                self.input_tokens += int(usage.get("input_tokens", 0) or 0)
                self.output_tokens += int(usage.get("output_tokens", 0) or 0)

    def on_llm_error(self, error: BaseException, **_: Any) -> None:
        self.errors += 1

    def snapshot(self) -> dict[str, int]:
        return {
            "llm_calls": self.calls,
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "llm_errors": self.errors,
        }

    def reset(self) -> None:
        self.calls = self.input_tokens = self.output_tokens = self.errors = 0
