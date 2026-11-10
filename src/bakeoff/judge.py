"""An LLM judge that scores a report's themes against a case's labelled themes, 1 to 5.

Scores are cached on disk by model, rubric and prompt, so a repeated report costs nothing.
"""

import hashlib
import json
from pathlib import Path

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


class Judgement(BaseModel):
    score: int | None
    # Priced when paid, as a run's cost is; zero for a cached score or no call.
    cost_usd: float


class ThemeJudge:
    """Scores theme quality with ``SETTINGS.model``, caching each verdict in ``cache_path``."""

    def __init__(self, client: anthropic.Anthropic, cache_path: Path) -> None:
        self._client = client
        self._cache_path = cache_path
        self._cache: dict[str, dict] = (
            json.loads(cache_path.read_text(encoding="utf-8")) if cache_path.exists() else {}
        )

    def score(self, report: TriageReport, case: Case, repo: Repo) -> Judgement:
        """Judge the report's themes; the score is ``None`` when there is nothing to judge.

        That is a case that labels no themes, where no call is made, or a reply with no verdict,
        such as a refusal, which isn't cached. A verdict that doesn't validate raises.
        """
        if not case.themes:
            return Judgement(score=None, cost_usd=0.0)
        prompt = judge_prompt(report, case, repo)
        key = _cache_key(prompt)
        if key in self._cache:
            return Judgement(score=self._cache[key]["score"], cost_usd=0.0)
        response = self._client.messages.parse(
            model=SETTINGS.model,
            max_tokens=16_000,
            system=RUBRIC,
            messages=[{"role": "user", "content": prompt}],
            output_format=Verdict,
        )
        cost = SETTINGS.cost(response.usage.input_tokens, response.usage.output_tokens)
        verdict = response.parsed_output
        if verdict is None:
            return Judgement(score=None, cost_usd=cost)
        # The reason is kept for the spot check by hand.
        self._cache[key] = verdict.model_dump()
        self._save()
        return Judgement(score=verdict.score, cost_usd=cost)

    def _save(self) -> None:
        # Written after every new score through a temporary file, so an interrupted eval keeps
        # every score it paid for and never leaves a half-written cache.
        temporary = self._cache_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self._cache, indent=1, sort_keys=True), encoding="utf-8")
        temporary.replace(self._cache_path)


def _cache_key(prompt: str) -> str:
    return hashlib.sha256(json.dumps([SETTINGS.model, RUBRIC, prompt]).encode()).hexdigest()


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
