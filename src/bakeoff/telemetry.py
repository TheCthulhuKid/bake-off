"""Per-run collector for tool calls and token usage, shared by every implementation.

A run wraps its work in ``collect()``. Tools call ``record_tool_call()`` and implementations
pass token counts to ``record_usage()``. Outside a ``collect()`` block both are no-ops, so
the tools also work from a shell.
"""

import threading
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Literal

from pydantic import BaseModel, computed_field

from bakeoff.settings import SETTINGS


class ToolLimitExceeded(RuntimeError):
    """Raised by a tool call past the run's tool-call limit, ending the run."""


class RunStats(BaseModel):
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    max_tool_calls: int
    limit_fired: Literal["tool_calls"] | None = None

    @computed_field
    @property
    def hit_limit(self) -> bool:
        return self.limit_fired is not None


_current: ContextVar[RunStats | None] = ContextVar("run_stats", default=None)
# PydanticAI and LangGraph run one reply's tool calls in threads that share the run's RunStats,
# so the limit check and the count must happen as one step.
_tool_call_lock = threading.Lock()


@contextmanager
def collect(max_tool_calls: int | None = None) -> Iterator[RunStats]:
    """Collect stats for one run; the limit defaults to ``SETTINGS.max_tool_calls``."""
    if max_tool_calls is None:
        max_tool_calls = SETTINGS.max_tool_calls
    stats = RunStats(max_tool_calls=max_tool_calls)
    token = _current.set(stats)
    try:
        yield stats
    finally:
        _current.reset(token)


def record_tool_call() -> None:
    """Count one tool call, raising ``ToolLimitExceeded`` once the limit is used up."""
    stats = _current.get()
    if stats is None:
        return
    with _tool_call_lock:
        if stats.tool_calls >= stats.max_tool_calls:
            stats.limit_fired = "tool_calls"
            raise _limit_exceeded(stats)
        stats.tool_calls += 1


def raise_if_limit_fired() -> None:
    """Raise ``ToolLimitExceeded`` again once the run's limit has fired.

    For a framework that turns a tool's exception into an error result for the model.
    """
    stats = _current.get()
    if stats is not None and stats.limit_fired:
        raise _limit_exceeded(stats)


def _limit_exceeded(stats: RunStats) -> ToolLimitExceeded:
    return ToolLimitExceeded(f"tool-call limit of {stats.max_tool_calls} reached")


def record_usage(input_tokens: int, output_tokens: int) -> None:
    """Add one model response's token counts to the current run."""
    stats = _current.get()
    if stats is None:
        return
    stats.input_tokens += input_tokens
    stats.output_tokens += output_tokens
