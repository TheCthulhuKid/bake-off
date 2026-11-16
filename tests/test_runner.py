import shutil
import threading
from datetime import UTC, datetime

import pytest
from helpers import FIXTURES, StubClient

from bakeoff.cases import Case, Injection
from bakeoff.contract import DuplicatePair, InvalidReport, Theme, TopIssue, TriageReport
from bakeoff.fixtures import Repo, UnknownRepoError, save_fixture
from bakeoff.judge import Judgement, ThemeJudge, Verdict
from bakeoff.provenance import cases_hash, code_lines, fixture_hash, prompt_hash
from bakeoff.runner import (
    EvalInterrupted,
    RescoreError,
    check_cases,
    load_eval,
    rescore,
    result_path,
    run_case,
    run_eval,
    run_once,
    save_result,
    select_cases,
)
from bakeoff.scoring import Scores
from bakeoff.settings import SETTINGS
from bakeoff.telemetry import RunLimitExceeded, record_usage
from bakeoff.tools import list_issues

CASE = Case(name="tiny-top", repo="tiny", top_issues=[1])
REPORT = TriageReport(
    themes=[], duplicates=[], top_issues=[TopIssue(number=1, reason="r")], suggested_labels=[]
)


class StubJudge:
    """Scores every report 4 for $0.50 with a reason, or raises ``error`` if given."""

    def __init__(self, error: Exception | None = None):
        self.error = error

    def score(self, report, case, repo) -> Judgement:
        if self.error:
            raise self.error
        return Judgement(score=4, cost_usd=0.5, reason="Clear groupings.")


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
    assert record.judge_reason == "Clear groupings."
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
    late = []

    def triage(repo):
        release.wait(5)
        record_usage(100, 10)
        try:
            list_issues(repo)
        except RunLimitExceeded as error:
            late.append(str(error))
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
    # Its next tool call stops it, as its next model request would.
    assert late == ["run timeout of 0.05 s reached"]


def test_run_once_gives_up_on_a_run_past_its_timeout(triage_with, monkeypatch):
    monkeypatch.setattr(SETTINGS, "run_timeout", 0.05)
    release = threading.Event()
    triage_with(lambda repo: release.wait(5) and REPORT)
    with pytest.raises(RunLimitExceeded, match="run timeout of 0.05 s reached"):
        run_once("fake", "tiny")
    release.set()


def test_run_eval_interleaves_the_impls_and_saves_each_once(triage_with, tmp_path):
    triage_with(lambda repo: REPORT)
    cases = [CASE, Case(name="tiny-bare", repo="tiny")]
    seen = []
    started = datetime(2026, 11, 10, 9, 0, tzinfo=UTC)
    # Registered names, for their code size; triage_with still swaps in the fake triage.
    impls = ["anthropic", "langgraph"]

    def on_record(impl, record):
        seen.append((impl, record.case, record.repeat))

    runs = run_eval(impls, cases, repeats=2, on_record=on_record, now=lambda: started)
    # Every impl runs a case's repeat before the next repeat starts.
    assert seen == [
        ("anthropic", "tiny-top", 0),
        ("langgraph", "tiny-top", 0),
        ("anthropic", "tiny-top", 1),
        ("langgraph", "tiny-top", 1),
        ("anthropic", "tiny-bare", 0),
        ("langgraph", "tiny-bare", 0),
        ("anthropic", "tiny-bare", 1),
        ("langgraph", "tiny-bare", 1),
    ]
    assert [run.impl for run in runs] == impls
    run = runs[0]
    assert [(record.case, record.repeat) for record in run.records] == [
        ("tiny-top", 0),
        ("tiny-top", 1),
        ("tiny-bare", 0),
        ("tiny-bare", 1),
    ]
    assert (run.model, run.effort, run.started_at) == (SETTINGS.model, SETTINGS.effort, started)
    assert run.prompt_hash == prompt_hash()
    assert (run.cases_hash, run.fixture_hashes) == (
        cases_hash(cases),
        {"tiny": fixture_hash("tiny")},
    )
    assert (run.page_size, run.body_limit) == (SETTINGS.page_size, SETTINGS.body_limit)
    assert (run.code_lines, run.code_non_blank_lines) == code_lines("anthropic")
    assert runs[1].code_lines == code_lines("langgraph")[0]
    # A results file in a directory is named by the UTC time and the impl.
    named = result_path(tmp_path, "anthropic", now=lambda: started)
    assert named == tmp_path / "20261110T090000Z-anthropic.json"
    # The results file loads back as the same run, and is never overwritten.
    path = tmp_path / "results" / "run.json"
    save_result(run, path)
    assert load_eval(path) == run
    with pytest.raises(FileExistsError):
        save_result(run, path)


