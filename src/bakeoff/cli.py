"""Command-line entry point. Commands handle input and output only."""

import click


@click.group()
def main() -> None:
    """Run the issue triage agent and its evals."""
