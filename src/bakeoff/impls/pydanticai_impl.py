"""PydanticAI version: one agent with the shared tools and ``TriageReport`` as its output type."""

from pydantic_ai import Agent
from pydantic_ai.models.anthropic import AnthropicModel, AnthropicModelSettings
from pydantic_ai.providers.anthropic import AnthropicProvider
from pydantic_ai.usage import RunUsage

from bakeoff.contract import TriageReport
from bakeoff.prompt import SYSTEM_PROMPT, user_prompt
from bakeoff.settings import SETTINGS
from bakeoff.telemetry import record_usage
from bakeoff.tools import get_issue, list_issues, search_issues

_key = SETTINGS.anthropic_api_key
agent = Agent(
    AnthropicModel(
        SETTINGS.model,
        provider=AnthropicProvider(api_key=_key.get_secret_value() if _key else None),
    ),
    output_type=TriageReport,
    instructions=SYSTEM_PROMPT,
    tools=[list_issues, get_issue, search_issues],
    model_settings=AnthropicModelSettings(anthropic_effort=SETTINGS.effort),
)


def triage(repo: str) -> TriageReport:
    """Triage ``repo``; the caller wraps the run in ``telemetry.collect()``."""
    # Passed in rather than read from the result, so a run that raises still reports its cost.
    usage = RunUsage()
    try:
        return agent.run_sync(user_prompt(repo), usage=usage).output
    finally:
        record_usage(usage.input_tokens, usage.output_tokens)
