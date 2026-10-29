"""Recorded repository data. Tools read fixtures, never live GitHub."""

from pathlib import Path

from pydantic import BaseModel

FIXTURE_ROOT = Path(__file__).resolve().parents[2] / "evals" / "repos"


class Comment(BaseModel):
    author: str
    body: str


class Issue(BaseModel):
    number: int
    title: str
    body: str
    labels: list[str]
    state: str
    comments: list[Comment]


class Repo(BaseModel):
    name: str
    source: str
    recorded_at: str
    issues: list[Issue]

    def issue(self, number: int) -> Issue | None:
        return next((issue for issue in self.issues if issue.number == number), None)


def fixture_path(name: str, root: Path | None = None) -> Path:
    # Resolved at call time so tests can point every caller, tools included, at another root.
    return (root or FIXTURE_ROOT) / name / "issues.json"


def load_repo(name: str, root: Path | None = None) -> Repo:
    """Load ``<root>/<name>/issues.json``; an unknown name raises FileNotFoundError."""
    path = fixture_path(name, root)
    if not path.is_file():
        raise FileNotFoundError(f"no recorded repo {name!r} under {path.parent.parent}")
    return Repo.model_validate_json(path.read_text())
