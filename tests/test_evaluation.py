from evaluation import evaluate_submission


PROBLEM = {
    "entry_point": "Solution().answer()",
    "test": "assert candidate == 1",
}


def test_evaluation_returns_full_score_for_valid_submission():
    result = evaluate_submission(
        PROBLEM,
        "",
        "class Solution:\n    def answer(self):\n        return 1",
        timeout_seconds=2,
    )

    assert result.status == "passed"
    assert result.code_runs is True
    assert result.score == 1.0


def test_infinite_loop_times_out_and_next_submission_still_runs():
    stuck = evaluate_submission(
        PROBLEM,
        "",
        "class Solution:\n    def answer(self):\n        while True:\n            pass",
        timeout_seconds=0.5,
    )
    recovered = evaluate_submission(
        PROBLEM,
        "",
        "class Solution:\n    def answer(self):\n        return 1",
        timeout_seconds=2,
    )

    assert stuck.status == "timeout"
    assert stuck.score == 0.0
    assert recovered.status == "passed"
    assert recovered.score == 1.0
