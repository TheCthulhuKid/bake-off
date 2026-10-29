"""Command-line entry point. Commands handle input and output only."""

from pathlib import Path

import click

from bakeoff.impls import IMPLS
from bakeoff.runner import run_once


@click.group()
def main() -> None:
    """Run the issue triage agent and its evals."""


@main.command()
@click.argument("impl", type=click.Choice(sorted(IMPLS)))
@click.argument("repo")
@click.option(
    "--out",
    type=click.Path(dir_okay=False, path_type=Path),
    help="Also write the result to this new file; an existing file is never overwritten.",
)
def run(impl: str, repo: str, out: Path | None) -> None:
    """Run IMPL once on the recorded REPO and print the report and stats as JSON."""
    # Checked before the run as well as by the "x" mode below, so a taken path costs no tokens.
    if out is not None and out.exists():
        raise click.ClickException(f"{out} already exists")
    try:
        result = run_once(impl, repo)
    except FileNotFoundError as error:
        raise click.ClickException(str(error)) from error
    text = result.model_dump_json(indent=2)
    click.echo(text)
    if out is not None:
        out.parent.mkdir(parents=True, exist_ok=True)
        with out.open("x") as file:
            file.write(text + "\n")
