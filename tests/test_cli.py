import json
from pathlib import Path

import pytest
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


@pytest.fixture
def evaluated(pydanticai_model, langgraph_model, anthropic_model, tmp_path):
    """One eval of the tiny case by every impl: its output and the results files it saved."""
    out = tmp_path / "results"
    args = ["eval", "--repeats", "1", "--cases", str(CASES), "--out", str(out)]
    result = CliRunner().invoke(main, args)
    assert result.exit_code == 0, result.output
    return result.output, [str(path) for impl in IMPLS for path in out.glob(f"*-{impl}.json")]


def test_eval_saves_one_results_file_per_impl(evaluated):
    output, files = evaluated
    assert output.count(": ok (") == 3 and len(files) == 3
    for path in files:
        [record] = load_eval(Path(path)).records
        assert (record.case, record.schema_valid) == ("tiny-basics", True)


def test_report_renders_the_files_and_refuses_a_case_twice(evaluated):
    _, files = evaluated
    printed = CliRunner().invoke(main, ["report", *files])
    assert printed.exit_code == 0, printed.output
    # The report needs only the files: a row per impl in each table.
    rows = [line for line in printed.output.splitlines() if line.startswith("| anthropic |")]
    assert len(rows) == 4
    # The case doesn't expect an empty report, so "Stayed empty" has no data.
    assert "| anthropic | 1 | 100% | 100% | 100% | n/a | 0 | 0 | 0 |" in printed.output
    # Duplicates are unlabelled and nothing was judged, so those columns have no data.
    assert "| anthropic | n/a | n/a | 100% | 100% | 0 | n/a |" in printed.output
    twice = CliRunner().invoke(main, ["report", files[0], files[0]])
    assert twice.exit_code != 0
    assert "cases in more than one file: ['tiny-basics']" in twice.output


def test_rescore_writes_new_files_and_refuses_existing_or_repeated_names(evaluated, tmp_path):
    _, files = evaluated
    rescored = tmp_path / "rescored"
    args = ["rescore", *files, "--cases", str(CASES), "--out", str(rescored)]
    assert CliRunner().invoke(main, args).exit_code == 0
    assert load_eval(rescored / Path(files[0]).name) == load_eval(Path(files[0]))
    existing = CliRunner().invoke(main, args)
    assert existing.exit_code != 0 and "already exists" in existing.output
    repeated = CliRunner().invoke(
        main, ["rescore", files[0], files[0], "--out", str(tmp_path / "r")]
    )
    assert repeated.exit_code != 0 and not (tmp_path / "r").exists()
    name = Path(files[0]).name
    assert f"files share a name, which their copies would too: ['{name}']" in repeated.output


# The fake models keep a run that wrongly starts offline, and show whether any request was sent.
@pytest.mark.parametrize(
    ("cases_text", "judge_cache", "error"),
    [
        ("- {name: stray, repo: tiny, top_issues: [9]}\n", None, "stray: issues not in tiny: [9]"),
        ("- {name: fine, repo: tiny}\n", "not json", "judge-cache.json is not a judge cache"),
    ],
    ids=["bad cases", "bad judge cache"],
)
def test_eval_stops_before_any_run_on_bad_cases_or_a_bad_judge_cache(
    pydanticai_model,
    langgraph_model,
    anthropic_model,
    tmp_path,
    monkeypatch,
    cases_text,
    judge_cache,
    error,
):
    cases = tmp_path / "cases.yaml"
    cases.write_text(cases_text)
    args = ["eval", "--cases", str(cases), "--out", str(tmp_path / "results")]
    if judge_cache is not None:
        monkeypatch.setattr("bakeoff.cli.EVALS", tmp_path)
        (tmp_path / "judge-cache.json").write_text(judge_cache)
        args.append("--judge")
    result = CliRunner().invoke(main, args)
    assert result.exit_code != 0 and error in result.output
    assert anthropic_model.sent == [] and not (tmp_path / "results").exists()


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
    assert result.exit_code != 0 and "Aborted" in result.output
    assert "interrupted during second, dropping its 0 finished runs" in result.output
    [path] = out.glob("*-pydanticai.json")
    assert [record.case for record in load_eval(path).records] == ["first"]
