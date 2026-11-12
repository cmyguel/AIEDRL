from pathlib import Path

from utils.data import load_experiment_snapshot


def test_tracked_snapshot_contains_original_200_plus_extension():
    root = Path(__file__).resolve().parents[1]
    frame = load_experiment_snapshot(
        root / "data" / "experiment_problems_2000.jsonl.gz",
        root / "data" / "experiment_problems_2000_manifest.csv",
    )

    assert len(frame) == 2000
    assert frame["scheduled_problem_index"].tolist() == list(range(2000))
    assert frame["task_id"].nunique() == 2000
    assert frame.iloc[0]["task_id"] == "reverse-vowels-of-a-string"
    assert frame.iloc[199]["scheduled_problem_index"] == 199
