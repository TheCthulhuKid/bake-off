"""The output every implementation must return. Imports nothing from the project."""

from pydantic import BaseModel, Field, model_validator


class Theme(BaseModel):
    name: str
    issues: list[int]


class DuplicatePair(BaseModel):
    a: int
    b: int
    reason: str

    @model_validator(mode="after")
    def _distinct_issues(self) -> "DuplicatePair":
        if self.a == self.b:
            raise ValueError(f"a duplicate pair needs two different issues, got #{self.a} twice")
        return self


class TopIssue(BaseModel):
    number: int
    reason: str


class TriageReport(BaseModel):
    themes: list[Theme]
    duplicates: list[DuplicatePair]
    top_issues: list[TopIssue] = Field(max_length=5)
    suggested_labels: dict[int, list[str]]

    def cited_issues(self) -> set[int]:
        """Every issue number the report mentions, for citation checks."""
        cited = {number for theme in self.themes for number in theme.issues}
        cited.update(number for pair in self.duplicates for number in (pair.a, pair.b))
        cited.update(top.number for top in self.top_issues)
        cited.update(self.suggested_labels)
        return cited
