import pytest
from pydantic import ValidationError

from bakeoff.contract import DuplicatePair, LabelSuggestion, Theme, TopIssue, TriageReport


def test_report_round_trips_and_cites_every_number():
    report = TriageReport(
        themes=[Theme(name="Login", issues=[1, 2])],
        duplicates=[DuplicatePair(a=2, b=3, reason="same stack trace")],
        top_issues=[TopIssue(number=4, reason="crash on start")],
        suggested_labels=[LabelSuggestion(number=5, labels=["bug"])],
    )
    assert TriageReport.model_validate_json(report.model_dump_json()) == report
    assert report.cited_issues() == {1, 2, 3, 4, 5}


def test_report_rejects_too_many_top_issues_self_pairs_and_repeated_labels():
    with pytest.raises(ValidationError):
        TriageReport(
            themes=[],
            duplicates=[],
            top_issues=[TopIssue(number=n, reason="x") for n in range(6)],
            suggested_labels=[],
        )
    with pytest.raises(ValidationError):
        DuplicatePair(a=7, b=7, reason="same issue")
    with pytest.raises(ValidationError):
        TriageReport(
            themes=[],
            duplicates=[],
            top_issues=[],
            suggested_labels=[LabelSuggestion(number=7, labels=[])] * 2,
        )
