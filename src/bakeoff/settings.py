"""Shared run settings. Every implementation reads these so differences come from the framework.

Variables are read from the environment and from a local ``.env`` (see ``.env.example``).
Run settings use the ``BAKEOFF_`` prefix; the two credentials keep their conventional names.
"""

from typing import Literal, NamedTuple

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


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
    max_tool_calls: int = 25
    body_limit: int = 4000
    page_size: int = 30
    anthropic_api_key: SecretStr | None = Field(default=None, validation_alias="ANTHROPIC_API_KEY")
    github_token: SecretStr | None = Field(default=None, validation_alias="GITHUB_TOKEN")

    model_config = SettingsConfigDict(
        env_prefix="BAKEOFF_", env_file=".env", extra="ignore", validate_by_name=True
    )

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
