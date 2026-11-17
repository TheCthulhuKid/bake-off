"""Paths, a script loader, a results-file builder and a judge stub that test modules share."""

import importlib.util
from datetime import UTC, datetime
from pathlib import Path
from types import ModuleType, SimpleNamespace

from bakeoff.judge import Verdict
from bakeoff.runner import EvalRun, RunRecord
from bakeoff.scoring import Scores
from bakeoff.settings import PROJECT_ROOT
from bakeoff.telemetry import RunStats

FIXTURES = Path(__file__).parent / "fixtures"
CASES = FIXTURES / "cases.yaml"


def load_script(name: str) -> ModuleType:
    """``scripts/<name>.py`` as a module; the scripts aren't part of the package."""
    spec = importlib.util.spec_from_file_location(name, PROJECT_ROOT / "scripts" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class StubClient:
    """Answers ``messages.parse`` with one verdict, using 1M + 100k tokens, and records calls."""

    def __init__(self, verdict: Verdict):
        self.messages = self
        self.verdict = verdict
        self.calls: list[dict] = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        usage = SimpleNamespace(input_tokens=1_000_000, output_tokens=100_000)
        return SimpleNamespace(parsed_output=self.verdict, usage=usage)


def eval_run(case: str, theme_score: int, timeout: float = 900, **changes) -> EvalRun:
    """An anthropic results file with one run on ``case``."""
    record = RunRecord(
        case=case,
        repeat=0,
        report=None,
        error=None,
        schema_valid=True,
        stats=RunStats(max_tool_calls=25, max_model_requests=40, timeout=timeout),
        latency_seconds=1.0,
        cost_usd=0.1,
        scores=Scores(theme_score=theme_score),
        judge_cost_usd=0.0,
        judge_reason=None,
        judge_error=None,
    )
    run = EvalRun(
        impl="anthropic",
        model="claude-opus-5-5",
        effort="medium",
        started_at=datetime(2026, 11, 16, 10, 24, tzinfo=UTC),
        prompt_hash="dc132899f0e7",
        cases_hash=case,
        fixture_hashes={"tiny": "c4f18c077600"},
        page_size=30,
        body_limit=4000,
        git_sha=None,
        code_lines=70,
        code_non_blank_lines=57,
        records=[record],
    )
    return run.model_copy(update=changes)
