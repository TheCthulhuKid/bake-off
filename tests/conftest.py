import os
from pathlib import Path

import pytest
from pydantic_ai import models
from pydantic_ai.messages import ModelResponse, ToolCallPart
from pydantic_ai.models.function import AgentInfo, FunctionModel
from pydantic_ai.usage import RequestUsage

from bakeoff.contract import Theme, TopIssue, TriageReport

# Set before bakeoff.settings is imported, so clients build without a real key.
os.environ["ANTHROPIC_API_KEY"] = "test-key"
# Any real model request fails; tests run on fake models only.
models.ALLOW_MODEL_REQUESTS = False

REPORT = TriageReport(
    themes=[Theme(name="Startup crashes", issues=[1])],
    duplicates=[],
    top_issues=[TopIssue(number=1, reason="Crashes on launch")],
    suggested_labels={2: ["enhancement"]},
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
