"""Runs an implementation on a recorded repo or an eval case and collects its stats."""

import contextvars
import functools
import threading
import time
from collections.abc import Callable, Iterable
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from bakeoff.cases import Case
from bakeoff.contract import InvalidReport, TriageReport
from bakeoff.fixtures import Repo, load_repo
from bakeoff.impls import get_triage
from bakeoff.judge import Judgement, ThemeJudge
from bakeoff.scoring import Scores, score_run
from bakeoff.settings import SETTINGS
from bakeoff.telemetry import RunStats, collect, raise_if_limit_fired


class RunResult(BaseModel):
    impl: str
    repo: str
    report: TriageReport
    stats: RunStats


def run_once(impl: str, repo: str) -> RunResult:
    """Run ``impl`` on ``repo`` once; an unknown repo or impl raises before any model is called."""
    # The repo first: it is the cheap check, and importing a framework can fail on a missing key.
    load_repo(repo)
    triage = get_triage(impl)
    with collect() as stats:
        report = triage(repo)
    return RunResult(impl=impl, repo=repo, report=report, stats=stats)


class RunRecord(BaseModel):
    case: str
    repeat: int
    report: TriageReport | None
    error: str | None
    # True when a report came back, False when it failed validation, None when the run failed
    # for another reason, such as a run limit, which says nothing about the schema.
    schema_valid: bool | None
    stats: RunStats
    latency_seconds: float
    cost_usd: float
    scores: Scores
    # The judge's spend on this run's themes, apart from the run's own cost; 0 when not judged.
    judge_cost_usd: float
    judge_error: str | None


def run_case(
    impl: str,
    case: Case,
    repeat: int,
    *,
    judge: ThemeJudge | None = None,
    clock: Callable[[], float] = time.monotonic,
) -> RunRecord:
    """Run ``impl`` once on ``case`` and score the report, its themes by ``judge`` if given.

    A run that raises, or runs past its timeout, is recorded as failed with its error, so one run
    never stops an eval; so is a judge that fails, which leaves the other scores standing. An
    unknown repo or impl still raises, before any model is called.
    """
    repo = load_repo(case.repo)
    triage = get_triage(impl)
    report = error = schema_valid = None
    start = clock()
    with collect() as stats:
        try:
            report = _triage_within_timeout(triage, case.repo, stats)
            schema_valid = True
        except InvalidReport as exc:
            error, schema_valid = _describe(exc), False
        except Exception as exc:
            error = _describe(exc)
    latency = clock() - start
    issues = {issue.number for issue in repo.issues}
    scores = Scores() if report is None else score_run(report, case, issues)
    judgement, judge_error = _judge_themes(judge, report, case, repo)
    scores.theme_score = judgement.score
    return RunRecord(
        case=case.name,
        repeat=repeat,
        report=report,
        error=error,
        schema_valid=schema_valid,
        # A copy: a run abandoned at its timeout still updates the original in the background.
        stats=stats.model_copy(),
        latency_seconds=latency,
        # Priced now: Settings.cost prices the current model, which a later report can't know.
        cost_usd=SETTINGS.cost(stats.input_tokens, stats.output_tokens),
        scores=scores,
        judge_cost_usd=judgement.cost_usd,
        judge_error=judge_error,
    )


class EvalRun(BaseModel):
    """One implementation's runs over the eval cases, as saved to one results file."""

    impl: str
    model: str
    effort: str
    started_at: datetime
    records: list[RunRecord]


def run_eval(
    impl: str,
    cases: Iterable[Case],
    repeats: int,
    *,
    judge: ThemeJudge | None = None,
    on_record: Callable[[RunRecord], None] = lambda record: None,
    now: Callable[[], datetime] = functools.partial(datetime.now, UTC),
) -> EvalRun:
    """Run ``impl`` ``repeats`` times on each case in turn, judging themes if ``judge`` is given.

    ``on_record`` sees each record as it is made, so the CLI can show progress without owning
    the loop.
    """
    started_at = now()
    records = []
    for case in cases:
        for repeat in range(repeats):
            record = run_case(impl, case, repeat, judge=judge)
            on_record(record)
            records.append(record)
    return EvalRun(
        impl=impl,
        model=SETTINGS.model,
        effort=SETTINGS.effort,
        started_at=started_at,
        records=records,
    )


def _judge_themes(
    judge: ThemeJudge | None, report: TriageReport | None, case: Case, repo: Repo
) -> tuple[Judgement, str | None]:
    """The judge's verdict on the report's themes, and the judge's error if it failed."""
    if judge is None or report is None:
        return Judgement(score=None, cost_usd=0.0), None
    try:
        return judge.score(report, case, repo), None
    except Exception as exc:
        return Judgement(score=None, cost_usd=0.0), _describe(exc)


def _triage_within_timeout(
    triage: Callable[[str], TriageReport], repo: str, stats: RunStats
) -> TriageReport:
    """Run ``triage(repo)`` on a daemon thread, giving up after ``stats.timeout`` seconds.

    The run's own deadline is only checked between model requests, so this is what ends a run
    stuck in a hung request. A daemon thread rather than a ThreadPoolExecutor, whose threads are
    joined at exit, so one hung request can't stop the process from exiting. The thread runs in
    a copy of this context, or the run's collector would be invisible to the impl and tools.
    """
    context = contextvars.copy_context()
    outcome: dict[str, TriageReport | BaseException] = {}

    def run() -> None:
        try:
            outcome["report"] = context.run(triage, repo)
        except BaseException as error:
            outcome["error"] = error

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    thread.join(stats.timeout)
    if thread.is_alive():
        # Also stops the abandoned run at its next limit check.
        stats.limit_fired = "timeout"
        raise_if_limit_fired()
    if "error" in outcome:
        raise outcome["error"]
    return outcome["report"]


def _describe(error: Exception) -> str:
    return f"{type(error).__name__}: {error}"


def result_path(out: Path, impl: str) -> Path:
    """``out`` itself if it names a ``.json`` file, else ``<UTC timestamp>-<impl>.json`` in it."""
    if out.suffix == ".json":
        return out
    return out / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{impl}.json"
