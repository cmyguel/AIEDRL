"""Interpretable reward model and pedagogical-action selection policy."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable
import pickle

import numpy as np
import pandas as pd
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder

from experiment_config import PolicyConfig


STATE_COLUMNS = [
    "i",
    "problem_difficulty",
    "last_student_level",
    "last_tutor_level",
    "last_reward",
    "last_coding_score",
    "last_action",
]
MODEL_COLUMNS = STATE_COLUMNS + ["action"]
TARGET_COLUMN = "reward"


@dataclass(frozen=True)
class ActionSelection:
    """Selected action plus optional reward-model diagnostics."""

    action: str
    predicted_rewards: dict[str, float] | None
    probabilities: dict[str, float] | None
    explored_randomly: bool


def softmax(values: np.ndarray, temperature: float = 1.0) -> np.ndarray:
    """Convert candidate rewards into stable sampling probabilities."""

    effective_temperature = max(float(temperature), 1e-6)
    centered = values / effective_temperature
    centered -= np.max(centered)
    probabilities = np.exp(centered)
    return probabilities / probabilities.sum()


def schedule_parameters(
    current_problem_index: int,
    total_problems: int,
    config: PolicyConfig,
) -> tuple[float, float]:
    """Return the paper run's constant epsilon and linearly decayed temperature."""

    progress = current_problem_index / max(total_problems - 1, 1)
    if progress <= config.temperature_decay_fraction:
        temperature = config.initial_temperature * (
            1 - progress / config.temperature_decay_fraction
        )
    else:
        temperature = 0.0
    return config.epsilon, temperature


class RewardPolicy:
    """Random-forest reward model with incremental transition memory.

    The model predicts immediate turn reward for each candidate action.  It is a
    contextual, per-turn controller; it does not optimize a delayed episode
    return and it does not update any LLM weights.
    """

    def __init__(self, config: PolicyConfig):
        self.config = config
        self.memory: list[dict[str, Any]] = []
        self.model: Pipeline | None = None
        self.rng = np.random.default_rng(config.random_seed)

    def transition_frame(self) -> pd.DataFrame:
        """Return logged transitions in stable column order."""

        if not self.memory:
            return pd.DataFrame(columns=["problem", "attempt", *MODEL_COLUMNS, TARGET_COLUMN])
        frame = pd.DataFrame(self.memory)
        leading = [name for name in ("problem", "attempt") if name in frame.columns]
        trailing = [name for name in frame.columns if name not in leading]
        return frame[leading + trailing]

    def log_transition(self, transition: dict[str, Any]) -> None:
        """Append one state-action-reward observation."""

        missing = [name for name in MODEL_COLUMNS + [TARGET_COLUMN] if name not in transition]
        if missing:
            raise ValueError(f"transition is missing required fields: {missing}")
        self.memory.append(dict(transition))

    def train(self) -> Pipeline:
        """Fit a new random forest to all accumulated transitions."""

        frame = self.transition_frame()
        if frame.empty:
            raise ValueError("cannot train a reward model without transitions")

        preprocessing = ColumnTransformer(
            transformers=[
                (
                    "categorical",
                    OneHotEncoder(handle_unknown="ignore"),
                    ["problem_difficulty", "last_action", "action"],
                ),
                (
                    "numeric",
                    "passthrough",
                    [
                        "i",
                        "last_student_level",
                        "last_tutor_level",
                        "last_reward",
                        "last_coding_score",
                    ],
                ),
            ]
        )
        model = Pipeline(
            steps=[
                ("preprocessing", preprocessing),
                (
                    "regressor",
                    RandomForestRegressor(
                        n_estimators=self.config.forest_estimators,
                        random_state=self.config.random_seed,
                        n_jobs=-1,
                    ),
                ),
            ]
        )
        model.fit(frame[MODEL_COLUMNS], frame[TARGET_COLUMN].astype(float))
        self.model = model
        return model

    def maybe_retrain(self) -> bool:
        """Retrain at the same row-count cadence as the submitted experiment."""

        row_count = len(self.memory)
        if row_count < self.config.min_rows_before_training:
            return False
        if row_count % self.config.retrain_every != 0:
            return False
        if self.transition_frame()[TARGET_COLUMN].nunique() < 2:
            return False
        self.train()
        return True

    def select_action(
        self,
        state: dict[str, Any],
        *,
        epsilon: float,
        temperature: float,
    ) -> ActionSelection:
        """Sample an action and return the diagnostics written to memory.csv."""

        actions = self.config.actions
        if self.model is None:
            return ActionSelection(
                action=str(self.rng.choice(actions)),
                predicted_rewards=None,
                probabilities=None,
                explored_randomly=True,
            )

        candidates = pd.DataFrame(
            [{**state, "action": action} for action in actions]
        )[MODEL_COLUMNS]
        predictions_array = self.model.predict(candidates)
        probabilities_array = softmax(predictions_array, temperature)
        predictions = {
            action: float(value) for action, value in zip(actions, predictions_array)
        }
        probabilities = {
            action: float(value) for action, value in zip(actions, probabilities_array)
        }

        explored = bool(self.rng.random() < epsilon)
        if explored:
            action = str(self.rng.choice(actions))
        else:
            action = str(self.rng.choice(actions, p=probabilities_array))
        return ActionSelection(action, predictions, probabilities, explored)

    def load_memory(self, rows: Iterable[dict[str, Any]]) -> None:
        """Replace transition memory from a checkpoint."""

        self.memory = [dict(row) for row in rows]

    def save_model(self, path: Path) -> None:
        """Persist the fitted sklearn pipeline when one exists."""

        if self.model is None:
            return
        with path.open("wb") as stream:
            pickle.dump(self.model, stream)

    def load_model(self, path: Path) -> None:
        """Load a previously fitted sklearn pipeline."""

        with path.open("rb") as stream:
            self.model = pickle.load(stream)

    def rng_state(self) -> dict[str, Any]:
        """Return the NumPy generator state so resume does not restart sampling."""

        return self.rng.bit_generator.state

    def load_rng_state(self, state: dict[str, Any]) -> None:
        """Restore action-sampling state from a checkpoint."""

        self.rng.bit_generator.state = state
