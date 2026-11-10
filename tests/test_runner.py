import threading

import pytest

from bakeoff.cases import Case
from bakeoff.contract import InvalidReport, TopIssue, TriageReport
from bakeoff.runner import run_case
from bakeoff.scoring import Scores
from bakeoff.settings import SETTINGS
from bakeoff.telemetry import record_usage

CASE = Case(name="tiny-top", repo="tiny", top_issues=[1])
REPORT = TriageReport(
    themes=[], duplicates=[], top_issues=[TopIssue(number=1, reason="r")], suggested_labels=[]
)


@pytest.fixture
def triage_with(tiny_root, monkeypatch):
    """Make ``run_case`` run the given function as every implementation's ``triage``."""

    def use(triage):
        monkeypatch.setattr("bakeoff.runner.get_triage", lambda impl: triage)

    return use


def test_run_case_records_the_report_scores_and_cost(triage_with, monkeypatch):
    monkeypatch.setattr(SETTINGS, "model", "claude-sonnet-5-5")

    def triage(repo):
        # triage runs on the timeout thread, so a cost here also shows the collector reaches it.
        record_usage(1_000_000, 100_000)
        return REPORT

    triage_with(triage)
    record = run_case("fake", CASE, repeat=2, clock=iter([10.0, 12.5]).__next__)
    assert (record.case, record.repeat, record.report) == ("tiny-top", 2, REPORT)
    assert record.schema_valid and record.error is None
    assert record.scores.top_issue_precision == 1.0
    assert (record.latency_seconds, record.cost_usd) == (2.5, pytest.approx(3.0))


# Only an invalid report counts against schema validity; any other failure leaves it unmeasured.
@pytest.mark.parametrize(
    ("failure", "schema_valid"), [(RuntimeError("boom"), None), (InvalidReport("boom"), False)]
)
def test_run_case_records_a_failed_run_and_whether_its_schema_failed(
    triage_with, failure, schema_valid
):
    def triage(repo):
        record_usage(100, 10)
        raise failure

    triage_with(triage)
    record = run_case("fake", CASE, repeat=0)
    assert (record.report, record.schema_valid) == (None, schema_valid)
    assert record.error == f"{type(failure).__name__}: boom"
    assert record.scores == Scores()
    # The tokens spent before the failure still count towards cost.
    assert record.stats.input_tokens == 100 and record.cost_usd > 0


def test_run_case_gives_up_on_a_run_past_its_timeout(triage_with, monkeypatch):
    monkeypatch.setattr(SETTINGS, "run_timeout", 0.05)
    release, done = threading.Event(), threading.Event()

    def triage(repo):
        release.wait(5)
        record_usage(100, 10)
        done.set()
        return REPORT

    triage_with(triage)
    record = run_case("fake", CASE, repeat=0)
    assert (record.report, record.schema_valid) == (None, None)
    assert record.error == "RunLimitExceeded: run timeout of 0.05 s reached"
    assert record.stats.limit_fired == "timeout"
    # The abandoned run carries on in the background; the record keeps the stats it had.
    release.set()
    assert done.wait(5)
    assert record.stats.input_tokens == 0
