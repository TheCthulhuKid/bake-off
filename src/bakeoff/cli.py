"""Command-line entry point. Commands handle input and output only."""

from pathlib import Path

import anthropic
import click

from bakeoff.cases import load_cases
from bakeoff.fixtures import UnknownRepoError
from bakeoff.impls import IMPLS
from bakeoff.judge import ThemeJudge
from bakeoff.report import render
from bakeoff.runner import (
    RunRecord,
    check_cases,
    load_eval,
    result_path,
    run_eval,
    run_once,
    save_eval,
)
from bakeoff.settings import PROJECT_ROOT, SETTINGS

EVALS = PROJECT_ROOT / "evals"


@click.group()
def main() -> None:
    """Run the issue triage agent and its evals."""


@main.command()
@click.argument("impl", type=click.Choice(sorted(IMPLS)))
@click.argument("repo")
@click.option(
    "--out",
    type=click.Path(path_type=Path),
    help=(
        "Also write the result to a new file: a path ending in .json is used as given, any "
        "other path is a directory that gets <UTC timestamp>-<IMPL>.json. Existing files are "
        "never overwritten."
    ),
)
def run(impl: str, repo: str, out: Path | None) -> None:
    """Run IMPL once on the recorded REPO and print the report and stats as JSON."""
    if out is not None:
        out = result_path(out, impl)
        # Done before the run as well as by the "x" mode below, so a bad path costs no tokens.
        if out.exists():
            raise click.ClickException(f"{out} already exists")
        out.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = run_once(impl, repo)
    except UnknownRepoError as error:
        raise click.ClickException(str(error)) from error
    text = result.model_dump_json(indent=2)
    click.echo(text)
    if out is not None:
        with out.open("x", encoding="utf-8") as file:
            file.write(text + "\n")


# Named eval_ so the function doesn't shadow the builtin.
@main.command("eval")
@click.option(
    "--impl",
    type=click.Choice(["all", *IMPLS]),
    default="all",
    show_default=True,
    help="The implementation to run, or all of them, taking turns on each case.",
)
@click.option("--repeats", type=click.IntRange(min=1), default=3, show_default=True)
@click.option(
    "--cases",
    "cases_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=EVALS / "cases.yaml",
    show_default="evals/cases.yaml",
)
@click.option("--repo", "repos", multiple=True, help="Only the cases on this repo; repeatable.")
@click.option("--judge", is_flag=True, help="Score themes with the LLM judge, which costs extra.")
@click.option(
    "--out",
    type=click.Path(file_okay=False, path_type=Path),
    default=PROJECT_ROOT / "results",
    show_default="results",
    help="Directory for one new <UTC timestamp>-<IMPL>.json per implementation.",
)
def eval_(
    impl: str, repeats: int, cases_path: Path, repos: tuple[str, ...], judge: bool, out: Path
) -> None:
    """Run the eval cases and save one results file per implementation."""
    # Everything that can fail cheaply is checked before the first run is paid for.
    if out.suffix == ".json":
        raise click.ClickException("--out is a directory: every implementation gets its own file")
    try:
        cases = load_cases(cases_path)
    except ValueError as error:
        raise click.ClickException(f"{cases_path}: {error}") from error
    if repos:
        cases = [case for case in cases if case.repo in repos]
    if not cases:
        raise click.ClickException(f"no cases to run in {cases_path}")
    if problems := check_cases(cases):
        raise click.ClickException("cases do not match their fixtures:\n" + "\n".join(problems))
    impls = list(IMPLS) if impl == "all" else [impl]
    paths = {name: result_path(out, name) for name in impls}
    if taken := [str(path) for path in paths.values() if path.exists()]:
        raise click.ClickException(f"already exists: {', '.join(taken)}")
    theme_judge = (
        ThemeJudge(anthropic.Anthropic(api_key=SETTINGS.api_key()), EVALS / "judge-cache.json")
        if judge
        else None
    )
    runs = run_eval(impls, cases, repeats, judge=theme_judge, on_record=_print_record)
    for run in runs:
        save_eval(run, paths[run.impl])
        click.echo(f"saved {paths[run.impl]}")


def _print_record(impl: str, record: RunRecord) -> None:
    outcome = record.error or "ok"
    click.echo(
        f"{impl} {record.case} #{record.repeat}: {outcome} "
        f"({record.latency_seconds:.1f} s, ${record.cost_usd:.4f})"
    )


@main.command()
@click.argument(
    "files", nargs=-1, required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path)
)
def report(files: tuple[Path, ...]) -> None:
    """Print the comparison tables for saved eval FILES, one row per file, as Markdown."""
    try:
        runs = [load_eval(path) for path in files]
    except ValueError as error:
        raise click.ClickException(f"not a results file: {error}") from error
    click.echo(render(runs))
