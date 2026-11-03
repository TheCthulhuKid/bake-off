import inspect
import json

import pytest
from langchain_core.utils.function_calling import convert_to_openai_tool

from bakeoff import tools
from bakeoff.impls import get_triage
from bakeoff.prompt import REPORT_PROMPT, SYSTEM_PROMPT
from bakeoff.telemetry import ToolLimitExceeded, collect


def test_pydanticai_returns_report_and_records_stats(pydanticai_model):
    with collect() as stats:
        report = get_triage("pydanticai")("tiny")
    assert report == pydanticai_model.report
    assert (stats.tool_calls, stats.input_tokens, stats.output_tokens) == (2, 300, 30)
    assert pydanticai_model.seen.instructions == SYSTEM_PROMPT
    # A dict is sent to the API as an object that can only be {}.
    schema = pydanticai_model.seen.output_tools[0].parameters_json_schema
    assert schema["properties"]["suggested_labels"]["type"] == "array"
    # Descriptions are the docstrings without their Args sections, which go into the schema.
    for tool in pydanticai_model.seen.function_tools:
        assert tool.description in inspect.getdoc(getattr(tools, tool.name))


def test_langgraph_returns_report_and_records_stats(langgraph_model):
    with collect() as stats:
        report = get_triage("langgraph")("tiny")
    assert report == langgraph_model.report
    # One more model call than PydanticAI: analyse runs after fetch ends.
    assert (stats.tool_calls, stats.input_tokens, stats.output_tokens) == (2, 400, 40)
    assert langgraph_model.seen[0].content == SYSTEM_PROMPT
    # The API rejects a report call that ends on the model's own reply.
    assert langgraph_model.seen[-1].content == REPORT_PROMPT
    # LangChain joins the docstring's lines with spaces, so compare with whitespace normalised.
    for tool in langgraph_model.tools:
        description = convert_to_openai_tool(tool)["function"]["description"]
        assert " ".join(description.split()) in " ".join(inspect.getdoc(tool).split())


def test_anthropic_returns_report_and_records_stats(anthropic_model):
    with collect() as stats:
        report = get_triage("anthropic")("tiny")
    assert report == anthropic_model.report
    assert (stats.tool_calls, stats.input_tokens, stats.output_tokens) == (2, 300, 30)
    # Under message threads, later requests leave out the system prompt and tools.
    first = anthropic_model.sent[0]
    assert first["system"] == SYSTEM_PROMPT
    for tool in first["tools"]:
        assert tool["description"] in inspect.getdoc(getattr(tools, tool["name"]))
    # The runner sends a dict result's keys as content blocks, which the API rejects.
    result = anthropic_model.sent[1]["messages"][-1]["content"][0]
    assert json.loads(result["content"]) == tools.list_issues("tiny")


@pytest.mark.parametrize("impl", ["pydanticai", "langgraph", "anthropic"])
def test_tool_limit_ends_the_run(impl, request):
    request.getfixturevalue(f"{impl}_model")
    with collect(max_tool_calls=1) as stats, pytest.raises(ToolLimitExceeded):
        get_triage(impl)("tiny")
    assert stats.limit_fired == "tool_calls"
    # The two turns before the limit still count towards cost.
    assert (stats.input_tokens, stats.output_tokens) == (200, 20)
