from pathlib import Path

import pandas as pd
import pytest


def test_submitted_run_artifacts_remain_intact():
    root = Path(__file__).resolve().parents[1]
    run = root / "outputs" / "20260315_gpt_4_1_beginner_test2"
    memory = pd.read_csv(run / "checkpoints" / "memory.csv")
    interaction_ids = {
        int(path.stem.removeprefix("problem_"))
        for path in (run / "interactions").glob("problem_*.json")
    }

    assert len(memory) == 636
    assert memory["problem"].nunique() == 190
    assert len(interaction_ids) == 196
    assert set(range(200)) - interaction_ids == {102, 126, 181, 182}

    action_counts = memory["action"].value_counts().to_dict()
    assert action_counts == {
        "CONCEPTUAL_HINT": 275,
        "SOCRATIC_PROBE": 204,
        "STRUCTURAL_SCAFFOLD": 157,
    }
    first_reward_bin = memory[memory["problem"].between(0, 19)]["reward"].mean()
    last_reward_bin = memory[memory["problem"].between(180, 199)]["reward"].mean()
    assert first_reward_bin == pytest.approx(0.7109, abs=0.0001)
    assert last_reward_bin == pytest.approx(0.9076, abs=0.0001)
