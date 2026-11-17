import re

import pytest
from helpers import eval_run

from bakeoff.report import IncompatibleRuns, combine, render


@pytest.mark.parametrize(
    ("case", "changes", "refused"),
    [
        ("tiny-later", {}, None),
        ("tiny-later", {"prompt_hash": "0123456789ab"}, "anthropic: files differ in prompt_hash"),
        ("tiny-later", {"fixture_hashes": {"tiny": "0123456789ab"}}, "different versions of tiny"),
        ("tiny-later", {"timeout": 60}, "anthropic: files differ in run limits"),
        ("tiny-first", {}, "cases in more than one file: ['tiny-first']"),
    ],
)
def test_report_combines_an_impl_s_files_and_refuses_mismatched_ones(case, changes, refused):
    runs = [eval_run("tiny-first", 3), eval_run(case, 4, **changes)]
    if refused:
        with pytest.raises(IncompatibleRuns, match=re.escape(refused)):
            combine(runs)
        return
    [combined] = combine(runs)
    assert [record.case for record in combined.records] == ["tiny-first", "tiny-later"]
    tables = render(runs)
    # Each file keeps its provenance row; the scores share one row per impl.
    assert tables.count("| anthropic | 2026-11-16 10:24 |") == 2
    assert "| anthropic | 2 | 100% |" in tables
    assert "| 3.5 |" in tables
