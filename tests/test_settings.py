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
    unknown = Settings(model="unknown", _env_file=None)
    assert unknown.cost(10, 10) == 0.0
    with pytest.raises(ValueError):
        unknown.max_output_tokens()


@pytest.mark.parametrize(
    "limit", ["max_tool_calls", "max_model_requests", "run_timeout", "body_limit", "page_size"]
)
def test_settings_reject_a_limit_that_is_not_positive(limit):
    assert getattr(Settings(**{limit: 1}, _env_file=None), limit) == 1
    with pytest.raises(ValidationError):
        Settings(**{limit: 0}, _env_file=None)
