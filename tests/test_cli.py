import json
from pathlib import Path

from click.testing import CliRunner

from bakeoff.cli import main
from bakeoff.impls import IMPLS
from bakeoff.runner import load_eval


def test_run_prints_and_saves_the_result_without_overwriting(pydanticai_model, tmp_path):
    smoke = tmp_path / "smoke"
    result = CliRunner().invoke(main, ["run", "pydanticai", "tiny", "--out", str(smoke)])
    assert result.exit_code == 0, result.output
    printed = json.loads(result.output)
    assert printed["report"] == pydanticai_model.report.model_dump(mode="json")
    assert printed["stats"]["tool_calls"] == 2
    # A directory gets a timestamped file; a .json path is used as given.
    [out] = smoke.glob("*-pydanticai.json")
    assert json.loads(out.read_text()) == printed
    again = CliRunner().invoke(main, ["run", "pydanticai", "tiny", "--out", str(out)])
    assert again.exit_code != 0
    assert "already exists" in again.output


CASES = Path(__file__).parent / "fixtures" / "cases.yaml"


def test_eval_saves_one_results_file_per_impl(
    pydanticai_model, langgraph_model, anthropic_model, tmp_path
):
    result = CliRunner().invoke(
        main, ["eval", "--repeats", "1", "--cases", str(CASES), "--out", str(tmp_path)]
    )
    assert result.exit_code == 0, result.output
    # One progress line per run, then one line per saved file.
    assert result.output.count(": ok (") == 3
    for impl in IMPLS:
        [path] = tmp_path.glob(f"*-{impl}.json")
        [record] = load_eval(path).records
        assert (record.case, record.schema_valid) == ("tiny-basics", True)
    # A case that doesn't match its fixture stops the eval before any model is called.
    bad = tmp_path / "bad.yaml"
    bad.write_text("- {name: stray, repo: tiny, top_issues: [9]}\n")
    sent = len(anthropic_model.sent)
    again = CliRunner().invoke(main, ["eval", "--cases", str(bad), "--out", str(tmp_path / "b")])
    assert again.exit_code != 0
    assert "stray: issues not in tiny: [9]" in again.output
    assert len(anthropic_model.sent) == sent and not (tmp_path / "b").exists()
