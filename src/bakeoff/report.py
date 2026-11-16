"""Summarises saved eval runs into the comparison tables, from the results files alone."""

from collections.abc import Sequence

from pydantic import BaseModel

from bakeoff.runner import EvalRun
from bakeoff.scoring import mean, percentile

# What a run's scores depend on besides its cases, so an impl's files must agree on all of it to
# share a row. Code size stands in for the impl's code being unchanged.
SAME_FOR_AN_IMPL = (
    "model",
    "effort",
    "prompt_hash",
    "page_size",
    "body_limit",
    "code_lines",
    "code_non_blank_lines",
)


class IncompatibleRuns(ValueError):
    """Raised when an implementation's results files can't be reported as one eval."""


def combine(runs: Sequence[EvalRun]) -> list[EvalRun]:
    """One run per implementation, in the order first seen, holding all its files' records.

    So an eval run in parts reports like one. An impl's files must agree on ``SAME_FOR_AN_IMPL``,
    on their run limits and on the hash of any fixture they share, and no case may be in two of
    them; otherwise ``IncompatibleRuns`` names the impl and what differs.
    """
    by_impl: dict[str, list[EvalRun]] = {}
    for run in runs:
        by_impl.setdefault(run.impl, []).append(run)
    return [_merge(impl, group) for impl, group in by_impl.items()]


def _merge(impl: str, group: list[EvalRun]) -> EvalRun:
    first = group[0]
    for run in group[1:]:
        for field in SAME_FOR_AN_IMPL:
            if (theirs := getattr(run, field)) != (ours := getattr(first, field)):
                raise IncompatibleRuns(f"{impl}: files differ in {field}: {ours} and {theirs}")
    # The request cap and timeout aren't in the prompt, so only the records' stats carry them.
    limits = {
        (record.stats.max_tool_calls, record.stats.max_model_requests, record.stats.timeout)
        for run in group
        for record in run.records
    }
    if len(limits) > 1:
        raise IncompatibleRuns(
            f"{impl}: files differ in run limits (tool calls, requests, timeout): {sorted(limits)}"
        )
    fixtures: dict[str, str] = {}
    seen: set[str] = set()
    for run in group:
        for repo, digest in run.fixture_hashes.items():
            if fixtures.setdefault(repo, digest) != digest:
                raise IncompatibleRuns(f"{impl}: files hold different versions of {repo}")
        cases = {record.case for record in run.records}
        if twice := cases & seen:
            raise IncompatibleRuns(f"{impl}: cases in more than one file: {sorted(twice)}")
        seen |= cases
    records = [record for run in group for record in run.records]
    return first.model_copy(update={"fixture_hashes": fixtures, "records": records})


class Summary(BaseModel):
    """One implementation's eval as one row: a field per column, ``None`` for no data."""

    impl: str
    started_at: str
    model: str
    effort: str
    prompt_hash: str
    cases_hash: str
    git_sha: str | None
    runs: int
    failed_runs: int
    limit_runs: int
    timed_out_runs: int
    schema_validity: float | None
    citation_validity: float | None
    injection_resisted: float | None
    stayed_empty: float | None
    duplicate_precision: float | None
    duplicate_recall: float | None
    label_hit_rate: float | None
    top_issue_precision: float | None
    top_issues_missing_runs: int
    theme_score: float | None
    latency_p50: float | None
    latency_p95: float | None
    tokens_per_run: float | None
    cost_per_run: float | None
    judge_cost: float
    tool_calls_per_run: float | None
    code_lines: int
    code_non_blank_lines: int


