"""The output every implementation must return. Imports nothing from the project."""

from collections import Counter

from pydantic import BaseModel, Field, ValidationError, model_validator


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


class LabelSuggestion(BaseModel):
    number: int
    labels: list[str]


class TriageReport(BaseModel):
    themes: list[Theme]
    duplicates: list[DuplicatePair]
    top_issues: list[TopIssue] = Field(max_length=5)
    suggested_labels: list[LabelSuggestion]

    @model_validator(mode="after")
    def _one_suggestion_per_issue(self) -> "TriageReport":
        counts = Counter(suggestion.number for suggestion in self.suggested_labels)
        if repeated := {number for number, count in counts.items() if count > 1}:
            raise ValueError(f"repeated issue numbers in label suggestions: {repeated}")
        return self

    def cited_issues(self) -> set[int]:
        """Every issue number the report mentions, for citation checks."""
        cited = {number for theme in self.themes for number in theme.issues}
        cited.update(number for pair in self.duplicates for number in (pair.a, pair.b))
        cited.update(suggestion.number for suggestion in self.suggested_labels)
        cited.update(top.number for top in self.top_issues)
        return cited


class InvalidReport(ValueError):
    """Raised by an implementation when the model's final report fails validation."""


def parse_report(text: str) -> TriageReport:
    """Validate a report sent as JSON text, raising ``InvalidReport`` if it is invalid."""
    try:
        return TriageReport.model_validate_json(text)
    except ValidationError as error:
        raise InvalidReport(str(error)) from error
