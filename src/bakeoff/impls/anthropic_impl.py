"""Anthropic SDK version"""

import functools
import json
from collections.abc import Callable

import anthropic
from anthropic import beta_tool, transform_schema
from anthropic.types.beta import BetaJSONOutputFormatParam

from bakeoff.contract import TriageReport
from bakeoff.prompt import SYSTEM_PROMPT, user_prompt
from bakeoff.settings import SETTINGS
from bakeoff.telemetry import raise_if_limit_fired, record_usage
from bakeoff.tools import TOOLS


def as_json(tool: Callable[..., dict]) -> Callable[..., str]:
    """``tool`` with its dict result as JSON text, which the runner sends as the result.

    The runner takes only a string or content blocks. It sends a dict's keys as blocks, and the
    API rejects them. ``json.dumps`` is what LangGraph's ``ToolNode`` uses for a dict.
    """

    @functools.wraps(tool)
    def wrapper(*args, **kwargs) -> str:
        return json.dumps(tool(*args, **kwargs), ensure_ascii=False)

    return wrapper


RUNNER_TOOLS = [beta_tool(as_json(tool)) for tool in TOOLS]
REPORT_FORMAT: BetaJSONOutputFormatParam = {
    "type": "json_schema",
    "schema": transform_schema(TriageReport),
}

client = anthropic.Anthropic(api_key=SETTINGS.api_key())


def triage(repo: str) -> TriageReport:
    """Triage a repository"""
    runner = client.beta.messages.tool_runner(
        model=SETTINGS.model,
        # The other frameworks send the model's maximum output by default. The SDK only allows a
        # request this large when it is streamed.
        max_tokens=SETTINGS.max_output_tokens(),
        stream=True,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt(repo)}],
        tools=RUNNER_TOOLS,
        output_config={"effort": SETTINGS.effort, "format": REPORT_FORMAT},
    )
    for stream in runner:
        message = stream.get_final_message()
        record_usage(message.usage.input_tokens, message.usage.output_tokens)
        # The runner turns a tool's exception into an error result for the model, so the limit is
        # checked here, once the reply's tools have run and before the next request.
        runner.generate_tool_call_response()
        raise_if_limit_fired()
    text = "".join(block.text for block in message.content if block.type == "text")
    return TriageReport.model_validate_json(text)
