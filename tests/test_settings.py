import pytest

from bakeoff.settings import Settings


def test_settings_read_env_and_price_runs(monkeypatch):
    monkeypatch.setenv("BAKEOFF_MODEL", "claude-sonnet-5-5")
    monkeypatch.setenv("BAKEOFF_MAX_TOOL_CALLS", "5")
    monkeypatch.setenv("GITHUB_TOKEN", "tok")
    # No .env, so a developer's local file cannot leak into the test.
    settings = Settings(_env_file=None)
    assert settings.model == "claude-sonnet-5-5"
    assert settings.max_tool_calls == 5
    assert settings.github_token.get_secret_value() == "tok"
    assert settings.cost(1_000_000, 100_000) == pytest.approx(3.0)
    unknown = Settings(model="unknown", _env_file=None)
    assert unknown.cost(10, 10) == 0.0
    with pytest.raises(ValueError):
        unknown.max_output_tokens()
