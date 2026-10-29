from pathlib import Path

import pytest

from bakeoff.fixtures import load_repo

FIXTURES = Path(__file__).parent / "fixtures"


def test_load_repo_reads_fixture_and_rejects_unknown_name():
    repo = load_repo("tiny", root=FIXTURES)
    assert [issue.number for issue in repo.issues] == [1, 2]
    assert repo.issue(1).comments[0].author == "alice"
    assert repo.issue(99) is None
    with pytest.raises(FileNotFoundError):
        load_repo("missing", root=FIXTURES)
