import pytest
from pydantic import ValidationError

from bakeoff.contract import DuplicatePair, Theme, TopIssue, TriageReport
from bakeoff.settings import Settings


def test_report_round_trips_and_cites_every_number():
    report = TriageReport(
        themes=[Theme(name="Login", issues=[1, 2])],
        duplicates=[DuplicatePair(a=2, b=3, reason="same stack trace")],
        top_issues=[TopIssue(number=4, reason="crash on start")],
        suggested_labels={5: ["bug"]},
    )
    assert TriageReport.model_validate_json(report.model_dump_json()) == report
    assert report.cited_issues() == {1, 2, 3, 4, 5}


def test_report_rejects_too_many_top_issues_and_self_pairs():
    with pytest.raises(ValidationError):
        TriageReport(
            themes=[],
            duplicates=[],
            top_issues=[TopIssue(number=n, reason="x") for n in range(6)],
            suggested_labels={},
        )
    with pytest.raises(ValidationError):
        DuplicatePair(a=7, b=7, reason="same issue")


def test_settings_read_env_and_price_runs(monkeypatch):
    monkeypatch.setenv("BAKEOFF_MODEL", "claude-sonnet-5-5")
    monkeypatch.setenv("BAKEOFF_MAX_TOOL_CALLS", "5")
    settings = Settings.from_env()
    assert settings.model == "claude-sonnet-5-5"
    assert settings.max_tool_calls == 5
    assert settings.cost(1_000_000, 100_000) == pytest.approx(3.0)
    assert Settings(model="unknown").cost(10, 10) == 0.0
