import pytest

from experiment import calculate_reward
from experiment_config import ExperimentConfig, PolicyConfig, RewardConfig, RunConfig
from policy import schedule_parameters


def test_reward_matches_paper_run_implementation():
    config = ExperimentConfig(
        run=RunConfig(problem_start=0, problem_stop=1, skip_problem_ids=()),
        reward=RewardConfig(
            pedagogical_weight=0.3,
            code_runs_bonus=0.1,
            repeated_action_penalty=-0.1,
        ),
    )
    result = calculate_reward(
        coding_score=0.5,
        previous_coding_score=0.0,
        code_runs=True,
        student_level=3,
        tutor_level=3,
        leakage_detected=False,
        action="CONCEPTUAL_HINT",
        previous_action="CONCEPTUAL_HINT",
        config=config,
    )

    # 0.7 * 0.5 + 0.3 * 2 + 0.1 - 0.1
    assert result.reward == pytest.approx(0.95)
    assert result.student_success == 0.5
    assert result.pedagogical_quality == 2.0


def test_unchanged_code_score_produces_zero_student_success():
    config = ExperimentConfig(
        run=RunConfig(problem_start=0, problem_stop=1, skip_problem_ids=())
    )
    result = calculate_reward(
        coding_score=0.5,
        previous_coding_score=0.5,
        code_runs=True,
        student_level=2,
        tutor_level=2,
        leakage_detected=False,
        action="SOCRATIC_PROBE",
        previous_action="NONE",
        config=config,
    )

    assert result.student_success == 0.0
    assert result.reward == pytest.approx(0.7)


def test_temperature_reaches_zero_but_epsilon_remains():
    config = PolicyConfig(
        epsilon=0.1,
        initial_temperature=2.0,
        temperature_decay_fraction=0.6,
    )

    early_epsilon, early_temperature = schedule_parameters(0, 200, config)
    late_epsilon, late_temperature = schedule_parameters(199, 200, config)

    assert early_epsilon == late_epsilon == 0.1
    assert early_temperature == 2.0
    assert late_temperature == 0.0
