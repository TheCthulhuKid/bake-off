"""Runs an implementation on a recorded repo or an eval case and collects its stats."""

import time
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel

from bakeoff.cases import Case
from bakeoff.contract import InvalidReport, TriageReport
from bakeoff.fixtures import load_repo
from bakeoff.impls import get_triage
from bakeoff.scoring import Scores, score_run
from bakeoff.settings import SETTINGS
from bakeoff.telemetry import RunStats, collect


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


def run_case(
    impl: str, case: Case, repeat: int, clock: Callable[[], float] = time.monotonic
) -> RunRecord:
    """Run ``impl`` once on ``case`` and score the report.

    A run that raises is recorded as failed with its error, so one run never stops an eval. An
    unknown repo or impl still raises, before any model is called.
    """
    repo = load_repo(case.repo)
    triage = get_triage(impl)
    report = error = schema_valid = None
    start = clock()
    with collect() as stats:
        try:
            report = triage(case.repo)
            schema_valid = True
        except InvalidReport as exc:
            error, schema_valid = _describe(exc), False
        except Exception as exc:
            error = _describe(exc)
    latency = clock() - start
    issues = {issue.number for issue in repo.issues}
    return RunRecord(
        case=case.name,
        repeat=repeat,
        report=report,
        error=error,
        schema_valid=schema_valid,
        stats=stats,
        latency_seconds=latency,
        # Priced now: Settings.cost prices the current model, which a later report can't know.
        cost_usd=SETTINGS.cost(stats.input_tokens, stats.output_tokens),
        scores=Scores() if report is None else score_run(report, case, issues),
    )


def _describe(error: Exception) -> str:
    return f"{type(error).__name__}: {error}"


def result_path(out: Path, impl: str) -> Path:
    """``out`` itself if it names a ``.json`` file, else ``<UTC timestamp>-<impl>.json`` in it."""
    if out.suffix == ".json":
        return out
    return out / f"{datetime.now(UTC):%Y%m%dT%H%M%SZ}-{impl}.json"
