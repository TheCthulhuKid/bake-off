from types import SimpleNamespace

from bakeoff.cases import Case
from bakeoff.contract import Theme, TriageReport
from bakeoff.fixtures import load_repo
from bakeoff.judge import RUBRIC, ThemeJudge, Verdict


class StubClient:
    """Answers ``messages.parse`` with one verdict and records each call."""

    def __init__(self, verdict: Verdict):
        self.messages = self
        self.verdict = verdict
        self.calls: list[dict] = []

    def parse(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(parsed_output=self.verdict)


def test_judge_scores_a_report_s_themes_against_the_case(tiny_root):
    repo = load_repo("tiny")
    case = Case(name="tiny-themes", repo="tiny", themes=[Theme(name="Crashes", issues=[1])])
    report = TriageReport(
        themes=[Theme(name="Everything", issues=[1, 2, 9])],
        duplicates=[],
        top_issues=[],
        suggested_labels=[],
    )
    client = StubClient(Verdict(reason="One theme mixes a crash with a feature.", score=2))
    judge = ThemeJudge(client)
    assert judge.score(report, case, repo) == 2
    [call] = client.calls
    assert (call["system"], call["output_format"]) == (RUBRIC, Verdict)
    [message] = call["messages"]
    assert message["content"] == (
        "Labelled themes:\nCrashes\n- #1 Crash on startup\n\n"
        "The report's themes:\nEverything\n- #1 Crash on startup\n- #2 Add dark mode\n"
        "- #9 (not in the repo)"
    )
    # Nothing to compare against, so no call is made.
    assert judge.score(report, Case(name="bare", repo="tiny"), repo) is None
    assert len(client.calls) == 1
