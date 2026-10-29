import inspect

import pytest
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RequestUsage

from bakeoff import tools
from bakeoff.contract import Theme, TopIssue, TriageReport
from bakeoff.impls import pydanticai_impl
from bakeoff.prompt import SYSTEM_PROMPT
from bakeoff.telemetry import ToolLimitExceeded, collect

pytestmark = pytest.mark.usefixtures("tiny_root")

REPORT = TriageReport(
    themes=[Theme(name="Startup crashes", issues=[1])],
    duplicates=[],
    top_issues=[TopIssue(number=1, reason="Crashes on launch")],
    suggested_labels={2: ["enhancement"]},
)


class ScriptedModel(FunctionModel):
    """Calls list_issues, then get_issue, then returns ``REPORT``, using 100 + 10 tokens a turn."""

    def __init__(self):
        super().__init__(self.respond)
        self.seen: AgentInfo | None = None

    def respond(self, messages, info: AgentInfo) -> ModelResponse:
        self.seen = info
        # Requests and responses alternate, so this counts the turns taken so far.
        script = [
            ToolCallPart("list_issues", {"repo": "tiny"}),
            ToolCallPart("get_issue", {"repo": "tiny", "number": 1}),
            ToolCallPart(info.output_tools[0].name, REPORT.model_dump(mode="json")),
        ]
        part = script[len(messages) // 2]
        return ModelResponse(parts=[part], usage=RequestUsage(input_tokens=100, output_tokens=10))


def test_pydanticai_returns_report_and_records_stats():
    model = ScriptedModel()
    with collect() as stats, pydanticai_impl.agent.override(model=model):
        report = pydanticai_impl.triage("tiny")
    assert report == REPORT
    assert (stats.tool_calls, stats.input_tokens, stats.output_tokens) == (2, 300, 30)
    assert model.seen.instructions == SYSTEM_PROMPT
    # Descriptions are the docstrings without their Args sections, which go into the schema.
    for tool in model.seen.function_tools:
        assert tool.description in inspect.getdoc(getattr(tools, tool.name))


def test_pydanticai_lets_the_tool_limit_end_the_run():
    with collect(max_tool_calls=1) as stats, pydanticai_impl.agent.override(model=ScriptedModel()):
        with pytest.raises(ToolLimitExceeded):
            pydanticai_impl.triage("tiny")
    assert stats.limit_fired == "tool_calls"
    # The two turns before the limit still count towards cost.
    assert (stats.input_tokens, stats.output_tokens) == (200, 20)
