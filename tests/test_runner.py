import threading
from datetime import UTC, datetime

import pytest

from bakeoff.cases import Case
from bakeoff.contract import InvalidReport, TopIssue, TriageReport
from bakeoff.judge import Judgement
from bakeoff.provenance import code_lines, prompt_hash
from bakeoff.runner import load_eval, run_case, run_eval, save_eval
from bakeoff.scoring import Scores
from bakeoff.settings import SETTINGS
from bakeoff.telemetry import record_usage

CASE = Case(name="tiny-top", repo="tiny", top_issues=[1])
REPORT = TriageReport(
    themes=[], duplicates=[], top_issues=[TopIssue(number=1, reason="r")], suggested_labels=[]
)


class StubJudge:
    """Scores every report 4 for $0.50, or raises ``error`` if given."""

    def __init__(self, error: Exception | None = None):
        self.error = error

    def score(self, report, case, repo) -> Judgement:
        if self.error:
            raise self.error
        return Judgement(score=4, cost_usd=0.5)


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
    clock = iter([10.0, 12.5]).__next__
    record = run_case("fake", CASE, repeat=2, judge=StubJudge(), clock=clock)
    assert (record.case, record.repeat, record.report) == ("tiny-top", 2, REPORT)
    assert record.schema_valid and record.error is None
    assert (record.scores.top_issue_precision, record.scores.theme_score) == (1.0, 4)
    assert (record.latency_seconds, record.cost_usd) == (2.5, pytest.approx(3.0))
    # The judge's spend is kept apart from the run's own cost.
    assert (record.judge_cost_usd, record.judge_error) == (0.5, None)
    # A judge that fails leaves the run and its other scores standing.
    failed = run_case("fake", CASE, repeat=3, judge=StubJudge(RuntimeError("judge down")))
    assert (failed.schema_valid, failed.scores.top_issue_precision) == (True, 1.0)
    assert (failed.scores.theme_score, failed.judge_error) == (None, "RuntimeError: judge down")


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


def test_run_eval_runs_every_case_and_repeat_and_saves_once(triage_with, tmp_path):
    triage_with(lambda repo: REPORT)
    cases = [CASE, Case(name="tiny-bare", repo="tiny")]
    seen = []
    started = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)
    # A registered name, for its code size; triage_with still swaps in the fake triage.
    run = run_eval("anthropic", cases, repeats=2, on_record=seen.append, now=lambda: started)
    assert [(record.case, record.repeat) for record in run.records] == [
        ("tiny-top", 0),
        ("tiny-top", 1),
        ("tiny-bare", 0),
        ("tiny-bare", 1),
    ]
    assert seen == run.records
    assert (run.impl, run.model, run.effort) == ("anthropic", SETTINGS.model, SETTINGS.effort)
    assert run.started_at == started
    assert run.prompt_hash == prompt_hash()
    assert (run.code_lines, run.code_non_blank_lines) == code_lines("anthropic")
    # The results file loads back as the same run, and is never overwritten.
    path = tmp_path / "results" / "run.json"
    save_eval(run, path)
    assert load_eval(path) == run
    with pytest.raises(FileExistsError):
        save_eval(run, path)
