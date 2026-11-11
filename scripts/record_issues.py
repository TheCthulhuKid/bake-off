"""Record a GitHub repository's open issues as a fixture. Run by hand; tests fake its requests.

Usage: .venv/bin/python scripts/record_issues.py owner/repo --name <fixture-name> [--limit 80]
An existing fixture is never replaced unless --force is passed.
Set GITHUB_TOKEN (environment or .env) to raise the unauthenticated rate limit.
"""

from collections.abc import Iterator
from datetime import UTC, datetime

import click
import httpx2

from bakeoff.fixtures import Comment, Issue, Repo, fixture_path
from bakeoff.settings import SETTINGS

API = "https://api.github.com"
PER_PAGE = 100


def _client(transport: httpx2.BaseTransport | None = None) -> httpx2.Client:
    """A GitHub API client; tests pass a mock ``transport``."""
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "bakeoff-recorder"}
    if SETTINGS.github_token:
        headers["Authorization"] = f"Bearer {SETTINGS.github_token.get_secret_value()}"
    return httpx2.Client(base_url=API, headers=headers, timeout=30, transport=transport)


def _pages(client: httpx2.Client, url: str, **params: str) -> Iterator[list[dict]]:
    """Every page of a GitHub list endpoint, following the ``Link`` header's next page."""
    response = client.get(url, params={**params, "per_page": PER_PAGE})
    while True:
        response.raise_for_status()
        yield response.json()
        if "next" not in response.links:
            return
        response = client.get(response.links["next"]["url"])


def _open_issues(client: httpx2.Client, source: str, limit: int) -> list[dict]:
    issues: list[dict] = []
    for batch in _pages(client, f"/repos/{source}/issues", state="open"):
        # The issues endpoint also returns pull requests; they are not issues.
        issues.extend(item for item in batch if "pull_request" not in item)
        if len(issues) >= limit:
            break
    return issues[:limit]


def _comments(client: httpx2.Client, issue: dict) -> list[Comment]:
    if not issue["comments"]:
        return []
    return [
        Comment(author=_author(c), body=c["body"] or "")
        for batch in _pages(client, issue["comments_url"])
        for c in batch
    ]


def _author(comment: dict) -> str:
    # GitHub sends "user": null for a deleted account and shows such a comment as by "ghost".
    user = comment["user"]
    return "ghost" if user is None else user["login"]


@click.command()
@click.argument("source")
@click.option("--name", required=True, help="Fixture directory name under evals/repos.")
@click.option("--limit", default=80, show_default=True, help="Maximum issues to record.")
@click.option("--force", is_flag=True, help="Replace an existing fixture.")
def main(source: str, name: str, limit: int, force: bool) -> None:
    """Fetch open issues and comments for SOURCE (owner/repo) into a fixture."""
    path = fixture_path(name)
    # Checked before any request: ground truth is labelled against the recorded issues.
    if path.exists() and not force:
        raise click.ClickException(f"{path} already exists; pass --force to replace it")
    with _client() as client:
        raw = _open_issues(client, source, limit)
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
                    comments=_comments(client, item),
                )
                for item in raw
            ],
        )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(repo.model_dump_json(indent=2) + "\n", encoding="utf-8")
    click.echo(f"recorded {len(repo.issues)} issues from {source} to {path}")


if __name__ == "__main__":
    main()
