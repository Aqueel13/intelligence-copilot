"""What the current work is part of (an investigation, a Q&A answer, an evaluation run), so
every LLM call can be attributed. A context variable: it follows the work into the threads the
gateway and the parallel assessor start."""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace


@dataclass(frozen=True)
class Trace:
    purpose: str | None = None  # investigation | qa | metric | evaluation …
    investigation_id: str | None = None
    user_id: str | None = None


_EMPTY = Trace()
_trace: ContextVar[Trace | None] = ContextVar("trace", default=None)


def current_trace() -> Trace:
    return _trace.get() or _EMPTY


# Token accumulator for a block of work (e.g. "what did generating this answer cost?").
_usage: ContextVar[list[int] | None] = ContextVar("usage", default=None)


@contextmanager
def usage_scope() -> Iterator[list[int]]:
    """Collect [input_tokens, output_tokens] of every LLM call made inside the block, in any
    thread that copies this context."""
    totals = [0, 0]
    token = _usage.set(totals)
    try:
        yield totals
    finally:
        _usage.reset(token)


def add_usage(inp: int, out: int) -> None:
    totals = _usage.get()
    if totals is not None:
        totals[0] += inp
        totals[1] += out


@contextmanager
def traced(**fields: str | None) -> Iterator[Trace]:
    """Add fields to the current trace for the code inside the block."""
    trace = replace(current_trace(), **fields)
    token = _trace.set(trace)
    try:
        yield trace
    finally:
        _trace.reset(token)
