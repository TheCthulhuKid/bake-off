"""Where an eval's results came from: the prompt text, the code checkout and each impl's size."""

import hashlib
import importlib.util
import json
import subprocess
from pathlib import Path

from bakeoff.impls import IMPLS
from bakeoff.prompt import REPORT_PROMPT, SYSTEM_PROMPT, user_prompt
from bakeoff.settings import PROJECT_ROOT
from bakeoff.tools import TOOLS


def prompt_hash() -> str:
    """A short SHA-256 of every prompt text the model sees, tool docstrings included."""
    texts = [SYSTEM_PROMPT, user_prompt("{repo}"), REPORT_PROMPT, *(tool.__doc__ for tool in TOOLS)]
    return hashlib.sha256(json.dumps(texts).encode()).hexdigest()[:12]


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
