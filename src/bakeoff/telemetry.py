"""Per-run collector for tool calls and token usage, shared by every implementation.

A run wraps its work in ``collect()``. Tools call ``record_tool_call()`` and implementations
pass token counts to ``record_usage()``. Outside a ``collect()`` block both are no-ops, so
the tools also work from a shell.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar

from pydantic import BaseModel, computed_field

from bakeoff.settings import SETTINGS


class ToolLimitExceeded(RuntimeError):
    """Raised by a tool call past the run's tool-call limit, ending the run."""


class RunStats(BaseModel):
    tool_calls: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    max_tool_calls: int
    limit_fired: str | None = None

    @computed_field
    @property
    def hit_limit(self) -> bool:
        return self.limit_fired is not None


_current: ContextVar[RunStats | None] = ContextVar("run_stats", default=None)


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
    if stats.tool_calls >= stats.max_tool_calls:
        stats.limit_fired = "tool_calls"
        raise ToolLimitExceeded(f"tool-call limit of {stats.max_tool_calls} reached")
    stats.tool_calls += 1


def record_usage(input_tokens: int, output_tokens: int) -> None:
    """Add one model response's token counts to the current run."""
    stats = _current.get()
    if stats is None:
        return
    stats.input_tokens += input_tokens
    stats.output_tokens += output_tokens
