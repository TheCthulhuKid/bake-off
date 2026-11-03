import os
from pathlib import Path
from typing import ClassVar

import pytest
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult
from pydantic_ai import models
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RequestUsage

from bakeoff.contract import LabelSuggestion, Theme, TopIssue, TriageReport

# Set before bakeoff.settings is imported, so clients build without a real key.
os.environ["ANTHROPIC_API_KEY"] = "test-key"
# Any real model request fails; tests run on fake models only.
models.ALLOW_MODEL_REQUESTS = False

REPORT = TriageReport(
    themes=[Theme(name="Startup crashes", issues=[1])],
    duplicates=[],
    top_issues=[TopIssue(number=1, reason="Crashes on launch")],
    suggested_labels=[LabelSuggestion(number=2, labels=["enhancement"])],
)


class ScriptedModel(FunctionModel):
    """Calls list_issues, then get_issue, then returns ``REPORT``, using 100 + 10 tokens a turn."""

    report = REPORT

    def __init__(self):
        super().__init__(self.respond)
        self.seen: AgentInfo | None = None

    def respond(self, messages, info: AgentInfo) -> ModelResponse:
        self.seen = info
        script = [
            ToolCallPart("list_issues", {"repo": "tiny"}),
            ToolCallPart("get_issue", {"repo": "tiny", "number": 1}),
            ToolCallPart(info.output_tools[0].name, REPORT.model_dump(mode="json")),
        ]
        # Requests and responses alternate, so this counts the turns taken so far.
        part = script[len(messages) // 2]
        return ModelResponse(parts=[part], usage=RequestUsage(input_tokens=100, output_tokens=10))


class ScriptedChatModel(BaseChatModel):
    """
    Calls list_issues, then get_issue, ends the loop, then returns ``REPORT``,
    using 100 + 10 tokens a turn.
    """

    report: ClassVar[TriageReport] = REPORT
    tools: list = []
    seen: list = []

    @property
    def _llm_type(self) -> str:
        return "scripted"

    def bind_tools(self, tools, **kwargs):
        # with_structured_output binds again with the report schema; keep the three tools.
        if not self.tools:
            self.tools = list(tools)
        return self

    def _generate(
            self, messages, stop=None,
            run_manager=None, **kwargs
    ) -> ChatResult:
        self.seen = messages
        script = [
            [("list_issues", {"repo": "tiny"})],
            [("get_issue", {"repo": "tiny", "number": 1})],
            [],
            [("TriageReport", REPORT.model_dump(mode="json"))]
        ]
        # Each earlier turn left one AI message, so this counts the turns taken so far.
        calls = script[sum(message.type == "ai" for message in messages)]
        reply = AIMessage(
            content="",
            tool_calls=[
                {"name": name, "args": args, "id": f"call_{name}"} for name, args in calls
            ],
            usage_metadata={"input_tokens": 100, "output_tokens": 10, "total_tokens": 110},
            # The usage callback ignores a message without a model name.
            response_metadata={"model_name": "scripted"},
        )
        return ChatResult(generations=[ChatGeneration(message=reply)])


@pytest.fixture
def tiny_root(monkeypatch):
    """Point every fixture lookup, the tools included, at ``tests/fixtures``."""
    monkeypatch.setattr("bakeoff.fixtures.FIXTURE_ROOT", Path(__file__).parent / "fixtures")


@pytest.fixture
def pydanticai_model(tiny_root):
    """Run the PydanticAI agent on a fresh ``ScriptedModel`` over the tiny fixture."""
    from bakeoff.impls import pydanticai_impl

    model = ScriptedModel()
    with pydanticai_impl.agent.override(model=model):
        yield model


@pytest.fixture
def langgraph_model(tiny_root, monkeypatch):
    """Run the LangGraph graph on a fresh ``ScriptedChatModel`` over the tiny fixture."""
    from bakeoff.impls import langgraph_impl

    model = ScriptedChatModel()
    monkeypatch.setattr(langgraph_impl, "graph", langgraph_impl.build_graph(model))
    return model
