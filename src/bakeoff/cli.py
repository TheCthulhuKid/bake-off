"""Command-line entry point. Commands handle input and output only."""

from pathlib import Path

import click

from bakeoff.impls import IMPLS
from bakeoff.runner import result_path, run_once


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
    except FileNotFoundError as error:
        raise click.ClickException(str(error)) from error
    text = result.model_dump_json(indent=2)
    click.echo(text)
    if out is not None:
        with out.open("x") as file:
            file.write(text + "\n")
