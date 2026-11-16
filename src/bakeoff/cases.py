"""Hand-labelled eval cases: the ground truth each run's report is scored against."""

from pathlib import Path

import yaml
from pydantic import BaseModel, TypeAdapter, ValidationError, field_validator

from bakeoff.contract import Theme, repeated, require_distinct


class Injection(BaseModel):
    """An issue whose text asks the agent to suggest ``forbidden_label``."""

    issue: int
    forbidden_label: str


class Case(BaseModel):
    """One fixture repo with its labels; a case labels only what it tests."""

    name: str
    repo: str
    themes: list[Theme] = []
    # None leaves duplicates unlabelled; [] labels the repo as having none.
    duplicates: list[tuple[int, int]] | None = None
    top_issues: list[int] = []
    labels: dict[int, list[str]] = {}
    injection: Injection | None = None
    expect_empty: bool = False
    notes: str = ""

    @field_validator("duplicates")
    @classmethod
    def _distinct_issues(cls, pairs: list[tuple[int, int]] | None) -> list[tuple[int, int]] | None:
        if pairs is None:
            return None
        for a, b in pairs:
            require_distinct(a, b)
        return pairs


_CASES = TypeAdapter(list[Case])


def load_cases(path: Path) -> list[Case]:
    """The cases in the YAML list at ``path``.

    A file that isn't YAML, a case that doesn't validate and a name used twice each raise
    ``ValueError``, naming the file.
    """
    try:
        cases = _CASES.validate_python(yaml.safe_load(path.read_text(encoding="utf-8")))
    except yaml.YAMLError as error:
        raise ValueError(f"{path} is not valid YAML: {error}") from error
    except ValidationError as error:
        raise ValueError(f"{path}: {error}") from error
    if names := repeated(case.name for case in cases):
        raise ValueError(f"repeated case names in {path}: {names}")
    return cases
