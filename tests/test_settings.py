import os
import subprocess
import sys
from contextlib import nullcontext

import pytest
from pydantic import ValidationError

from bakeoff.settings import Settings


def test_settings_read_env_and_price_runs(monkeypatch):
    monkeypatch.setenv("BAKEOFF_MODEL", "claude-sonnet-5-5")
    monkeypatch.setenv("BAKEOFF_MAX_TOOL_CALLS", "5")
    monkeypatch.setenv("BAKEOFF_RUN_TIMEOUT", "0.5")
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    # No .env, so a developer's local file cannot leak into the test.
    settings = Settings(_env_file=None)
    assert settings.model == "claude-sonnet-5-5"
    assert (settings.max_tool_calls, settings.run_timeout) == (5, 0.5)
    assert settings.github_token.get_secret_value() == "tok"
    assert settings.cost(1_000_000, 100_000) == pytest.approx(3.0)


@pytest.mark.parametrize(
    ("model", "expected"),
    [("claude-haiku-5-5", nullcontext()), ("claude-new", pytest.raises(ValidationError))],
)
def test_settings_reject_a_model_with_no_prices(model, expected):
    with expected:
        Settings(model=model, _env_file=None)


def test_an_invalid_setting_stops_the_program_with_a_message():
    env = {**os.environ, "BAKEOFF_MODEL": "claude-new"}
    result = subprocess.run(
        [sys.executable, "-c", "import bakeoff.settings"], env=env, capture_output=True, text=True
    )
    assert result.returncode == 1 and "Traceback" not in result.stderr
    assert "'claude-new' is not in MODELS" in result.stderr


@pytest.mark.parametrize(
    "limit", ["max_tool_calls", "max_model_requests", "run_timeout", "body_limit", "page_size"]
)
def test_settings_reject_a_limit_that_is_not_positive(limit):
    assert getattr(Settings(**{limit: 1}, _env_file=None), limit) == 1
    with pytest.raises(ValidationError):
        Settings(**{limit: 0}, _env_file=None)
