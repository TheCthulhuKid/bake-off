"""Shared run settings. Every implementation reads these so differences come from the framework.

Variables are read from the environment and from a local ``.env`` (see ``.env.example``).
Run settings use the ``BAKEOFF_`` prefix; the two credentials keep their conventional names.
"""

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

# USD per million tokens, Anthropic first-party rates.
PRICES = {
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
}


class Settings(BaseSettings):
    model: str = "claude-opus-5-5"
    effort: str = "medium"
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
        if self.model not in PRICES:
            return 0.0
        per_input, per_output = PRICES[self.model]
        return (input_tokens * per_input + output_tokens * per_output) / 1_000_000


SETTINGS = Settings()
