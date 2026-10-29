import pytest

from bakeoff.settings import SETTINGS
from bakeoff.telemetry import ToolLimitExceeded, collect, record_usage
from bakeoff.tools import get_issue, list_issues, search_issues

pytestmark = pytest.mark.usefixtures("tiny_root")


def test_list_issues_pages_through_summaries(monkeypatch):
    monkeypatch.setattr(SETTINGS, "page_size", 1)
    first = list_issues("tiny")
    assert first["pages"] == 2
    assert first["issues"] == [
        {"number": 1, "title": "Crash on startup", "labels": ["bug"], "comments": 1}
    ]
    assert list_issues("tiny", page=2)["issues"][0]["number"] == 2
    assert list_issues("tiny", page=3)["issues"] == []


def test_get_issue_marks_truncation_and_reports_unknown_numbers(monkeypatch):
    monkeypatch.setattr(SETTINGS, "body_limit", 20)
    issue = get_issue("tiny", 1)
    assert issue["body"] == "The app crashes when\n[truncated: 31 of 51 characters omitted]"
    assert issue["comments"] == [{"author": "alice", "body": "Reproduced on 1.2."}]
    assert "error" in get_issue("tiny", 99)


def test_search_issues_matches_title_and_body_ignoring_case():
    assert [hit["number"] for hit in search_issues("tiny", "CRASH config")["issues"]] == [1]
    assert [hit["number"] for hit in search_issues("tiny", "theme")["issues"]] == [2]


def test_tool_limit_raises_inside_collect_and_usage_adds_up():
    with collect(max_tool_calls=2) as stats:
        list_issues("tiny")
        get_issue("tiny", 1)
        record_usage(100, 20)
        record_usage(50, 10)
        with pytest.raises(ToolLimitExceeded):
            search_issues("tiny", "crash")
    assert (stats.tool_calls, stats.input_tokens, stats.output_tokens) == (2, 150, 30)
    assert stats.hit_limit and stats.limit_fired == "tool_calls"
    # Outside collect() nothing is counted or limited.
    search_issues("tiny", "crash")
    assert stats.tool_calls == 2
