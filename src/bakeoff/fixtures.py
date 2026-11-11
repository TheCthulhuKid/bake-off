"""Recorded repository data. Tools read fixtures, never live GitHub."""

from pathlib import Path

from pydantic import BaseModel

from bakeoff.settings import PROJECT_ROOT

FIXTURE_ROOT = PROJECT_ROOT / "evals" / "repos"


class UnknownRepoError(FileNotFoundError):
    """Raised by ``load_repo`` for a name with no recorded fixture."""


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


def fixture_path(name: str) -> Path:
    """``FIXTURE_ROOT/<name>/issues.json``; a name that isn't one directory raises UnknownRepoError.

    The tools pass the model's repo argument here, and issue text is untrusted, so a name such
    as ``../elsewhere`` or an absolute path must not reach a file outside the fixture root.
    """
    if name in {"", ".", ".."} or Path(name).name != name:
        raise UnknownRepoError(f"{name!r} is not a fixture name")
    # Read at call time so tests can point every caller, tools included, at another root.
    return FIXTURE_ROOT / name / "issues.json"


def load_repo(name: str) -> Repo:
    """Load ``FIXTURE_ROOT/<name>/issues.json``; an unknown name raises UnknownRepoError."""
    path = fixture_path(name)
    if not path.is_file():
        raise UnknownRepoError(f"no recorded repo {name!r} under {FIXTURE_ROOT}")
    return Repo.model_validate_json(path.read_text())
