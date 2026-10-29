"""Shared run settings. Every implementation reads these so differences come from the framework."""

import os
from dataclasses import dataclass

# USD per million tokens, Anthropic first-party rates.
PRICES = {
    "claude-opus-5-5": (4.0, 20.0),
    "claude-sonnet-5-5": (2.0, 10.0),
    "claude-haiku-5-5": (0.10, 0.50),
}


@dataclass(frozen=True)
class Settings:
    model: str = "claude-opus-5-5"
    effort: str = "medium"
    max_tool_calls: int = 25
    body_limit: int = 4000
    page_size: int = 30

    @classmethod
    def from_env(cls) -> "Settings":
        defaults = cls()
        return cls(
            model=os.environ.get("BAKEOFF_MODEL", defaults.model),
            effort=os.environ.get("BAKEOFF_EFFORT", defaults.effort),
            max_tool_calls=int(os.environ.get("BAKEOFF_MAX_TOOL_CALLS", defaults.max_tool_calls)),
            body_limit=int(os.environ.get("BAKEOFF_BODY_LIMIT", defaults.body_limit)),
            page_size=int(os.environ.get("BAKEOFF_PAGE_SIZE", defaults.page_size)),
        )

    def cost(self, input_tokens: int, output_tokens: int) -> float:
        """Price of a run in USD; zero for a model not in the table rather than a guess."""
        if self.model not in PRICES:
            return 0.0
        per_input, per_output = PRICES[self.model]
        return (input_tokens * per_input + output_tokens * per_output) / 1_000_000


SETTINGS = Settings.from_env()
