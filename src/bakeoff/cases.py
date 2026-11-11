"""Hand-labelled eval cases: the ground truth each run's report is scored against."""

from collections import Counter
from pathlib import Path

import yaml
from pydantic import BaseModel, TypeAdapter, field_validator

from bakeoff.contract import Theme


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
    notes: str = ""

    @field_validator("duplicates")
    @classmethod
    def _distinct_issues(cls, pairs: list[tuple[int, int]] | None) -> list[tuple[int, int]] | None:
        if pairs is None:
            return None
        for a, b in pairs:
            if a == b:
                raise ValueError(f"a duplicate pair needs two different issues, got #{a} twice")
        return pairs


_CASES = TypeAdapter(list[Case])


def load_cases(path: Path) -> list[Case]:
    """The cases in the YAML list at ``path``; a name used twice raises ``ValueError``."""
    cases = _CASES.validate_python(yaml.safe_load(path.read_text(encoding="utf-8")))
    counts = Counter(case.name for case in cases)
    if repeated := sorted(name for name, count in counts.items() if count > 1):
        raise ValueError(f"repeated case names in {path}: {repeated}")
    return cases
