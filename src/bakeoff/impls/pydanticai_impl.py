"""PydanticAI version: one agent with the shared tools and ``TriageReport`` as its output type."""

from pydantic_ai import Agent, RunContext
from pydantic_ai.capabilities import Hooks
from pydantic_ai.models import ModelRequestContext
from pydantic_ai.models.anthropic import AnthropicModel, AnthropicModelSettings
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.usage import RunUsage

from bakeoff.contract import TriageReport
from bakeoff.prompt import SYSTEM_PROMPT, user_prompt
from bakeoff.settings import SETTINGS
from bakeoff.telemetry import record_model_request, record_usage
from bakeoff.tools import TOOLS


async def _count_request(
    _ctx: RunContext[None], request: ModelRequestContext
) -> ModelRequestContext:
    # Async, so PydanticAI calls it on the event loop instead of handing it to a worker thread.
    record_model_request()
    return request


agent = Agent(
    AnthropicModel(
        SETTINGS.model,
        provider=AnthropicProvider(api_key=SETTINGS.api_key()),
    ),
    output_type=TriageReport,
    instructions=SYSTEM_PROMPT,
    tools=TOOLS,
    model_settings=AnthropicModelSettings(anthropic_effort=SETTINGS.effort),
    capabilities=[Hooks(before_model_request=_count_request)],
)


def triage(repo: str) -> TriageReport:
    """Triage ``repo``; the caller wraps the run in ``telemetry.collect()``."""
    # Passed in rather than read from the result, so a run that raises still reports its cost.
    usage = RunUsage()
    try:
        return agent.run_sync(user_prompt(repo), usage=usage).output
    finally:
        record_usage(usage.input_tokens, usage.output_tokens)
