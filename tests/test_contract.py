from contextlib import nullcontext

import pytest
from pydantic import ValidationError

from bakeoff.contract import (
    DuplicatePair,
    IncompleteReport,
    InvalidReport,
    LabelSuggestion,
    Theme,
    TopIssue,
    TriageReport,
    parse_final_reply,
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


@pytest.mark.parametrize(
    ("b", "expected"),
    [(8, nullcontext()), (7, pytest.raises(ValidationError, match="two different issues"))],
)
def test_duplicate_pair_rejects_an_issue_paired_with_itself(b, expected):
    with expected:
        DuplicatePair(a=7, b=b, reason="same crash")


@pytest.mark.parametrize(
    ("second", "expected"),
    [(8, nullcontext()), (7, pytest.raises(ValidationError, match="repeated issue numbers"))],
)
def test_report_rejects_two_label_suggestions_for_one_issue(second, expected):
    suggestions = [LabelSuggestion(number=7, labels=[]), LabelSuggestion(number=second, labels=[])]
    with expected:
        TriageReport(themes=[], duplicates=[], top_issues=[], suggested_labels=suggestions)


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


@pytest.mark.parametrize(
    ("stop_reason", "expected"),
    [("end_turn", nullcontext()), ("max_tokens", pytest.raises(IncompleteReport))],
)
def test_parse_final_reply_raises_incomplete_report_for_a_reply_that_stopped_early(
    stop_reason, expected
):
    report = TriageReport(themes=[], duplicates=[], top_issues=[], suggested_labels=[])
    # A reply cut off mid-report is rarely valid JSON, but it is incomplete, not invalid.
    with expected:
        assert parse_final_reply(report.model_dump_json(), stop_reason) == report