def test_run_eval_keeps_only_whole_cases_when_interrupted(triage_with, tmp_path, monkeypatch):
    # A second fixture, so the saved files can be seen to leave out the unfinished case's repo.
    for name in ("tiny", "other"):
        shutil.copytree(FIXTURES / "tiny", tmp_path / name)
    monkeypatch.setattr("bakeoff.fixtures.FIXTURE_ROOT", tmp_path)
    calls = []

    def triage(repo):
        calls.append(repo)
        # The second case's second run: its first run is dropped with it.
        if len(calls) == 4:
            raise KeyboardInterrupt
        return REPORT

    triage_with(triage)
    cases = [CASE, Case(name="other-bare", repo="other")]
    with pytest.raises(EvalInterrupted) as interrupted:
        run_eval(["anthropic", "langgraph"], cases, repeats=1)
    assert (interrupted.value.case, interrupted.value.dropped) == ("other-bare", 1)
    assert isinstance(interrupted.value.__cause__, KeyboardInterrupt)
    for run in interrupted.value.runs:
        assert [record.case for record in run.records] == ["tiny-top"]
        # The file describes the cases it holds, so it combines with a later run of the rest.
        assert (run.cases_hash, list(run.fixture_hashes)) == (cases_hash([CASE]), ["tiny"])


def test_check_cases_lists_each_case_that_does_not_fit_its_fixture(tiny_root):
    both = [Theme(name="Crashes", issues=[1]), Theme(name="Features", issues=[2])]
    injection = Injection(issue=2, forbidden_label="urgent")
    cases = [
        CASE,
        Case(name="fits", repo="tiny", themes=both, labels={2: ["enhancement"]}),
        Case(name="stray", repo="tiny", duplicates=[(1, 7)], labels={9: ["bug"]}),
        # tiny labels #1 "bug"; labels are compared regardless of case, as they are scored.
        Case(name="planted", repo="tiny", injection=Injection(issue=2, forbidden_label="Bug")),
        Case(name="full", repo="tiny", expect_empty=True),
        Case(name="lost", repo="missing"),
        Case(name="themed", repo="tiny", themes=[both[0], both[0]]),
        Case(name="relabelled", repo="tiny", labels={1: ["bug"]}),
        Case(name="ranked", repo="tiny", top_issues=[2], injection=injection),
    ]
    [stray, planted, full, lost, unthemed, twice, relabelled, ranked] = check_cases(cases)
    assert stray == "stray: issues not in tiny: [7, 9]"
    assert planted == "planted: forbidden label 'Bug' is already used in tiny"
    assert full == "full: expects an empty report, but tiny has 2 issues"
    assert lost.startswith("lost: no recorded repo 'missing'")
    assert (unthemed, twice) == (
        "themed: issues in no theme: [2]",
        "themed: issues in more than one theme: [1]",
    )
    assert relabelled == "relabelled: expected labels on issues tiny already labels: [1]"
    assert ranked == "ranked: injected issue #2 is an accepted top issue"


def test_select_cases_brings_a_recorded_repo_s_derived_cases(tmp_path, monkeypatch):
    monkeypatch.setattr("bakeoff.fixtures.FIXTURE_ROOT", tmp_path)
    tiny = Repo.model_validate_json((FIXTURES / "tiny" / "issues.json").read_text())
    fixtures = {
        "tiny": tiny,
        "tiny-slice": tiny.model_copy(update={"name": "tiny-slice", "synthetic": True}),
        "other": tiny.model_copy(update={"name": "other", "source": "example/other"}),
    }
    for repo in fixtures.values():
        save_fixture(repo)
    cases = [Case(name=name, repo=name) for name in fixtures]
    assert [case.name for case in select_cases(cases, ["tiny"])] == ["tiny", "tiny-slice"]
    assert [case.name for case in select_cases(cases, ["tiny-slice"])] == ["tiny-slice"]
    with pytest.raises(UnknownRepoError):
        select_cases(cases, ["missing"])


def test_rescore_updates_scores_from_current_labels_and_keeps_theme_scores(triage_with, tmp_path):
    themes = [Theme(name="Crashes", issues=[1])]
    report = TriageReport(
        themes=themes,
        duplicates=[DuplicatePair(a=1, b=2, reason="Same crash")],
        top_issues=[],
        suggested_labels=[],
    )
    triage_with(lambda repo: report)
    client = StubClient(Verdict(reason="Clear.", score=4))
    cache = tmp_path / "cache.json"
    case = Case(name="tiny-pair", repo="tiny", themes=themes, duplicates=[])
    [run] = run_eval(["anthropic"], [case], repeats=1, judge=ThemeJudge(client, cache))
    assert run.records[0].scores.duplicate_precision == 0.0
    # The pair is labelled after the run; a judge with no client can only read its cache.
    fixed = case.model_copy(update={"duplicates": [(1, 2)]})
    cache_only = ThemeJudge(None, cache)
    rescored = rescore(run, [fixed], cache_only)
    [record] = rescored.records
    assert (record.scores.duplicate_precision, record.scores.theme_score) == (1.0, 4)
    assert (record.report, record.stats) == (run.records[0].report, run.records[0].stats)
    assert rescored.cases_hash == cases_hash([fixed])
    # New themes would need the judge again, which a rescore never pays for.
    regrouped = fixed.model_copy(update={"themes": [Theme(name="All", issues=[1, 2])]})
    with pytest.raises(RescoreError, match="tiny-pair: no cached verdict"):
        rescore(run, [regrouped], cache_only)
    with pytest.raises(RescoreError, match="cases not in the cases file"):
        rescore(run, [], cache_only)
    stale = run.model_copy(update={"fixture_hashes": {"tiny": "0123456789ab"}})
    with pytest.raises(RescoreError, match=r"fixtures changed since the run: \['tiny'\]"):
        rescore(stale, [fixed], cache_only)
