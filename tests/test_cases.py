from contextlib import nullcontext
from pathlib import Path

import pytest
from pydantic import ValidationError

from bakeoff.cases import Case, Injection, load_cases
from bakeoff.contract import Theme

CASES = Path(__file__).parent / "fixtures" / "cases.yaml"


def test_load_cases_reads_a_labelled_case_from_yaml():
    [case] = load_cases(CASES)
    assert (case.name, case.repo, case.top_issues) == ("tiny-basics", "tiny", [1])
    assert case.themes[1] == Theme(name="Feature requests", issues=[2])
    # YAML reads the `2:` key as an integer, so labels are keyed by issue number as they are.
    assert case.labels == {2: ["enhancement"]}
    assert case.injection == Injection(issue=2, forbidden_label="urgent")
    # Left out of the file, so it defaults to empty.
    assert case.duplicates == []


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
