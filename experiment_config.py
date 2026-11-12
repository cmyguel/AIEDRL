"""Typed configuration for supervised AIEDRL experiment runs.

The submitted experiment kept most configuration in notebook cells.  This module
collects those values in one inspectable object while keeping the original
scientific choices as defaults.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any
import tomllib


@dataclass(frozen=True)
class ModelConfig:
    """LLM aliases and request-level reliability settings."""

    tutor: str = "gpt-4.1"
    student: str = "gpt-4.1-mini"
    student_judge: str = "gpt-4.1"
    tutor_judge: str = "gpt-4.1"
    request_timeout_seconds: float = 120.0
    max_retries: int = 2


@dataclass(frozen=True)
class PolicyConfig:
    """Reward-model and exploration settings used by the action policy."""

    actions: tuple[str, ...] = (
        "SOCRATIC_PROBE",
        "CONCEPTUAL_HINT",
        "STRUCTURAL_SCAFFOLD",
    )
    random_seed: int = 42
    forest_estimators: int = 200
    min_rows_before_training: int = 10
    retrain_every: int = 3
    epsilon: float = 0.1
    initial_temperature: float = 2.0
    temperature_decay_fraction: float = 0.6


@dataclass(frozen=True)
class RewardConfig:
    """Weights from the paper run; these are intentionally not corrected here."""

    pedagogical_weight: float = 0.3
    code_runs_bonus: float = 0.1
    repeated_action_penalty: float = -0.1


@dataclass(frozen=True)
class EvaluationConfig:
    """Boundaries for generated-code execution and tutoring episodes."""

    code_timeout_seconds: float = 10.0
    max_turns: int = 10


@dataclass(frozen=True)
class RunConfig:
    """Problem range and run-directory behavior."""

    run_id: str = "paper_reproduction"
    problem_start: int = 0
    problem_stop: int = 200
    default_batch_size: int = 1
    skip_problem_ids: tuple[int, ...] = ()
    student_programming_level: str = "beginner"


@dataclass(frozen=True)
class PathConfig:
    """Repository-relative paths resolved when the TOML file is loaded."""

    dataset: Path = Path("data/experiment_problems_2000.jsonl.gz")
    manifest: Path = Path("data/experiment_problems_2000_manifest.csv")
    output_root: Path = Path("outputs")
    secrets_file: Path = Path("secrets/openai.env")


@dataclass(frozen=True)
class ExperimentConfig:
    """Complete configuration for a supervised experiment run."""

    run: RunConfig = field(default_factory=RunConfig)
    models: ModelConfig = field(default_factory=ModelConfig)
    policy: PolicyConfig = field(default_factory=PolicyConfig)
    reward: RewardConfig = field(default_factory=RewardConfig)
    evaluation: EvaluationConfig = field(default_factory=EvaluationConfig)
    paths: PathConfig = field(default_factory=PathConfig)
    source_path: Path | None = field(default=None, compare=False)

    @classmethod
    def from_toml(cls, config_path: str | Path) -> "ExperimentConfig":
        """Load and validate configuration, resolving paths from the repo root."""

        source_path = Path(config_path).resolve()
        with source_path.open("rb") as stream:
            raw = tomllib.load(stream)

        repo_root = source_path.parent.parent
        path_defaults = PathConfig()
        run_defaults = RunConfig()
        policy_defaults = PolicyConfig()
        paths_raw = raw.get("paths", {})
        paths = PathConfig(
            dataset=(repo_root / paths_raw.get("dataset", path_defaults.dataset)).resolve(),
            manifest=(repo_root / paths_raw.get("manifest", path_defaults.manifest)).resolve(),
            output_root=(repo_root / paths_raw.get("output_root", path_defaults.output_root)).resolve(),
            secrets_file=(repo_root / paths_raw.get("secrets_file", path_defaults.secrets_file)).resolve(),
        )

        run_raw = raw.get("run", {})
        policy_raw = raw.get("policy", {})
        config = cls(
            run=RunConfig(
                **{
                    **run_raw,
                    "skip_problem_ids": tuple(
                        int(value)
                        for value in run_raw.get(
                            "skip_problem_ids", run_defaults.skip_problem_ids
                        )
                    ),
                }
            ),
            models=ModelConfig(**raw.get("models", {})),
            policy=PolicyConfig(
                **{
                    **policy_raw,
                    "actions": tuple(
                        policy_raw.get("actions", policy_defaults.actions)
                    ),
                }
            ),
            reward=RewardConfig(**raw.get("reward", {})),
            evaluation=EvaluationConfig(**raw.get("evaluation", {})),
            paths=paths,
            source_path=source_path,
        )
        config.validate()
        return config

    def validate(self) -> None:
        """Fail early on configuration mistakes that would invalidate a run."""

        if self.run.problem_start < 0 or self.run.problem_stop <= self.run.problem_start:
            raise ValueError("problem_stop must be greater than problem_start >= 0")
        if self.run.default_batch_size < 1:
            raise ValueError("default_batch_size must be at least 1")
        if self.evaluation.max_turns < 1:
            raise ValueError("max_turns must be at least 1")
        if self.evaluation.code_timeout_seconds <= 0:
            raise ValueError("code_timeout_seconds must be positive")
        if not 0 <= self.policy.epsilon <= 1:
            raise ValueError("epsilon must be between 0 and 1")
        if not 0 < self.policy.temperature_decay_fraction <= 1:
            raise ValueError("temperature_decay_fraction must be in (0, 1]")
        if not 0 <= self.reward.pedagogical_weight <= 1:
            raise ValueError("pedagogical_weight must be between 0 and 1")
        if len(self.policy.actions) < 2 or len(set(self.policy.actions)) != len(self.policy.actions):
            raise ValueError("actions must contain at least two unique names")
        outside_range = [
            problem_id
            for problem_id in self.run.skip_problem_ids
            if problem_id < self.run.problem_start or problem_id >= self.run.problem_stop
        ]
        if outside_range:
            raise ValueError(f"skip_problem_ids outside configured range: {outside_range}")

    @property
    def run_path(self) -> Path:
        """Directory containing outputs for this configured run."""

        return self.paths.output_root / self.run.run_id

    def as_metadata(self) -> dict[str, Any]:
        """Return a JSON-serializable copy suitable for run provenance."""

        value = asdict(self)
        value["paths"] = {name: str(path) for name, path in value["paths"].items()}
        value["source_path"] = str(self.source_path) if self.source_path else None
        value["captured_at"] = datetime.now().astimezone().isoformat()
        return value
