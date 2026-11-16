import functools

import httpx2
import pytest
from click.testing import CliRunner
from helpers import load_script

from bakeoff.fixtures import load_repo

record_issues = load_script("record_issues")


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
    # GitHub names the next page in a Link header; the last page has none.
    pages = {
        ("/repos/o/r/issues", "1"): ([issue, pull], None),
        ("/repos/o/r/issues/1/comments", "1"): ([comment] * 100, f"{comments_url}?page=2"),
        # A deleted account's comment has no user; GitHub shows it as by "ghost".
        ("/repos/o/r/issues/1/comments", "2"): (
            [comment] * 29 + [{"user": None, "body": "+1"}],
            None,
        ),
    }
    requested = []

    def respond(request: httpx2.Request) -> httpx2.Response:
        key = (request.url.path, request.url.params.get("page", "1"))
        requested.append(key)
        body, next_url = pages[key]
        headers = {"Link": f'<{next_url}>; rel="next"'} if next_url else {}
        return httpx2.Response(200, json=body, headers=headers)

    transport = httpx2.MockTransport(respond)
    monkeypatch.setattr(
        record_issues, "_client", functools.partial(record_issues._client, transport)
    )
    result = CliRunner().invoke(record_issues.main, ["o/r", "--name", "r"])
    assert result.exit_code == 0, result.output
    [recorded] = load_repo("r").issues
    assert (recorded.number, recorded.body, len(recorded.comments)) == (1, "", 130)
    assert recorded.comments[-1].author == "ghost"
    assert requested == list(pages)
    # A second recording refuses before making any request, unless forced.
    again = CliRunner().invoke(record_issues.main, ["o/r", "--name", "r"])
    assert again.exit_code != 0 and "already exists" in again.output
    assert len(requested) == len(pages)
    forced = CliRunner().invoke(record_issues.main, ["o/r", "--name", "r", "--force"])
    assert forced.exit_code == 0, forced.output


@pytest.mark.parametrize(("limit", "exit_code"), [("1", 0), ("0", 2)])
def test_record_issues_needs_a_limit_of_at_least_one(monkeypatch, tmp_path, limit, exit_code):
    monkeypatch.setattr("bakeoff.fixtures.FIXTURE_ROOT", tmp_path)
    issue = {
        "number": 1,
        "title": "Crash",
        "body": "",
        "labels": [],
        "state": "open",
        "comments": 0,
    }
    transport = httpx2.MockTransport(lambda request: httpx2.Response(200, json=[issue]))
    monkeypatch.setattr(
        record_issues, "_client", functools.partial(record_issues._client, transport)
    )
    result = CliRunner().invoke(record_issues.main, ["o/r", "--name", "r", "--limit", limit])
    assert result.exit_code == exit_code, result.output
