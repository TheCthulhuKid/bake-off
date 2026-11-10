"""PydanticAI version: one agent with the shared tools and ``TriageReport`` as its output type."""

from pydantic_ai import Agent, RunContext
from pydantic_ai.capabilities import Hooks
from pydantic_ai.exceptions import UnexpectedModelBehavior
from pydantic_ai.messages import ModelResponse
from pydantic_ai.models import ModelRequestContext
from pydantic_ai.models.anthropic import AnthropicModel, AnthropicModelSettings
from pydantic_ai.providers.anthropic import AnthropicProvider

from bakeoff.contract import InvalidReport, TriageReport
from bakeoff.prompt import SYSTEM_PROMPT, user_prompt
from bakeoff.settings import SETTINGS
from bakeoff.telemetry import record_model_request, record_usage
from bakeoff.tools import TOOLS

# Running out of tool retries raises the same exception class, so only the message tells a report
# that failed validation apart.
OUTPUT_RETRIES_EXCEEDED = "Exceeded maximum output retries"


async def _count_request(
    _ctx: RunContext[None], request: ModelRequestContext
) -> ModelRequestContext:
    # Async, so PydanticAI calls it on the event loop instead of handing it to a worker thread.
    record_model_request()
    return request


async def _count_usage(
    _ctx: RunContext[None], *, request_context: ModelRequestContext, response: ModelResponse
) -> ModelResponse:
    # Recorded as each reply arrives rather than when the run ends, so a run abandoned at its
    # timeout still reports what it spent. The reply's usage is what the run is billed: this
    # agent has no fallback model and no paused turns, the two cases where they differ.
    record_usage(response.usage.input_tokens, response.usage.output_tokens)
    return response


agent = Agent(
    AnthropicModel(
        SETTINGS.model,
        provider=AnthropicProvider(api_key=SETTINGS.api_key()),
    ),
    output_type=TriageReport,
    instructions=SYSTEM_PROMPT,
    tools=TOOLS,
    model_settings=AnthropicModelSettings(anthropic_effort=SETTINGS.effort),
    capabilities=[Hooks(before_model_request=_count_request, after_model_request=_count_usage)],
)


def triage(repo: str) -> TriageReport:
    """Triage ``repo``; the caller wraps the run in ``telemetry.collect()``."""
    try:
        return agent.run_sync(user_prompt(repo)).output
    except UnexpectedModelBehavior as error:
        if error.message.startswith(OUTPUT_RETRIES_EXCEEDED):
            raise InvalidReport(error.message) from error
        raise
