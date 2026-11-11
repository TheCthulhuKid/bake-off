"""Build the derived fixtures listed in evals/derived.yaml from recorded ones. Run by hand.

Usage: .venv/bin/python scripts/derive_fixtures.py [--spec evals/derived.yaml]
Every derived fixture is rebuilt from the spec, so the same spec always gives the same files.
A recorded fixture is never overwritten.
"""

from collections import Counter
from pathlib import Path
from typing import Annotated, Literal

import click
import yaml
from pydantic import BaseModel, Field, TypeAdapter, model_validator

from bakeoff.fixtures import Issue, Repo, fixture_path, load_repo
from bakeoff.settings import PROJECT_ROOT

SPEC = PROJECT_ROOT / "evals" / "derived.yaml"


class Slice(BaseModel):
    """Keep only the listed issues, in the base's order."""

    step: Literal["slice"]
    issues: list[int]

    def apply(self, issues: list[Issue]) -> list[Issue]:
        _check_known(self.issues, issues)
        return [issue for issue in issues if issue.number in self.issues]


class HideLabels(BaseModel):
    """Clear the labels of the listed issues; the cleared labels become the expected answer."""

    step: Literal["hide_labels"]
    issues: list[int]

    def apply(self, issues: list[Issue]) -> list[Issue]:
        _check_known(self.issues, issues)
        return [
            issue.model_copy(update={"labels": []}) if issue.number in self.issues else issue
            for issue in issues
        ]


class Plant(BaseModel):
    """Add an open issue with no comments, after the others."""

    step: Literal["plant"]
    number: int
    title: str
    body: str
    labels: list[str] = []

    def apply(self, issues: list[Issue]) -> list[Issue]:
        if any(issue.number == self.number for issue in issues):
            raise ValueError(f"issue #{self.number} is already in the fixture")
        planted = Issue(
            number=self.number,
            title=self.title,
            body=self.body,
            labels=self.labels,
            state="open",
            comments=[],
        )
        return [*issues, planted]


class Inflate(BaseModel):
    """Pad one issue's body to ``characters`` by repeating its own text."""

    step: Literal["inflate"]
    number: int
    characters: int

    def apply(self, issues: list[Issue]) -> list[Issue]:
        _check_known([self.number], issues)
        return [self._inflated(issue) if issue.number == self.number else issue for issue in issues]

    def _inflated(self, issue: Issue) -> Issue:
        if not issue.body or self.characters <= len(issue.body):
            raise ValueError(
                f"issue #{self.number} can't be padded to {self.characters} characters"
            )
        copies = self.characters // (len(issue.body) + 2) + 1
        body = "\n\n".join([issue.body] * copies)[: self.characters]
        return issue.model_copy(update={"body": body})


class Rewrite(BaseModel):
    """Replace one issue's title, body or both with hand-written text, such as a translation."""

    step: Literal["rewrite"]
    number: int
    title: str | None = None
    body: str | None = None

    @model_validator(mode="after")
    def _changes_something(self) -> "Rewrite":
        if self.title is None and self.body is None:
            raise ValueError(f"rewriting issue #{self.number} needs a title or a body")
        return self

    def apply(self, issues: list[Issue]) -> list[Issue]:
        _check_known([self.number], issues)
        changes = self.model_dump(include={"title", "body"}, exclude_none=True)
        return [
            issue.model_copy(update=changes) if issue.number == self.number else issue
            for issue in issues
        ]


Step = Annotated[Slice | HideLabels | Plant | Inflate | Rewrite, Field(discriminator="step")]


class Derived(BaseModel):
    name: str
    base: str
    steps: list[Step]


def load_spec(path: Path) -> list[Derived]:
    """The entries in the spec at ``path``; a name used twice raises ``ValueError``."""
    entries = TypeAdapter(list[Derived]).validate_python(
        yaml.safe_load(path.read_text(encoding="utf-8"))
    )
    counts = Counter(entry.name for entry in entries)
    if repeated := sorted(name for name, count in counts.items() if count > 1):
        raise ValueError(f"repeated fixture names in {path}: {repeated}")
    return entries


def derive(entry: Derived) -> Repo:
    """``entry``'s fixture: its base with the steps applied in order."""
    base = load_repo(entry.base)
    issues = base.issues
    for step in entry.steps:
        issues = step.apply(issues)
    return Repo(
        name=entry.name,
        source=base.source,
        recorded_at=base.recorded_at,
        synthetic=True,
        issues=issues,
    )


def write(repo: Repo) -> Path:
    """Write ``repo`` as its fixture, refusing to replace a recorded one."""
    path = fixture_path(repo.name)
    if path.exists() and not load_repo(repo.name).synthetic:
        raise ValueError(f"{path} is a recorded fixture; a derived one never replaces it")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(repo.model_dump_json(indent=2) + "\n", encoding="utf-8")
    return path


def _check_known(numbers: list[int], issues: list[Issue]) -> None:
    if missing := set(numbers) - {issue.number for issue in issues}:
        raise ValueError(f"issues not in the fixture: {sorted(missing)}")


@click.command()
@click.option(
    "--spec",
    type=click.Path(exists=True, dir_okay=False, path_type=Path),
    default=SPEC,
    show_default="evals/derived.yaml",
)
def main(spec: Path) -> None:
    """Rebuild every derived fixture in SPEC."""
    try:
        for entry in load_spec(spec):
            path = write(derive(entry))
            click.echo(f"derived {path} from {entry.base}")
    except ValueError as error:
        raise click.ClickException(str(error)) from error


if __name__ == "__main__":
    main()
