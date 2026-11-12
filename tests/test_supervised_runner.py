import json

import pandas as pd
from langchain.messages import AIMessage, HumanMessage

from experiment import AgentBundle, ExperimentRunner
from experiment_config import (
    EvaluationConfig,
    ExperimentConfig,
    PathConfig,
    PolicyConfig,
    RunConfig,
)


class FakeTutor:
    def update_system_message(self, _message):
        pass

    def invoke(self, _message):
        return AIMessage(content="Consider what the method should return.")


class FakeStudent:
    def __init__(self, code):
        self.code = code
        self.conversation_history = []

    def invoke(self, _message):
        return HumanMessage(
            content=json.dumps({"conversation": "I will try this.", "python_code": self.code})
        )


class FakeStudentJudge:
    def invoke(self, _message):
        return AIMessage(
            content=json.dumps(
                {
                    "student_level": 2,
                    "student_level_explanation": "procedural",
                    "student_changed_problem": False,
                }
            )
        )


class FakeTutorJudge:
    def invoke(self, _message):
        return AIMessage(
            content=json.dumps(
                {
                    "tutor_level": 2,
                    "tutor_level_explanation": "procedural",
                    "leakage_detected": False,
                    "leakage_explanation": "no solution",
                }
            )
        )


class FakeFactory:
    def create(self, problem):
        if problem["task_id"] == "stuck":
            code = "class Solution:\n    def answer(self):\n        while True:\n            pass"
        else:
            code = "class Solution:\n    def answer(self):\n        return 1"
        return AgentBundle(
            tutor=FakeTutor(),
            student=FakeStudent(code),
            student_judge=FakeStudentJudge(),
            tutor_judge=FakeTutorJudge(),
        )


def test_mock_stuck_problem_does_not_block_following_problem(tmp_path):
    dataset_path = tmp_path / "dataset.gz"
    manifest_path = tmp_path / "manifest.csv"
    dataset_path.write_bytes(b"dataset")
    manifest_path.write_text("manifest", encoding="utf-8")
    config = ExperimentConfig(
        run=RunConfig(
            run_id="mock",
            problem_start=0,
            problem_stop=2,
            default_batch_size=1,
            skip_problem_ids=(),
        ),
        policy=PolicyConfig(min_rows_before_training=10, retrain_every=3),
        evaluation=EvaluationConfig(code_timeout_seconds=0.5, max_turns=1),
        paths=PathConfig(
            dataset=dataset_path,
            manifest=manifest_path,
            output_root=tmp_path / "outputs",
            secrets_file=tmp_path / "unused.env",
        ),
    )
    problems = pd.DataFrame(
        [
            {
                "scheduled_problem_index": 0,
                "task_id": "stuck",
                "difficulty": "Easy",
                "problem_description": "Return one.",
                "starter_code": "class Solution:\n    def answer(self):",
                "entry_point": "Solution().answer()",
                "test": "assert candidate == 1",
            },
            {
                "scheduled_problem_index": 1,
                "task_id": "normal",
                "difficulty": "Easy",
                "problem_description": "Return one.",
                "starter_code": "class Solution:\n    def answer(self):",
                "entry_point": "Solution().answer()",
                "test": "assert candidate == 1",
            },
        ]
    )
    runner = ExperimentRunner(config, problems, agent_factory=FakeFactory())

    results = runner.run_next(batch_size=2)
    status = runner.status().set_index("problem_id")["status"].to_dict()
    first_interaction = json.loads(
        (config.run_path / "interactions" / "problem_0.json").read_text(encoding="utf-8")
    )

    assert results[0]["solved"] is False
    assert results[1]["solved"] is True
    assert status == {0: "completed", 1: "completed"}
    assert first_interaction[1]["code_evaluation"]["status"] == "timeout"
