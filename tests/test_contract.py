from contextlib import nullcontext

import pytest
from pydantic import ValidationError

from bakeoff.contract import (
    DuplicatePair,
    InvalidReport,
    LabelSuggestion,
    Theme,
    TopIssue,
    TriageReport,
    parse_report,
)


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


@pytest.mark.parametrize(
    ("top_issues", "expected"), [(5, nullcontext()), (6, pytest.raises(InvalidReport))]
)
def test_parse_report_raises_invalid_report_for_a_report_that_fails_validation(
    top_issues, expected
):
    # model_construct skips validation, so it can build the invalid report a model might send.
    report = TriageReport.model_construct(
        themes=[],
        duplicates=[],
        top_issues=[TopIssue(number=n, reason="r") for n in range(top_issues)],
        suggested_labels=[],
    )
    with expected:
        assert parse_report(report.model_dump_json()) == report
