import re
from datetime import UTC, datetime

import pytest

from bakeoff.report import IncompatibleRuns, combine, render
from bakeoff.runner import EvalRun, RunRecord
from bakeoff.scoring import Scores
from bakeoff.telemetry import RunStats


def _run(case: str, theme_score: int, timeout: float = 900, **changes) -> EvalRun:
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


@pytest.mark.parametrize(
    ("case", "changes", "refused"),
    [
        ("tiny-later", {}, None),
        ("tiny-later", {"prompt_hash": "0123456789ab"}, "anthropic: files differ in prompt_hash"),
        ("tiny-later", {"fixture_hashes": {"tiny": "0123456789ab"}}, "different versions of tiny"),
        ("tiny-later", {"timeout": 60}, "anthropic: files differ in run limits"),
        ("tiny-first", {}, "cases in more than one file: ['tiny-first']"),
    ],
)
def test_report_combines_an_impl_s_files_and_refuses_mismatched_ones(case, changes, refused):
    runs = [_run("tiny-first", 3), _run(case, 4, **changes)]
    if refused:
        with pytest.raises(IncompatibleRuns, match=re.escape(refused)):
            combine(runs)
        return
    [combined] = combine(runs)
    assert [record.case for record in combined.records] == ["tiny-first", "tiny-later"]
    tables = render(runs)
    # Each file keeps its provenance row; the scores share one row per impl.
    assert tables.count("| anthropic | 2026-11-16 10:24 |") == 2
    assert "| anthropic | 2 | 100% |" in tables
    assert "| 3.5 |" in tables
