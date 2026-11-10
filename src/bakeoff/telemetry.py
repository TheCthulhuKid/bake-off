"""Per-run collector for tool calls, model requests and token usage, shared by every implementation.

A run wraps its work in ``collect()``. Tools call ``record_tool_call()``, implementations call
``record_model_request()`` before each model request and pass token counts to
``record_usage()``. Outside a ``collect()`` block all three are no-ops, so the tools also work
from a shell.
"""

import threading
import time
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from typing import Literal, NoReturn

from pydantic import BaseModel, PrivateAttr, computed_field

from bakeoff.settings import SETTINGS

Limit = Literal["tool_calls", "model_requests", "timeout"]


class RunLimitExceeded(RuntimeError):
    """Raised when a run passes one of its limits, ending the run."""


class ToolLimitExceeded(RunLimitExceeded):
    """Raised by a tool call past the run's tool-call limit."""


class RunStats(BaseModel):
    tool_calls: int = 0
    model_requests: int = 0
    input_tokens: int = 0
    output_tokens: int = 0
    max_tool_calls: int
    max_model_requests: int
    timeout: float
    limit_fired: Limit | None = None
    # Monotonic clock, so a system clock change can't move it.
    _deadline: float = PrivateAttr()

    @computed_field
    @property
    def hit_limit(self) -> bool:
        return self.limit_fired is not None


_LIMIT_ERRORS: dict[Limit, tuple[type[RunLimitExceeded], str]] = {
    "tool_calls": (ToolLimitExceeded, "tool-call limit of {s.max_tool_calls} reached"),
    "model_requests": (RunLimitExceeded, "model-request limit of {s.max_model_requests} reached"),
    "timeout": (RunLimitExceeded, "run timeout of {s.timeout:g} s reached"),
}

_current: ContextVar[RunStats | None] = ContextVar("run_stats", default=None)
# PydanticAI and LangGraph run one reply's tool calls in threads that share the run's RunStats,
# so each limit check and its count must happen as one step.
_count_lock = threading.Lock()


@contextmanager
def collect(
    max_tool_calls: int | None = None,
    max_model_requests: int | None = None,
    timeout: float | None = None,
) -> Iterator[RunStats]:
    """Collect stats for one run; each limit left out comes from ``SETTINGS``.

    ``timeout`` is in seconds, and the deadline starts when the block is entered.
    """
    stats = RunStats(
        max_tool_calls=SETTINGS.max_tool_calls if max_tool_calls is None else max_tool_calls,
        max_model_requests=(
            SETTINGS.max_model_requests if max_model_requests is None else max_model_requests
        ),
        timeout=SETTINGS.run_timeout if timeout is None else timeout,
    )
    stats._deadline = time.monotonic() + stats.timeout
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
    with _count_lock:
        if stats.tool_calls >= stats.max_tool_calls:
            _fire(stats, "tool_calls")
        stats.tool_calls += 1


def record_model_request() -> None:
    """Count one model request before it is sent.

    Raises ``RunLimitExceeded`` instead if the run's deadline has passed or its request cap is
    used up.
    """
    stats = _current.get()
    if stats is None:
        return
    with _count_lock:
        if time.monotonic() >= stats._deadline:
            _fire(stats, "timeout")
        if stats.model_requests >= stats.max_model_requests:
            _fire(stats, "model_requests")
        stats.model_requests += 1


def raise_if_limit_fired() -> None:
    """Raise the run's limit error again once a limit has fired.

    For a framework that turns a tool's exception into an error result for the model.
    """
    stats = _current.get()
    if stats is not None and stats.limit_fired:
        raise _limit_exceeded(stats)


def _fire(stats: RunStats, limit: Limit) -> NoReturn:
    stats.limit_fired = limit
    raise _limit_exceeded(stats)


def _limit_exceeded(stats: RunStats) -> RunLimitExceeded:
    error, message = _LIMIT_ERRORS[stats.limit_fired]
    return error(message.format(s=stats))


def record_usage(input_tokens: int, output_tokens: int) -> None:
    """Add one model response's token counts to the current run."""
    stats = _current.get()
    if stats is None:
        return
    stats.input_tokens += input_tokens
    stats.output_tokens += output_tokens
