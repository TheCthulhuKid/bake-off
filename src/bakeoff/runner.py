"""Runs an implementation on a recorded repo and collects its stats."""

from pydantic import BaseModel

from bakeoff.contract import TriageReport
from bakeoff.fixtures import load_repo
from bakeoff.impls import get_triage
from bakeoff.telemetry import RunStats, collect


class RunResult(BaseModel):
    impl: str
    repo: str
    report: TriageReport
    stats: RunStats


def run_once(impl: str, repo: str) -> RunResult:
    """Run ``impl`` on ``repo`` once; an unknown name raises before any model is called."""
    # The repo first: it is the cheap check, and importing a framework can fail on a missing key.
    load_repo(repo)
    triage = get_triage(impl)
    with collect() as stats:
        report = triage(repo)
    return RunResult(impl=impl, repo=repo, report=report, stats=stats)
