import json
import os
from pathlib import Path
from typing import ClassVar

import anthropic
import httpx2
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
        # analyse binds the same tools again with the report schema; keep the first list.
        if not self.tools:
            self.tools = list(tools)
        return self

    def _generate(self, messages, stop=None, run_manager=None, **kwargs) -> ChatResult:
        self.seen = messages
        script = [
            [("list_issues", {"repo": "tiny"})],
            [("get_issue", {"repo": "tiny", "number": 1})],
            [],
        ]
        # Each earlier turn left one AI message, so this counts the turns taken so far.
        turn = sum(message.type == "ai" for message in messages)
        calls = script[turn] if turn < len(script) else []
        reply = AIMessage(
            # The report call answers in JSON text, as the API does under output_config.format.
            content=REPORT.model_dump_json() if turn == len(script) else "",
            tool_calls=[{"name": name, "args": args, "id": f"call_{name}"} for name, args in calls],
            usage_metadata={"input_tokens": 100, "output_tokens": 10, "total_tokens": 110},
            # The usage callback ignores a message without a model name.
            response_metadata={"model_name": "scripted"},
        )
        return ChatResult(generations=[ChatGeneration(message=reply)])


def _sse(turn: int, block: dict, stop_reason: str) -> bytes:
    """One streamed Messages API reply holding ``block``, using 100 + 10 tokens."""
    message = {
        "id": f"msg_{turn}",
        "type": "message",
        "role": "assistant",
        "model": "scripted",
        "content": [],
        "stop_reason": None,
        "stop_sequence": None,
        "usage": {"input_tokens": 100, "output_tokens": 0},
    }
    if block["type"] == "text":
        start, delta = {"type": "text", "text": ""}, {"type": "text_delta", "text": block["text"]}
    else:
        start = {**block, "input": {}}
        delta = {"type": "input_json_delta", "partial_json": json.dumps(block["input"])}
    events = [
        {"type": "message_start", "message": message},
        {"type": "content_block_start", "index": 0, "content_block": start},
        {"type": "content_block_delta", "index": 0, "delta": delta},
        {"type": "content_block_stop", "index": 0},
        {
            "type": "message_delta",
            "delta": {"stop_reason": stop_reason, "stop_sequence": None},
            "usage": {"output_tokens": 10},
        },
        {"type": "message_stop"},
    ]
    return "".join(f"event: {e['type']}\ndata: {json.dumps(e)}\n\n" for e in events).encode()


class ScriptedTransport(httpx2.MockTransport):
    """Answers the Messages API with list_issues, then get_issue, then ``REPORT`` as JSON text."""

    report = REPORT

    def __init__(self):
        super().__init__(self.respond)
        self.sent: list[dict] = []

    def respond(self, request: httpx2.Request) -> httpx2.Response:
        self.sent.append(json.loads(request.content))
        calls = [("list_issues", {"repo": "tiny"}), ("get_issue", {"repo": "tiny", "number": 1})]
        turn = len(self.sent) - 1
        if turn < len(calls):
            name, args = calls[turn]
            block = {"type": "tool_use", "id": f"call_{turn}", "name": name, "input": args}
            body = _sse(turn, block, "tool_use")
        else:
            body = _sse(turn, {"type": "text", "text": self.report.model_dump_json()}, "end_turn")
        return httpx2.Response(200, headers={"content-type": "text/event-stream"}, content=body)


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


@pytest.fixture
def anthropic_model(tiny_root, monkeypatch):
    """Run the tool runner against a fresh ``ScriptedTransport`` over the tiny fixture."""
    from bakeoff.impls import anthropic_impl

    transport = ScriptedTransport()
    http_client = httpx2.Client(transport=transport)
    client = anthropic.Anthropic(api_key="test-key", max_retries=0, http_client=http_client)
    monkeypatch.setattr(anthropic_impl, "client", client)
    return transport
