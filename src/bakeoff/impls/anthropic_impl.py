"""Anthropic SDK version"""

import anthropic
from anthropic import beta_tool, transform_schema
from anthropic.types.beta import BetaJSONOutputFormatParam

from bakeoff.contract import TriageReport
from bakeoff.prompt import SYSTEM_PROMPT, user_prompt
from bakeoff.settings import SETTINGS
from bakeoff.telemetry import raise_if_limit_fired, record_usage
from bakeoff.tools import get_issue, list_issues, search_issues

TOOLS = [beta_tool(list_issues), beta_tool(get_issue), beta_tool(search_issues)]
REPORT_FORMAT: BetaJSONOutputFormatParam = {
    "type": "json_schema",
    "schema": transform_schema(TriageReport),
}

_key = SETTINGS.anthropic_api_key
client = anthropic.Anthropic(api_key=_key.get_secret_value() if _key else None)


def triage(repo: str) -> TriageReport:
    """Triage a repository"""
    runner = client.beta.messages.tool_runner(
        model=SETTINGS.model,
        # The model's maximum output, which the other frameworks send by default. The SDK only
        # allows a request this large when it is streamed.
        max_tokens=128_000,
        stream=True,
        system=SYSTEM_PROMPT,
        messages=[{"role": "user", "content": user_prompt(repo)}],
        tools=TOOLS,
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
