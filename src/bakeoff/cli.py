"""Command-line entry point. Commands handle input and output only."""

from collections.abc import Iterable
from pathlib import Path

import anthropic
import click

from bakeoff.cases import Case, load_cases
from bakeoff.contract import repeated
from bakeoff.fixtures import UnknownRepoError
from bakeoff.impls import IMPLS
from bakeoff.judge import JudgeCacheError, ThemeJudge
from bakeoff.report import IncompatibleRuns, render
from bakeoff.runner import (
    EvalInterrupted,
    EvalRun,
    RescoreError,
    RunRecord,
    check_cases,
    load_eval,
    result_path,
    run_eval,
    run_once,
    save_result,
    select_cases,
)
from bakeoff.runner import rescore as rescore_eval
from bakeoff.settings import PROJECT_ROOT, SETTINGS

EVALS = PROJECT_ROOT / "evals"

cases_option = click.option(
    "--cases",
    "cases_path",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=EVALS / "cases.yaml",
    show_default="evals/cases.yaml",
)
files_argument = click.argument(
    "files", nargs=-1, required=True, type=click.Path(exists=True, dir_okay=False, path_type=Path)
)


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
        # Checked before the run as well as by save_result, so a bad path costs no tokens.
        _refuse_existing([out])
        out.parent.mkdir(parents=True, exist_ok=True)
    try:
        result = run_once(impl, repo)
    except UnknownRepoError as error:
        raise click.ClickException(str(error)) from error
    click.echo(result.model_dump_json(indent=2))
    if out is not None:
        save_result(result, out)


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
@cases_option
@click.option(
    "--repo",
    "repos",
    multiple=True,
    help="Only the cases on this fixture; a recorded repo also brings the cases derived from it. "
    "Repeatable.",
)
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
    # The whole file is checked, so a broken case stops any eval, and selecting can rely on
    # every fixture loading.
    cases = _load_checked_cases(cases_path)
    if repos:
        try:
            cases = select_cases(cases, repos)
        except UnknownRepoError as error:
            raise click.ClickException(str(error)) from error
    if not cases:
        raise click.ClickException(f"no cases to run in {cases_path}")
    impls = list(IMPLS) if impl == "all" else [impl]
    paths = {name: result_path(out, name) for name in impls}
    _refuse_existing(paths.values())
    theme_judge = _theme_judge(anthropic.Anthropic(api_key=SETTINGS.api_key())) if judge else None
    try:
        runs = run_eval(impls, cases, repeats, judge=theme_judge, on_record=_print_record)
    except EvalInterrupted as interrupted:
        finished = [run for run in interrupted.runs if run.records]
        _save_runs((run, paths[run.impl]) for run in finished)
        saved = "the files above hold every whole case" if finished else "no case had finished"
        click.echo(f"{interrupted}; {saved}", err=True)
        # Re-raised as it was, so Ctrl-C still aborts and a bug still shows its traceback.
        raise interrupted.__cause__ from None
    _save_runs((run, paths[run.impl]) for run in runs)


def _print_record(impl: str, record: RunRecord) -> None:
    outcome = record.error or "ok"
    click.echo(
        f"{impl} {record.case} #{record.repeat}: {outcome} "
        f"({record.latency_seconds:.1f} s, ${record.cost_usd:.4f})"
    )


@main.command()
@files_argument
def report(files: tuple[Path, ...]) -> None:
    """Print the comparison tables for saved eval FILES as Markdown.

    An implementation's files are combined into one row, so an eval run in parts reports as one.
    """
    runs = _load_evals(files)
    try:
        click.echo(render(runs))
    except IncompatibleRuns as error:
        raise click.ClickException(str(error)) from error


@main.command()
@files_argument
@cases_option
@click.option(
    "--out",
    type=click.Path(file_okay=False, path_type=Path),
    required=True,
    help="Directory for the rescored files, under their own names. Existing files are never "
    "overwritten.",
)
def rescore(files: tuple[Path, ...], cases_path: Path, out: Path) -> None:
    """Score saved eval FILES again against the current cases, offline, into new files.

    For labels fixed after an eval ran. Theme scores are read from the judge's cache, never
    paid for again.
    """
    runs = _load_evals(files)
    paths = [out / path.name for path in files]
    if names := repeated(path.name for path in files):
        raise click.ClickException(f"files share a name, which their copies would too: {names}")
    _refuse_existing(paths)
    cases = _load_checked_cases(cases_path)
    judge = _theme_judge(None)
    try:
        rescored = [rescore_eval(run, cases, judge) for run in runs]
    except RescoreError as error:
        raise click.ClickException(str(error)) from error
    _save_runs(zip(rescored, paths, strict=True))


def _load_checked_cases(path: Path) -> list[Case]:
    try:
        cases = load_cases(path)
    except ValueError as error:
        raise click.ClickException(str(error)) from error
    if problems := check_cases(cases):
        raise click.ClickException("cases do not match their fixtures:\n" + "\n".join(problems))
    return cases


def _refuse_existing(paths: Iterable[Path]) -> None:
    if taken := [str(path) for path in paths if path.exists()]:
        raise click.ClickException(f"already exists: {', '.join(taken)}")


def _theme_judge(client: anthropic.Anthropic | None) -> ThemeJudge:
    try:
        return ThemeJudge(client, EVALS / "judge-cache.json")
    except JudgeCacheError as error:
        raise click.ClickException(str(error)) from error


def _save_runs(runs: Iterable[tuple[EvalRun, Path]]) -> None:
    for run, path in runs:
        save_result(run, path)
        click.echo(f"saved {path}")


def _load_evals(files: tuple[Path, ...]) -> list[EvalRun]:
    try:
        return [load_eval(path) for path in files]
    except ValueError as error:
        raise click.ClickException(f"not a results file: {error}") from error
