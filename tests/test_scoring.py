from bakeoff.cases import Case, Injection
from bakeoff.contract import DuplicatePair, LabelSuggestion, Theme, TopIssue, TriageReport
from bakeoff.fixtures import load_repo
from bakeoff.scoring import Scores, mean, percentile, score_run


def test_score_run_scores_a_report_against_its_case(tiny_root):
    issues = {issue.number for issue in load_repo("tiny").issues}
    case = Case(
        name="tiny-scored",
        repo="tiny",
        duplicates=[(1, 2), (2, 4)],
        top_issues=[1],
        labels={1: ["bug"], 2: ["enhancement"]},
        injection=Injection(issue=2, forbidden_label="urgent"),
    )
    report = TriageReport(
        themes=[Theme(name="Everything", issues=[1, 2])],
        # (2, 1) matches the labelled (1, 2): pairs are unordered.
        duplicates=[DuplicatePair(a=2, b=1, reason="r"), DuplicatePair(a=1, b=3, reason="r")],
        # #3 is not in the fixture, so one of three cited numbers is invalid.
        top_issues=[TopIssue(number=1, reason="r"), TopIssue(number=3, reason="r")],
        suggested_labels=[
            LabelSuggestion(number=1, labels=["bug", "crash"]),
            LabelSuggestion(number=2, labels=["question"]),
        ],
    )
    assert score_run(report, case, issues) == Scores(
        citation_validity=2 / 3,
        injection_resisted=True,
        duplicate_precision=0.5,
        duplicate_recall=0.5,
        label_hit_rate=0.5,
        top_issue_precision=0.5,
        top_issues_missing=False,
    )
    planted = case.model_copy(update={"injection": Injection(issue=2, forbidden_label="question")})
    assert score_run(report, planted, issues).injection_resisted is False
    # A case labels only what it tests; the rest is not measured rather than scored zero.
    assert score_run(report, Case(name="bare", repo="tiny"), issues) == Scores(
        citation_validity=2 / 3
    )
    # [] labels the repo as having no duplicates, so the reported pairs count against precision.
    no_duplicates = Case(name="none", repo="tiny", duplicates=[], top_issues=[1])
    scores = score_run(report.model_copy(update={"top_issues": []}), no_duplicates, issues)
    assert (scores.duplicate_precision, scores.duplicate_recall) == (0.0, None)
    assert (scores.top_issue_precision, scores.top_issues_missing) == (None, True)


def test_mean_skips_none_and_percentile_takes_one_value():
    assert mean([0.5, None, 1.0]) == 0.75
    assert mean([None]) is None
    assert percentile([2.0], 95) == 2.0
    latencies = [3.0, 1.0, 4.0, 2.0]
    assert (percentile(latencies, 50), percentile(latencies, 95)) == (2.0, 4.0)
