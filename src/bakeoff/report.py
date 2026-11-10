"""Summarises saved eval runs into the comparison tables, from the results files alone."""

from pydantic import BaseModel

from bakeoff.runner import EvalRun
from bakeoff.scoring import mean, percentile


class Summary(BaseModel):
    """One implementation's eval as one row: a field per column, ``None`` for no data."""

    impl: str
    started_at: str
    model: str
    effort: str
    prompt_hash: str
    git_sha: str | None
    runs: int
    failed_runs: int
    limit_runs: int
    timed_out_runs: int
    schema_validity: float | None
    citation_validity: float | None
    injection_resisted: float | None
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
    # A run abandoned at its timeout may not have recorded its tokens yet, so its cost is a lower
    # bound; such runs are counted on their own instead of pulling the cost mean down.
    finished = [record for record in records if record.stats.limit_fired != "timeout"]
    latencies = [record.latency_seconds for record in records]
    return Summary(
        impl=run.impl,
        started_at=f"{run.started_at:%Y-%m-%d %H:%M}",
        model=run.model,
        effort=run.effort,
        prompt_hash=run.prompt_hash,
        git_sha=run.git_sha,
        runs=len(records),
        failed_runs=sum(record.error is not None for record in records),
        limit_runs=sum(record.stats.hit_limit for record in records),
        timed_out_runs=len(records) - len(finished),
        schema_validity=mean(record.schema_valid for record in records),
        citation_validity=mean(score.citation_validity for score in scores),
        injection_resisted=mean(score.injection_resisted for score in scores),
        duplicate_precision=mean(score.duplicate_precision for score in scores),
        duplicate_recall=mean(score.duplicate_recall for score in scores),
        label_hit_rate=mean(score.label_hit_rate for score in scores),
        top_issue_precision=mean(score.top_issue_precision for score in scores),
        top_issues_missing_runs=sum(bool(score.top_issues_missing) for score in scores),
        theme_score=mean(score.theme_score for score in scores),
        latency_p50=percentile(latencies, 50),
        latency_p95=percentile(latencies, 95),
        tokens_per_run=mean(r.stats.input_tokens + r.stats.output_tokens for r in records),
        cost_per_run=mean(record.cost_usd for record in finished),
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
        ("Commit", "git_sha", "{:.12}"),
    ],
    "Safety and correctness": [
        ("Runs", "runs", "{}"),
        ("Schema validity", "schema_validity", "{:.0%}"),
        ("Citation validity", "citation_validity", "{:.0%}"),
        ("Injection resisted", "injection_resisted", "{:.0%}"),
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
    """The comparison tables as Markdown, one row per results file."""
    summaries = [summarise(run) for run in runs]
    return "\n\n".join(_table(title, columns, summaries) for title, columns in TABLES.items())


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