def summarise(run: EvalRun) -> Summary:
    """The summary row for one results file."""
    records = run.records
    scores = [record.scores for record in records]
    latencies = [record.latency_seconds for record in records]
    return Summary(
        impl=run.impl,
        started_at=f"{run.started_at:%Y-%m-%d %H:%M}",
        model=run.model,
        effort=run.effort,
        prompt_hash=run.prompt_hash,
        cases_hash=run.cases_hash,
        git_sha=run.git_sha,
        runs=len(records),
        failed_runs=sum(record.error is not None for record in records),
        limit_runs=sum(record.stats.hit_limit for record in records),
        timed_out_runs=sum(record.stats.limit_fired == "timeout" for record in records),
        schema_validity=mean(record.schema_valid for record in records),
        citation_validity=mean(score.citation_validity for score in scores),
        injection_resisted=mean(score.injection_resisted for score in scores),
        stayed_empty=mean(score.stayed_empty for score in scores),
        duplicate_precision=mean(score.duplicate_precision for score in scores),
        duplicate_recall=mean(score.duplicate_recall for score in scores),
        label_hit_rate=mean(score.label_hit_rate for score in scores),
        top_issue_precision=mean(score.top_issue_precision for score in scores),
        top_issues_missing_runs=sum(bool(score.top_issues_missing) for score in scores),
        theme_score=mean(score.theme_score for score in scores),
        latency_p50=percentile(latencies, 50),
        latency_p95=percentile(latencies, 95),
        tokens_per_run=mean(r.stats.input_tokens + r.stats.output_tokens for r in records),
        cost_per_run=mean(record.cost_usd for record in records),
        judge_cost=sum(record.judge_cost_usd for record in records),
        tool_calls_per_run=mean(record.stats.tool_calls for record in records),
        code_lines=run.code_lines,
        code_non_blank_lines=run.code_non_blank_lines,
    )


# Each table is a list of (column title, Summary field, format); a None value prints as n/a.
TABLES: dict[str, list[tuple[str, str, str]]] = {
    "Runs": [
        ("Started (UTC)", "started_at", "{}"),
        ("Model", "model", "{}"),
        ("Effort", "effort", "{}"),
        ("Prompt hash", "prompt_hash", "{}"),
        ("Cases hash", "cases_hash", "{}"),
        ("Commit", "git_sha", "{:.12}"),
    ],
    "Safety and correctness": [
        ("Runs", "runs", "{}"),
        ("Schema validity", "schema_validity", "{:.0%}"),
        ("Citation validity", "citation_validity", "{:.0%}"),
        ("Injection resisted", "injection_resisted", "{:.0%}"),
        ("Stayed empty", "stayed_empty", "{:.0%}"),
        ("Failed runs", "failed_runs", "{}"),
        ("Hit a limit", "limit_runs", "{}"),
        ("Timed out", "timed_out_runs", "{}"),
    ],
    "Quality": [
        ("Duplicate precision", "duplicate_precision", "{:.0%}"),
        ("Duplicate recall", "duplicate_recall", "{:.0%}"),
        ("Label hit rate", "label_hit_rate", "{:.0%}"),
        ("Top-issue precision", "top_issue_precision", "{:.0%}"),
        ("No top issues", "top_issues_missing_runs", "{}"),
        ("Theme score (1-5)", "theme_score", "{:.1f}"),
    ],
    "Cost and speed": [
        ("Latency p50", "latency_p50", "{:.0f} s"),
        ("Latency p95", "latency_p95", "{:.0f} s"),
        ("Tokens per run", "tokens_per_run", "{:,.0f}"),
        ("Cost per run", "cost_per_run", "${:.3f}"),
        ("Judge cost", "judge_cost", "${:.3f}"),
        ("Tool calls per run", "tool_calls_per_run", "{:.1f}"),
        ("Code lines", "code_lines", "{}"),
        ("Non-blank lines", "code_non_blank_lines", "{}"),
    ],
}


def render(runs: list[EvalRun]) -> str:
    """The comparison tables as Markdown.

    The Runs table has a row per results file, so each file's provenance shows; the others have
    a row per implementation, over all its files, combined by ``combine``.
    """
    files = [summarise(run) for run in runs]
    impls = [summarise(run) for run in combine(runs)]
    return "\n\n".join(
        _table(title, columns, files if title == "Runs" else impls)
        for title, columns in TABLES.items()
    )


def _table(title: str, columns: list[tuple[str, str, str]], summaries: list[Summary]) -> str:
    header = ["Implementation", *(heading for heading, _, _ in columns)]
    rows = [
        [summary.impl, *(_cell(getattr(summary, field), spec) for _, field, spec in columns)]
        for summary in summaries
    ]
    lines = [f"## {title}", "", _row(header), _row(["---"] * len(header))]
    return "\n".join(lines + [_row(row) for row in rows])


def _cell(value: object, spec: str) -> str:
    return "n/a" if value is None else spec.format(value)


def _row(cells: list[str]) -> str:
    return f"| {' | '.join(cells)} |"
