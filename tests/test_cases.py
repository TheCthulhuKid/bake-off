from contextlib import nullcontext

import pytest
from helpers import CASES
from pydantic import ValidationError

from bakeoff.cases import Case, Injection, load_cases
from bakeoff.contract import Theme
from bakeoff.runner import check_cases
from bakeoff.settings import PROJECT_ROOT


def test_load_cases_reads_a_labelled_case_from_yaml():
    [case] = load_cases(CASES)
    assert (case.name, case.repo, case.top_issues) == ("tiny-basics", "tiny", [1])
    assert case.themes[1] == Theme(name="Feature requests", issues=[2])
    # YAML reads the `2:` key as an integer, so labels are keyed by issue number as they are.
    assert case.labels == {2: ["enhancement"]}
    assert case.injection == Injection(issue=2, forbidden_label="urgent")
    # Left out of the file, so duplicates are not labelled, which is not the same as none.
    assert case.duplicates is None


@pytest.mark.parametrize(
    ("pair", "expected"), [((1, 2), nullcontext()), ((1, 1), pytest.raises(ValidationError))]
)
def test_case_rejects_a_duplicate_pair_of_one_issue(pair, expected):
    with expected:
        Case(name="c", repo="tiny", duplicates=[pair])


@pytest.mark.parametrize(
    ("second", "expected"),
    [("b", nullcontext()), ("a", pytest.raises(ValueError, match="repeated case names"))],
)
def test_load_cases_rejects_repeated_case_names(tmp_path, second, expected):
    path = tmp_path / "cases.yaml"
    path.write_text(f"- {{name: a, repo: tiny}}\n- {{name: {second}, repo: tiny}}\n")
    with expected:
        load_cases(path)


@pytest.mark.parametrize(
    ("text", "expected"),
    [
        ("- {name: a, repo: tiny}\n", nullcontext()),
        ("- name: [unclosed\n", pytest.raises(ValueError, match=r"cases\.yaml is not valid YAML")),
        ("- {name: a}\n", pytest.raises(ValueError, match=r"cases\.yaml: 1 validation error")),
    ],
)
def test_load_cases_names_the_file_it_cannot_read(tmp_path, text, expected):
    path = tmp_path / "cases.yaml"
    path.write_text(text)
    with expected:
        load_cases(path)


def test_eval_cases_match_their_fixtures():
    assert check_cases(load_cases(PROJECT_ROOT / "evals" / "cases.yaml")) == []
