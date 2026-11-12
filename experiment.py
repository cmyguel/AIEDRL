"""Supervised, checkpointed execution of the AIEDRL tutoring experiment."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Protocol

import pandas as pd
from dotenv import load_dotenv
from langchain.messages import AIMessage, HumanMessage

from agents import Student, StudentJudge, Tutor, TutorJudge
from evaluation import evaluate_submission
from experiment_config import ExperimentConfig
from policy import RewardPolicy, schedule_parameters
from prompts.judge.baseline import STUDENT_JUDGE_PROMPT, TUTOR_JUDGE_PROMPT
from prompts.student.baseline import CODING_BEGINNER_STUDENT_PROMPT
from prompts.tutor.baseline import CODING_PRACTICE_PROMPT, TUTOR_PEDAGOGICAL_MOVES_PROMPT
from run_store import RunStore
from utils.code_processing import get_code_definitions
from utils.data import load_experiment_snapshot


@dataclass(frozen=True)
class RewardBreakdown:
    """Auditable components of the implemented paper-run reward."""

    reward: float
    student_success: float
    pedagogical_quality: float
    scaffolding: float
    code_runs_bonus: float
    repetition_penalty: float


@dataclass
class AgentBundle:
    tutor: Any
    student: Any
    student_judge: Any
    tutor_judge: Any


class AgentFactory(Protocol):
    """Factory seam used by offline tests to avoid live API calls."""

    def create(self, problem: Mapping[str, Any]) -> AgentBundle: ...


class DefaultAgentFactory:
    """Create the four OpenAI-backed agents used in the submitted experiment."""

    def __init__(self, config: ExperimentConfig):
        self.config = config

    def create(self, problem: Mapping[str, Any]) -> AgentBundle:
        tutor_prompt, student_prompt, tutor_judge_prompt, student_judge_prompt = (
            format_agent_prompts(
                problem,
                student_programming_level=self.config.run.student_programming_level,
            )
        )
        model_config = self.config.models
        common = {
            "request_timeout_seconds": model_config.request_timeout_seconds,
            "max_retries": model_config.max_retries,
        }
        return AgentBundle(
            tutor=Tutor(tutor_prompt, model_name=model_config.tutor, **common),
            student=Student(student_prompt, model_name=model_config.student, **common),
            student_judge=StudentJudge(
                student_judge_prompt,
                model_name=model_config.student_judge,
                **common,
            ),
            tutor_judge=TutorJudge(
                tutor_judge_prompt,
                model_name=model_config.tutor_judge,
                **common,
            ),
        )


def format_agent_prompts(
    problem: Mapping[str, Any],
    student_programming_level: str = "beginner",
) -> tuple[str, str, str, str]:
    """Render the exact prompt families used by the paper-run notebook."""

    values = {
        "problem_description": problem["problem_description"],
        "starter_code": problem["starter_code"],
        "programming_level": student_programming_level,
    }
    return (
        CODING_PRACTICE_PROMPT.format(**values),
        CODING_BEGINNER_STUDENT_PROMPT.format(**values),
        TUTOR_JUDGE_PROMPT.format(**values),
        STUDENT_JUDGE_PROMPT.format(**values),
    )


def calculate_reward(
    *,
    coding_score: float,
    previous_coding_score: float,
    code_runs: bool,
    student_level: int,
    tutor_level: int,
    leakage_detected: bool,
    action: str,
    previous_action: str,
    config: ExperimentConfig,
) -> RewardBreakdown:
    """Calculate the implemented reward without silently changing its semantics.

    Student success is the current code score only when that score changes; it is
    not the score delta.  This reproduces the notebook implementation and is
    documented as a limitation rather than corrected during replication.
    """

    scaffolding = 2 - abs(int(student_level) - int(tutor_level))
    pedagogical_quality = -1.0 if leakage_detected else float(scaffolding)
    student_success = float(coding_score) if coding_score != previous_coding_score else 0.0
    code_bonus = config.reward.code_runs_bonus if code_runs else 0.0
    repetition_penalty = (
        config.reward.repeated_action_penalty if action == previous_action else 0.0
    )
    pedagogical_weight = config.reward.pedagogical_weight
    reward = (
        (1 - pedagogical_weight) * student_success
        + pedagogical_weight * pedagogical_quality
        + code_bonus
        + repetition_penalty
    )
    return RewardBreakdown(
        reward=float(reward),
        student_success=student_success,
        pedagogical_quality=pedagogical_quality,
        scaffolding=float(scaffolding),
        code_runs_bonus=float(code_bonus),
        repetition_penalty=float(repetition_penalty),
    )


class ExperimentRunner:
    """Human-supervised runner with durable retry, skip, and resume behavior."""

    def __init__(
        self,
        config: ExperimentConfig,
        problems: pd.DataFrame,
        *,
        agent_factory: AgentFactory | None = None,
        policy: RewardPolicy | None = None,
    ):
        self.config = config
        self.problem_ids = list(range(config.run.problem_start, config.run.problem_stop))
        self.problems = _index_problems(problems)
        missing = [problem_id for problem_id in self.problem_ids if problem_id not in self.problems]
        if missing:
            raise ValueError(f"dataset snapshot is missing configured problem IDs: {missing[:10]}")

        preexisting = config.run_path.exists() and any(config.run_path.iterdir())
        if preexisting and not (config.run_path / "run_metadata.json").exists():
            raise RuntimeError(
                f"Refusing to adopt nonempty directory without run metadata: {config.run_path}"
            )

        self.policy = policy or RewardPolicy(config.policy)
        self.store = RunStore(config.run_path)
        self.store.load_policy_checkpoint(self.policy)
        self.store.reconcile_interrupted_attempts()
        self.agent_factory = agent_factory or DefaultAgentFactory(config)
        self.store.initialize_metadata(
            {**config.as_metadata(), "prompt_sha256": _prompt_hashes()},
            repo_root=Path(__file__).parent,
        )
        self._record_configured_skips()

    def status(self) -> pd.DataFrame:
        """Return one readable status row per configured problem."""

        return self.store.status_frame(self.problem_ids)

    def run_next(self, batch_size: int | None = None) -> list[dict[str, Any]]:
        """Run the next untouched problems; failed/interrupted problems require retry()."""

        requested = batch_size or self.config.run.default_batch_size
        if requested < 1:
            raise ValueError("batch_size must be at least 1")
        statuses = self.store.problem_statuses(self.problem_ids)
        pending = [problem_id for problem_id in self.problem_ids if statuses[problem_id] == "pending"]
        return [self._run_attempt(problem_id) for problem_id in pending[:requested]]

    def retry(self, problem_id: int) -> dict[str, Any]:
        """Start a fresh attempt for a failed or interrupted problem."""

        self._validate_problem_id(problem_id)
        status = self.store.problem_statuses([problem_id])[problem_id]
        if status not in {"failed", "interrupted"}:
            raise ValueError(f"problem {problem_id} has status {status!r}, not failed/interrupted")
        return self._run_attempt(problem_id)

    def skip(self, problem_id: int, reason: str) -> None:
        """Record an operator decision to stop retrying a problem."""

        self._validate_problem_id(problem_id)
        if not reason.strip():
            raise ValueError("a manual skip requires a reason")
        status = self.store.problem_statuses([problem_id])[problem_id]
        if status == "completed":
            raise ValueError(f"problem {problem_id} is already completed")
        self.store.append_event(
            problem_id=problem_id,
            attempt=None,
            status="skipped",
            reason=reason.strip(),
            details={"source": "operator"},
        )

    def _run_attempt(self, problem_id: int) -> dict[str, Any]:
        problem = self.problems[problem_id]
        attempt = self.store.next_attempt_number(problem_id)
        self.store.append_event(problem_id=problem_id, attempt=attempt, status="started")
        interactions: list[dict[str, Any]] = []
        try:
            result = self._run_episode(problem_id, attempt, problem, interactions)
            self.store.save_attempt(problem_id, attempt, interactions, completed=True)
            self.store.append_event(
                problem_id=problem_id,
                attempt=attempt,
                status="completed",
                reason=result["stop_reason"],
                details=result,
            )
            self.store.save_policy_checkpoint(self.policy)
            return result
        except KeyboardInterrupt:
            self.store.save_attempt(problem_id, attempt, interactions, completed=False)
            self.store.save_policy_checkpoint(self.policy)
            self.store.append_event(
                problem_id=problem_id,
                attempt=attempt,
                status="interrupted",
                reason="Operator interrupted the active attempt",
            )
            raise
        except Exception as error:
            interactions.append({"stop": {"error": f"{type(error).__name__}: {error}"}})
            self.store.save_attempt(problem_id, attempt, interactions, completed=False)
            self.store.save_policy_checkpoint(self.policy)
            self.store.append_event(
                problem_id=problem_id,
                attempt=attempt,
                status="failed",
                reason=f"{type(error).__name__}: {error}",
            )
            return {
                "problem_id": problem_id,
                "attempt": attempt,
                "status": "failed",
                "error": f"{type(error).__name__}: {error}",
            }

    def _run_episode(
        self,
        problem_id: int,
        attempt: int,
        problem: dict[str, Any],
        interactions: list[dict[str, Any]],
    ) -> dict[str, Any]:
        agents = self.agent_factory.create(problem)
        code_definitions = get_code_definitions(str(problem["starter_code"]))
        initial_content = json.dumps(
            {
                "conversation": "I will start working on this problem.",
                "python_code": problem["starter_code"],
            }
        )
        student_message = HumanMessage(content=initial_content)
        if hasattr(agents.student, "conversation_history"):
            agents.student.conversation_history.append(AIMessage(content=initial_content))
        interactions.append({"student_message": student_message})
        self.store.save_attempt(problem_id, attempt, interactions, completed=False)

        last_student_level = -1
        last_tutor_level = -1
        last_reward = -1.0
        last_action = "NONE"
        last_coding_score = 0.0
        stop_reason = "Max number of iterations"
        solved = False

        total_problems = self.config.run.problem_stop - self.config.run.problem_start
        schedule_index = problem_id - self.config.run.problem_start
        for turn_index in range(self.config.evaluation.max_turns):
            epsilon, temperature = schedule_parameters(
                schedule_index,
                total_problems,
                self.config.policy,
            )
            state = {
                "i": turn_index,
                "problem_difficulty": str(problem["difficulty"]),
                "last_student_level": last_student_level,
                "last_tutor_level": last_tutor_level,
                "last_reward": float(last_reward),
                "last_coding_score": float(last_coding_score),
                "last_action": str(last_action),
            }
            selection = self.policy.select_action(
                state,
                epsilon=epsilon,
                temperature=temperature,
            )
            tutor_prompt = TUTOR_PEDAGOGICAL_MOVES_PROMPT.format(
                pedagogical_move=selection.action,
                problem_description=problem["problem_description"],
                starter_code=problem["starter_code"],
            )
            agents.tutor.update_system_message(tutor_prompt)

            tutor_message = agents.tutor.invoke(student_message)
            tutor_judgment = agents.tutor_judge.invoke(tutor_message)
            if turn_index > 0:
                test_percentage = int(last_coding_score * 100)
                student_input = AIMessage(
                    content=(
                        tutor_message.content
                        + f"\n\n[TEST FEEDBACK: Your previous coding solution passed "
                        f"{test_percentage}% of tests]"
                    )
                )
            else:
                student_input = tutor_message
            student_message = agents.student.invoke(student_input)
            student_judgment = agents.student_judge.invoke(student_message)

            student_output = _message_json(student_message, "student")
            student_judgment_value = _message_json(student_judgment, "student judge")
            tutor_judgment_value = _message_json(tutor_judgment, "tutor judge")
            evaluation = evaluate_submission(
                problem,
                code_definitions,
                str(student_output["python_code"]),
                timeout_seconds=self.config.evaluation.code_timeout_seconds,
            )
            reward = calculate_reward(
                coding_score=evaluation.score,
                previous_coding_score=last_coding_score,
                code_runs=evaluation.code_runs,
                student_level=int(student_judgment_value["student_level"]),
                tutor_level=int(tutor_judgment_value["tutor_level"]),
                leakage_detected=bool(tutor_judgment_value["leakage_detected"]),
                action=selection.action,
                previous_action=last_action,
                config=self.config,
            )

            interactions.append(
                {
                    "tutor_message": tutor_message,
                    "student_message": student_message,
                    "tutor_judgment": tutor_judgment,
                    "student_judgment": student_judgment,
                    "code_evaluation": evaluation.as_dict(),
                    "selected_action": selection.action,
                }
            )
            transition = {
                "problem": problem_id,
                "attempt": attempt,
                **state,
                "action": selection.action,
                "reward": reward.reward,
                "lambda": self.config.reward.pedagogical_weight,
                "CODE_RUNS_REWARD": self.config.reward.code_runs_bonus,
                "student_success": reward.student_success,
                "pedagogical_quality": reward.pedagogical_quality,
                "student_level": int(student_judgment_value["student_level"]),
                "tutor_level": int(tutor_judgment_value["tutor_level"]),
                "code_runs": evaluation.code_runs,
                "code_evaluation_status": evaluation.status,
                "explored_randomly": selection.explored_randomly,
            }
            if selection.predicted_rewards is not None:
                transition.update(
                    {
                        f"pred_reward_{action}": value
                        for action, value in selection.predicted_rewards.items()
                    }
                )
                transition.update(
                    {
                        f"pred_prob_{action}": value
                        for action, value in selection.probabilities.items()
                    }
                )
            self.policy.log_transition(transition)
            self.policy.maybe_retrain()
            self.store.save_attempt(problem_id, attempt, interactions, completed=False)
            self.store.save_policy_checkpoint(self.policy)

            if evaluation.code_runs and evaluation.score == 1.0:
                stop_reason = "score equals 1"
                solved = True
                break
            if bool(tutor_judgment_value["leakage_detected"]):
                stop_reason = "Leakage detected"
                break
            if bool(student_judgment_value["student_changed_problem"]):
                stop_reason = "Student changed problem"
                break

            last_student_level = int(student_judgment_value["student_level"])
            last_tutor_level = int(tutor_judgment_value["tutor_level"])
            last_reward = reward.reward
            last_action = selection.action
            last_coding_score = evaluation.score

        interactions.append(
            {
                "stop": {
                    "problem_finished": solved,
                    "explanation": stop_reason,
                }
            }
        )
        return {
            "problem_id": problem_id,
            "attempt": attempt,
            "status": "completed",
            "solved": solved,
            "stop_reason": stop_reason,
            "turns": len([entry for entry in interactions if "tutor_message" in entry]),
        }

    def _record_configured_skips(self) -> None:
        statuses = self.store.problem_statuses(self.problem_ids)
        for problem_id in self.config.run.skip_problem_ids:
            if statuses[problem_id] == "pending":
                self.store.append_event(
                    problem_id=problem_id,
                    attempt=None,
                    status="skipped",
                    reason="Problem explicitly omitted by the run configuration",
                    details={"source": "configuration"},
                )

    def _validate_problem_id(self, problem_id: int) -> None:
        if problem_id not in self.problem_ids:
            raise ValueError(f"problem {problem_id} is outside the configured range")


def create_runner_from_config(
    config_path: str | Path = "configs/paper_reproduction.toml",
    *,
    agent_factory: AgentFactory | None = None,
) -> ExperimentRunner:
    """Load configuration, credentials, the exact snapshot, and checkpoints."""

    config = ExperimentConfig.from_toml(config_path)
    load_dotenv(config.paths.secrets_file)
    problems = load_experiment_snapshot(config.paths.dataset, config.paths.manifest)
    return ExperimentRunner(config, problems, agent_factory=agent_factory)


def _index_problems(problems: pd.DataFrame) -> dict[int, dict[str, Any]]:
    index_column = (
        "scheduled_problem_index"
        if "scheduled_problem_index" in problems.columns
        else "question_id"
    )
    return {
        int(row[index_column]): row.to_dict()
        for _, row in problems.iterrows()
    }


def _message_json(message: Any, role: str) -> dict[str, Any]:
    content = message.content if hasattr(message, "content") else message
    if isinstance(content, dict):
        return content
    try:
        return json.loads(content)
    except (TypeError, json.JSONDecodeError) as error:
        raise ValueError(f"{role} returned invalid structured JSON") from error


def _prompt_hashes() -> dict[str, str]:
    prompts = {
        "tutor_baseline": CODING_PRACTICE_PROMPT,
        "tutor_actions": TUTOR_PEDAGOGICAL_MOVES_PROMPT,
        "student_beginner": CODING_BEGINNER_STUDENT_PROMPT,
        "student_judge": STUDENT_JUDGE_PROMPT,
        "tutor_judge": TUTOR_JUDGE_PROMPT,
    }
    return {
        name: hashlib.sha256(value.encode("utf-8")).hexdigest()
        for name, value in prompts.items()
    }
