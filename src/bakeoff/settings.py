"""Shared run settings. Every implementation reads these so differences come from the framework.

Variables are read from the environment and from ``.env`` at the project root (see
``.env.example``). Run settings use the ``BAKEOFF_`` prefix; the two credentials keep their
conventional names.
"""

from pathlib import Path
from typing import Literal, NamedTuple

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# The checkout root, so .env and the fixtures are found from any working directory. This needs a
# source checkout or editable install, as `uv sync` gives.
PROJECT_ROOT = Path(__file__).resolve().parents[2]


class ModelSpec(NamedTuple):
    # USD per million tokens, Anthropic first-party rates.
    input_price: float
    output_price: float
    # The maximum output PydanticAI and LangChain send as max_tokens when none is set.
    max_output_tokens: int


MODELS = {
    "claude-opus-5-5": ModelSpec(4.0, 20.0, 128_000),
    "claude-sonnet-5-5": ModelSpec(2.0, 10.0, 128_000),
    "claude-haiku-5-5": ModelSpec(0.10, 0.50, 128_000),
}


class Settings(BaseSettings):
    model: str = "claude-opus-5-5"
    effort: Literal["low", "medium", "high", "xhigh", "max"] = "medium"
    # Positive, since a limit of 0 fires on the first call and a page size of 0 can't page.
    max_tool_calls: int = Field(default=25, gt=0)
    max_model_requests: int = Field(default=40, gt=0)
    # Seconds. A guess: the smoke runs didn't record latency, so check it against the first evals.
    run_timeout: float = Field(default=900, gt=0)
    body_limit: int = Field(default=4000, gt=0)
    page_size: int = Field(default=30, gt=0)
    anthropic_api_key: SecretStr | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
    github_token: SecretStr | None = Field(default=None, validation_alias="GITHUB_TOKEN")

    model_config = SettingsConfigDict(
        env_prefix="BAKEOFF_", env_file=PROJECT_ROOT / ".env", extra="ignore", validate_by_name=True
    )

    def api_key(self) -> str | None:
        """The Anthropic API key as plain text, for clients that take a string."""
        return self.anthropic_api_key.get_secret_value() if self.anthropic_api_key else None

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        """Price of a run in USD; zero for a model not in the table rather than a guess."""
        if self.model not in MODELS:
            return 0.0
        spec = MODELS[self.model]
        return (input_tokens * spec.input_price + output_tokens * spec.output_price) / 1_000_000

    def max_output_tokens(self) -> int:
        """The model's maximum output, for a client that needs ``max_tokens`` set explicitly.

        Raises ``ValueError`` for a model not in ``MODELS`` rather than guessing a limit the
        other frameworks would not send.
        """
        if self.model not in MODELS:
            raise ValueError(f"no maximum output known for {self.model!r}; add it to MODELS")
        return MODELS[self.model].max_output_tokens


SETTINGS = Settings()
