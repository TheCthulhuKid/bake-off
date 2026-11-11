"""Where an eval's results came from: the prompts, cases and fixtures, the checkout, impl sizes."""

import hashlib
import importlib.util
import json
import subprocess
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from bakeoff.cases import Case
from bakeoff.contract import TriageReport
from bakeoff.fixtures import fixture_path
from bakeoff.impls import IMPLS
from bakeoff.prompt import REPORT_PROMPT, SYSTEM_PROMPT, user_prompt
from bakeoff.settings import PROJECT_ROOT
from bakeoff.tools import TOOLS


def prompt_hash() -> str:
    """A short hash of every prompt text the model sees: tool docstrings and report schema too."""
    texts = [SYSTEM_PROMPT, user_prompt("{repo}"), REPORT_PROMPT, *(tool.__doc__ for tool in TOOLS)]
    return _short_hash([*texts, TriageReport.model_json_schema()])


def cases_hash(cases: Iterable[Case]) -> str:
    """A short hash of the cases' labels, so results scored against other labels stand out."""
    return _short_hash([case.model_dump(mode="json") for case in cases])


def fixture_hash(name: str) -> str:
    """A short hash of the fixture's file, which changes if it is re-recorded or edited."""
    return hashlib.sha256(fixture_path(name).read_bytes()).hexdigest()[:12]


def _short_hash(data: Any) -> str:
    # Sorted keys, so equal content always hashes alike.
    return hashlib.sha256(json.dumps(data, sort_keys=True).encode()).hexdigest()[:12]


def git_sha(root: Path = PROJECT_ROOT) -> str | None:
    """The checkout's commit, with ``-dirty`` if tracked files have changed; ``None`` outside git.

    Untracked files don't count, so new results files don't mark every later run dirty.
    """
    try:
        sha = _git(root, "rev-parse", "HEAD")
        changed = _git(root, "status", "--porcelain", "--untracked-files=no")
    except (OSError, subprocess.CalledProcessError):
        return None
    return f"{sha}-dirty" if changed else sha


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def code_lines(impl: str) -> tuple[int, int]:
    """Total and non-blank lines in ``impl``'s module, found without importing its framework."""
    origin = importlib.util.find_spec(IMPLS[impl]).origin
    lines = Path(origin).read_text(encoding="utf-8").splitlines()
    return len(lines), sum(bool(line.strip()) for line in lines)
