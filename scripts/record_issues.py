"""Record a GitHub repository's open issues as a fixture. Run by hand; tests fake its requests.

Usage: .venv/bin/python scripts/record_issues.py owner/repo --name <fixture-name> [--limit 80]
Set GITHUB_TOKEN (environment or .env) to raise the unauthenticated rate limit.
"""

import json
import urllib.parse
import urllib.request
from collections.abc import Iterator
from datetime import UTC, datetime

import click

from bakeoff.fixtures import Comment, Issue, Repo, fixture_path
from bakeoff.settings import SETTINGS

API = "https://api.github.com"
PER_PAGE = 100
TIMEOUT = 30


def _get(url: str) -> list[dict]:
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "bakeoff-recorder"}
    if SETTINGS.github_token:
        headers["Authorization"] = f"Bearer {SETTINGS.github_token.get_secret_value()}"
    request = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
        return json.load(response)


def _pages(url: str, **params: str) -> Iterator[list[dict]]:
    """Every page of a GitHub list endpoint, ``PER_PAGE`` items at a time."""
    page = 1
    while True:
        query = urllib.parse.urlencode({**params, "per_page": PER_PAGE, "page": page})
        batch = _get(f"{url}?{query}")
        if batch:
            yield batch
        # A short page is the last one, which saves a request for an empty page.
        if len(batch) < PER_PAGE:
            return
        page += 1


def _open_issues(source: str, limit: int) -> list[dict]:
    issues: list[dict] = []
    for batch in _pages(f"{API}/repos/{source}/issues", state="open"):
        # The issues endpoint also returns pull requests; they are not issues.
        issues.extend(item for item in batch if "pull_request" not in item)
        if len(issues) >= limit:
            break
    return issues[:limit]


def _comments(issue: dict) -> list[Comment]:
    if not issue["comments"]:
        return []
    return [
        Comment(author=c["user"]["login"], body=c["body"] or "")
        for batch in _pages(issue["comments_url"])
        for c in batch
    ]


@click.command()
@click.argument("source")
@click.option("--name", required=True, help="Fixture directory name under evals/repos.")
@click.option("--limit", default=80, show_default=True, help="Maximum issues to record.")
def main(source: str, name: str, limit: int) -> None:
    """Fetch open issues and comments for SOURCE (owner/repo) into a fixture."""
    raw = _open_issues(source, limit)
    repo = Repo(
        name=name,
        source=source,
        recorded_at=datetime.now(UTC).isoformat(timespec="seconds"),
        issues=[
            Issue(
                number=item["number"],
                title=item["title"],
                body=item["body"] or "",
                labels=[label["name"] for label in item["labels"]],
                state=item["state"],
                comments=_comments(item),
            )
            for item in raw
        ],
    )
    path = fixture_path(name)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(repo.model_dump_json(indent=2) + "\n")
    click.echo(f"recorded {len(repo.issues)} issues from {source} to {path}")


if __name__ == "__main__":
    main()
