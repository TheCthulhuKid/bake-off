import inspect

import pytest

from bakeoff import tools
from bakeoff.impls import get_triage
from bakeoff.prompt import SYSTEM_PROMPT
from bakeoff.telemetry import ToolLimitExceeded, collect


def test_pydanticai_returns_report_and_records_stats(pydanticai_model):
    with collect() as stats:
        report = get_triage("pydanticai")("tiny")
    assert report == pydanticai_model.report
    assert (stats.tool_calls, stats.input_tokens, stats.output_tokens) == (2, 300, 30)
    assert pydanticai_model.seen.instructions == SYSTEM_PROMPT
    # Descriptions are the docstrings without their Args sections, which go into the schema.
    for tool in pydanticai_model.seen.function_tools:
        assert tool.description in inspect.getdoc(getattr(tools, tool.name))


def test_pydanticai_lets_the_tool_limit_end_the_run(pydanticai_model):
    with collect(max_tool_calls=1) as stats, pytest.raises(ToolLimitExceeded):
        get_triage("pydanticai")("tiny")
    assert stats.limit_fired == "tool_calls"
    # The two turns before the limit still count towards cost.
    assert (stats.input_tokens, stats.output_tokens) == (200, 20)
