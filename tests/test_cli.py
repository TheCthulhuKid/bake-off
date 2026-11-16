import json
from pathlib import Path

from click.testing import CliRunner

from bakeoff import runner
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
    files = []
    for impl in IMPLS:
        [path] = tmp_path.glob(f"*-{impl}.json")
        [record] = load_eval(path).records
        assert (record.case, record.schema_valid) == ("tiny-basics", True)
        files.append(str(path))
    # The report needs only the files: a row per impl in each table.
    printed = CliRunner().invoke(main, ["report", *files])
    assert printed.exit_code == 0, printed.output
    rows = [line for line in printed.output.splitlines() if line.startswith("| anthropic |")]
    assert len(rows) == 4
    # The case doesn't expect an empty report, so "Stayed empty" has no data.
    assert "| anthropic | 1 | 100% | 100% | 100% | n/a | 0 | 0 | 0 |" in printed.output
    # Duplicates are unlabelled and nothing was judged, so those columns have no data.
    assert "| anthropic | n/a | n/a | 100% | 100% | 0 | n/a |" in printed.output
    # One impl's files share a row only if they can: the same case twice is refused.
    twice = CliRunner().invoke(main, ["report", files[0], files[0]])
    assert twice.exit_code != 0
    assert "cases in more than one file: ['tiny-basics']" in twice.output
    # A rescore writes new files under the same names, offline, and never overwrites them.
    rescored = tmp_path / "rescored"
    args = ["rescore", *files, "--cases", str(CASES), "--out", str(rescored)]
    assert CliRunner().invoke(main, args).exit_code == 0
    assert load_eval(rescored / Path(files[0]).name) == load_eval(Path(files[0]))
    again = CliRunner().invoke(main, args)
    assert again.exit_code != 0
    assert "already exists" in again.output
    # A case that doesn't match its fixture stops the eval before any model is called.
    bad = tmp_path / "bad.yaml"
    bad.write_text("- {name: stray, repo: tiny, top_issues: [9]}\n")
    sent = len(anthropic_model.sent)
    again = CliRunner().invoke(main, ["eval", "--cases", str(bad), "--out", str(tmp_path / "b")])
    assert again.exit_code != 0
    assert "stray: issues not in tiny: [9]" in again.output
    assert len(anthropic_model.sent) == sent and not (tmp_path / "b").exists()


def test_eval_saves_the_whole_cases_of_an_interrupted_eval(pydanticai_model, tmp_path, monkeypatch):
    two = tmp_path / "two.yaml"
    two.write_text("- {name: first, repo: tiny}\n- {name: second, repo: tiny}\n")
    run_case = runner.run_case

    def interrupt_the_second(impl, case, repeat, **kwargs):
        if case.name == "second":
            raise KeyboardInterrupt
        return run_case(impl, case, repeat, **kwargs)

    monkeypatch.setattr(runner, "run_case", interrupt_the_second)
    out = tmp_path / "results"
    args = [
        "eval",
        "--impl",
        "pydanticai",
        "--repeats",
        "1",
        "--cases",
        str(two),
        "--out",
        str(out),
    ]
    result = CliRunner().invoke(main, args)
    # Ctrl-C still aborts, after the finished case is saved.
    assert result.exit_code != 0 and "Aborted" in result.output
    assert "interrupted during second, dropping its 0 finished runs" in result.output
    [path] = out.glob("*-pydanticai.json")
    assert [record.case for record in load_eval(path).records] == ["first"]
