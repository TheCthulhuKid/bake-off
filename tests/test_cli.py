from click.testing import CliRunner

from bakeoff.cli import main


def test_cli_help_runs():
    result = CliRunner().invoke(main, ["--help"])
    assert result.exit_code == 0
    assert "triage" in result.output
