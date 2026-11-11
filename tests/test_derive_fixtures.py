import importlib.util
import shutil
from pathlib import Path

import pytest
from click.testing import CliRunner

from bakeoff.fixtures import Repo, load_repo
from bakeoff.settings import PROJECT_ROOT

SCRIPT = PROJECT_ROOT / "scripts" / "derive_fixtures.py"
spec = importlib.util.spec_from_file_location("derive_fixtures", SCRIPT)
derive_fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(derive_fixtures)

RECORDED = PROJECT_ROOT / "evals" / "repos"


@pytest.fixture
def root(tmp_path, monkeypatch):
    """An empty fixture root that every fixture lookup, the script's included, uses."""
    root = tmp_path / "repos"
    monkeypatch.setattr("bakeoff.fixtures.FIXTURE_ROOT", root)
    return root


def derive(spec_text: str, spec_path: Path):
    spec_path.write_text(spec_text)
    return CliRunner().invoke(derive_fixtures.main, ["--spec", str(spec_path)])


def test_derive_applies_the_steps_to_a_copy_of_the_base(root, tmp_path):
    shutil.copytree(Path(__file__).parent / "fixtures" / "tiny", root / "tiny")
    result = derive(
        """
- name: tiny-derived
  base: tiny
  steps:
    - {step: plant, number: 90001, title: Planted, body: A planted issue., labels: [bug]}
    - {step: slice, issues: [90001, 1]}
    - {step: hide_labels, issues: [1]}
    - {step: inflate, number: 1, characters: 120}
    - {step: rewrite, number: 90001, title: Neu geschrieben}
""",
        tmp_path / "derived.yaml",
    )
    assert result.exit_code == 0, result.output
    derived, base = load_repo("tiny-derived"), load_repo("tiny")
    assert [issue.number for issue in derived.issues] == [1, 90001]
    assert (derived.issue(1).labels, derived.issue(90001).labels) == ([], ["bug"])
    body = derived.issue(1).body
    assert len(body) == 120 and body.startswith(base.issue(1).body)
    assert derived.issue(90001).title == "Neu geschrieben"
    assert derived.synthetic
    assert (derived.source, derived.recorded_at) == (base.source, base.recorded_at)


def test_derive_refuses_to_overwrite_a_recorded_fixture(root, tmp_path):
    shutil.copytree(Path(__file__).parent / "fixtures" / "tiny", root / "tiny")
    before = (root / "tiny" / "issues.json").read_bytes()
    result = derive(
        "- {name: tiny, base: tiny, steps: [{step: slice, issues: []}]}\n",
        tmp_path / "derived.yaml",
    )
    assert result.exit_code != 0 and "is a recorded fixture" in result.output
    assert (root / "tiny" / "issues.json").read_bytes() == before


def test_derived_fixtures_match_the_spec(root):
    recorded = [path.parent for path in RECORDED.glob("*/issues.json") if not _is_synthetic(path)]
    for directory in recorded:
        shutil.copytree(directory, root / directory.name)
    result = CliRunner().invoke(derive_fixtures.main, [])
    assert result.exit_code == 0, result.output
    names = {entry.name for entry in derive_fixtures.load_spec(derive_fixtures.SPEC)}
    committed = {path.parent.name for path in RECORDED.glob("*/issues.json") if _is_synthetic(path)}
    assert committed == names
    for name in names:
        rebuilt = (root / name / "issues.json").read_bytes()
        assert rebuilt == (RECORDED / name / "issues.json").read_bytes(), name


def _is_synthetic(path: Path) -> bool:
    return Repo.model_validate_json(path.read_text(encoding="utf-8")).synthetic
