from contextlib import nullcontext

import pytest

from bakeoff.fixtures import UnknownRepoError, load_repo


def test_load_repo_reads_fixture_and_rejects_unknown_name(tiny_root):
    repo = load_repo("tiny")
    assert [issue.number for issue in repo.issues] == [1, 2]
    assert repo.issue(1).comments[0].author == "alice"
    assert repo.issue(99) is None
    with pytest.raises(UnknownRepoError):
        load_repo("missing")


# From the test root, "../fixtures/tiny" is the same fixture as "tiny", so this checks the name,
# not whether the file exists.
@pytest.mark.parametrize(
    ("name", "expected"),
    [("tiny", nullcontext()), ("../fixtures/tiny", pytest.raises(UnknownRepoError))],
)
def test_load_repo_rejects_a_name_outside_the_fixture_root(tiny_root, name, expected):
    with expected:
        load_repo(name)
