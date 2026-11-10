"""An LLM judge that scores a report's themes against a case's labelled themes, 1 to 5."""

import anthropic
from pydantic import BaseModel, Field

from bakeoff.cases import Case
from bakeoff.contract import Theme, TriageReport
from bakeoff.fixtures import Repo
from bakeoff.settings import SETTINGS

RUBRIC = """\
You grade how well an issue triage report grouped a repository's open issues into themes. You \
get the themes a maintainer labelled and the themes the report proposed, with each issue shown \
by number and title.

Score the report's themes from 1 to 5:
5: The same groupings as the labelled themes, or groupings at least as coherent. Every theme is \
a real, distinct topic.
4: Mostly the labelled groupings; a few issues are misplaced or two themes overlap.
3: Some themes match; others are vague, overlap, or mix unrelated issues.
2: Few themes match; most groupings are vague or mix unrelated issues.
1: The themes don't reflect the issues: arbitrary, empty or duplicated groupings.

Judge the groupings, not the theme names or their order. Give your reason first, then the score.
"""


class Verdict(BaseModel):
    # Reason first, so the score is written after the reasoning that supports it.
    reason: str
    score: int = Field(ge=1, le=5)


class ThemeJudge:
    """Scores theme quality with ``SETTINGS.model``, through the client it is given."""

    def __init__(self, client: anthropic.Anthropic) -> None:
        self._client = client

    def score(self, report: TriageReport, case: Case, repo: Repo) -> int | None:
        """The judge's score, or ``None`` when the case labels no themes or no verdict came back.

        A refusal has no verdict; a verdict that doesn't validate raises.
        """
        if not case.themes:
            return None
        response = self._client.messages.parse(
            model=SETTINGS.model,
            max_tokens=16_000,
            system=RUBRIC,
            messages=[{"role": "user", "content": judge_prompt(report, case, repo)}],
            output_format=Verdict,
        )
        verdict = response.parsed_output
        return None if verdict is None else verdict.score


def judge_prompt(report: TriageReport, case: Case, repo: Repo) -> str:
    """The user message: the labelled themes, then the report's, each issue as ``#n title``."""
    return (
        f"Labelled themes:\n{_themes_text(case.themes, repo)}\n\n"
        f"The report's themes:\n{_themes_text(report.themes, repo)}"
    )


def _themes_text(themes: list[Theme], repo: Repo) -> str:
    return "\n\n".join(
        f"{theme.name}\n" + "\n".join(_issue_line(number, repo) for number in theme.issues)
        for theme in themes
    )


def _issue_line(number: int, repo: Repo) -> str:
    issue = repo.issue(number)
    return f"- #{number} (not in the repo)" if issue is None else f"- #{number} {issue.title}"
