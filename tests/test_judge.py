import json
from types import SimpleNamespace

import pytest

from bakeoff.cases import Case
from bakeoff.contract import Theme, TriageReport
from bakeoff.fixtures import load_repo
from bakeoff.judge import RUBRIC, Judgement, ThemeJudge, Verdict
from bakeoff.settings import SETTINGS

CASE = Case(name="tiny-themes", repo="tiny", themes=[Theme(name="Crashes", issues=[1])])
REPORT = TriageReport(
    themes=[Theme(name="Everything", issues=[1, 2, 9])],
    duplicates=[],
    top_issues=[],
    suggested_labels=[],
)
VERDICT = Verdict(reason="One theme mixes a crash with a feature.", score=2)


class StubClient:
    """Answers ``messages.parse`` with one verdict, using 1M + 100k tokens, and records calls."""

    def __init__(self, verdict: Verdict):
        self.messages = self
        self.verdict = verdict
        self.calls: list[dict] = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        usage = SimpleNamespace(input_tokens=1_000_000, output_tokens=100_000)
        return SimpleNamespace(parsed_output=self.verdict, usage=usage)


@pytest.fixture
def judge_model(tiny_root, monkeypatch):
    """Price the judge's calls at Sonnet rates, so 1M + 100k tokens cost $3."""
    monkeypatch.setattr(SETTINGS, "model", "claude-sonnet-5-5")


def test_judge_scores_a_report_s_themes_against_the_case(judge_model, tmp_path):
    repo = load_repo("tiny")
    client = StubClient(VERDICT)
    judge = ThemeJudge(client, tmp_path / "cache.json")
    assert judge.score(REPORT, CASE, repo) == Judgement(score=2, cost_usd=3.0)
    [call] = client.calls
    assert (call["system"], call["output_format"]) == (RUBRIC, Verdict)
    [message] = call["messages"]
    assert message["content"] == (
        "Labelled themes:\nCrashes\n- #1 Crash on startup\n\n"
        "The report's themes:\nEverything\n- #1 Crash on startup\n- #2 Add dark mode\n"
        "- #9 (not in the repo)"
    )
    # Nothing to compare against, so no call is made and nothing is spent.
    bare = Case(name="bare", repo="tiny")
    assert judge.score(REPORT, bare, repo) == Judgement(score=None, cost_usd=0.0)
    assert len(client.calls) == 1


def test_judge_scores_a_repeated_report_from_the_cache(judge_model, tmp_path):
    repo, cache = load_repo("tiny"), tmp_path / "cache.json"
    client = StubClient(VERDICT)
    ThemeJudge(client, cache).score(REPORT, CASE, repo)
    # A new judge reads the scores already paid for from disk, and spends nothing on them.
    assert ThemeJudge(client, cache).score(REPORT, CASE, repo) == Judgement(score=2, cost_usd=0.0)
    assert len(client.calls) == 1
    [entry] = json.loads(cache.read_text()).values()
    assert entry == VERDICT.model_dump()
