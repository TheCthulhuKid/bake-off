import subprocess
from pathlib import Path

from bakeoff.cases import Case
from bakeoff.contract import TriageReport
from bakeoff.provenance import cases_hash, code_lines, git_sha, prompt_hash
from bakeoff.tools import TOOLS


def test_prompt_hash_changes_with_a_tool_docstring_or_the_report_schema(monkeypatch):
    before = prompt_hash()
    # Docstrings are the model-facing tool descriptions, so they are prompt text too.
    monkeypatch.setattr(TOOLS[0], "__doc__", "A different description.")
    redescribed = prompt_hash()
    assert redescribed != before and len(before) == 12
    # Every framework sends the report schema to the model, so it counts as well.
    monkeypatch.setattr(TriageReport, "model_json_schema", classmethod(lambda cls: {}))
    assert prompt_hash() != redescribed


def test_cases_hash_changes_when_a_label_changes():
    case = Case(name="c", repo="tiny", labels={1: ["bug"]})
    assert cases_hash([case]) == cases_hash([case.model_copy()])
    assert cases_hash([case]) != cases_hash([case.model_copy(update={"labels": {1: ["crash"]}})])


def test_git_sha_is_dirty_only_for_changed_tracked_files(tmp_path):
    def git(*args):
        return subprocess.run(
            ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
            cwd=tmp_path,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()

    assert git_sha(tmp_path) is None
    git("init", "-q")
    (tmp_path / "tracked.txt").write_text("one\n")
    git("add", "tracked.txt")
    git("-c", "commit.gpgsign=false", "commit", "-q", "-m", "first")
    sha = git("rev-parse", "HEAD")
    # A new results file is untracked, so it leaves the checkout clean.
    (tmp_path / "untracked.json").write_text("{}")
    assert git_sha(tmp_path) == sha
    (tmp_path / "tracked.txt").write_text("two\n")
    assert git_sha(tmp_path) == f"{sha}-dirty"


def test_code_lines_counts_an_impl_module_s_lines():
    lines = Path("src/bakeoff/impls/anthropic_impl.py").read_text().splitlines()
    total, non_blank = code_lines("anthropic")
    assert total == len(lines) and 0 < non_blank < total
