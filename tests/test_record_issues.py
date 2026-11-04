import importlib.util
from pathlib import Path
from urllib.parse import parse_qs

from click.testing import CliRunner

from bakeoff.fixtures import load_repo

SCRIPT = Path(__file__).parents[1] / "scripts" / "record_issues.py"
spec = importlib.util.spec_from_file_location("record_issues", SCRIPT)
record_issues = importlib.util.module_from_spec(spec)
spec.loader.exec_module(record_issues)


def test_records_issues_skipping_pull_requests_and_pages_through_comments(monkeypatch, tmp_path):
    monkeypatch.setattr("bakeoff.fixtures.FIXTURE_ROOT", tmp_path)
    comments_url = "https://api.github.com/repos/o/r/issues/1/comments"
    comment = {"user": {"login": "alice"}, "body": "same here"}
    issue = {
        "number": 1,
        "title": "Crash",
        "body": None,
        "labels": [{"name": "bug"}],
        "state": "open",
        "comments": 130,
        "comments_url": comments_url,
    }
    pull = {"number": 2, "pull_request": {}}
    # GitHub serves at most PER_PAGE items a page, so 130 comments take two pages.
    pages = {
        ("https://api.github.com/repos/o/r/issues", "1"): [issue, pull],
        (comments_url, "1"): [comment] * 100,
        (comments_url, "2"): [comment] * 30,
    }
    requested = []

    def fake_get(url):
        base, _, query = url.partition("?")
        page = parse_qs(query)["page"][0]
        requested.append((base, page))
        return pages[base, page]

    monkeypatch.setattr(record_issues, "_get", fake_get)
    result = CliRunner().invoke(record_issues.main, ["o/r", "--name", "r"])
    assert result.exit_code == 0, result.output
    [recorded] = load_repo("r").issues
    assert (recorded.number, recorded.body, len(recorded.comments)) == (1, "", 130)
    # A short page ends the paging without asking for an empty one.
    assert requested == list(pages)
