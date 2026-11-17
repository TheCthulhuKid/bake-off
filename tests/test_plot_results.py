from helpers import eval_run, load_script

from bakeoff.scoring import Scores

plot_results = load_script("plot_results")


def test_case_scores_keep_each_repeat_in_order_and_skip_unscored_runs():
    record = eval_run("tiny", 3).records[0]
    scored = [
        record.model_copy(update={"case": case, "repeat": repeat, "scores": Scores(**scores)})
        for case, repeat, scores in [
            ("tiny-b", 1, {"duplicate_recall": 0.5}),
            ("tiny-a", 0, {"duplicate_recall": 1.0}),
            ("tiny-b", 0, {"duplicate_recall": 0.0}),
            ("tiny-c", 0, {}),
        ]
    ]
    run = eval_run("tiny", 3, records=scored)

    assert plot_results.case_scores(run, "duplicate_recall") == {
        "tiny-a": [1.0],
        "tiny-b": [0.0, 0.5],
    }
