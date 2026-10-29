import json

from click.testing import CliRunner

from bakeoff.cli import main


def test_cli_help_runs():
    result = CliRunner().invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "triage" in result.output


def test_run_prints_and_saves_the_result_without_overwriting(pydanticai_model, tmp_path):
    out = tmp_path / "smoke" / "run.json"
    result = CliRunner().invoke(main, ["run", "pydanticai", "tiny", "--out", str(out)])
    assert result.exit_code == 0, result.output
    printed = json.loads(result.output)
    assert printed["report"] == pydanticai_model.report.model_dump(mode="json")
    assert printed["stats"]["tool_calls"] == 2
    assert json.loads(out.read_text()) == printed
    again = CliRunner().invoke(main, ["run", "pydanticai", "tiny", "--out", str(out)])
    assert again.exit_code != 0
    assert "already exists" in again.output
