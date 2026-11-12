"""Append-only run status, interaction artifacts, and checkpoints."""

from __future__ import annotations

from collections import defaultdict
from datetime import datetime
import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess
from typing import Any, Iterable

import pandas as pd

from policy import RewardPolicy


ATTEMPT_TERMINAL_STATUSES = {"completed", "failed", "interrupted"}


class RunStore:
    """Own the on-disk audit trail for a supervised experiment run."""

    def __init__(self, run_path: Path):
        self.run_path = Path(run_path)
        self.interactions_path = self.run_path / "interactions"
        self.attempts_path = self.run_path / "attempts"
        self.checkpoints_path = self.run_path / "checkpoints"
        for path in (
            self.run_path,
            self.interactions_path,
            self.attempts_path,
            self.checkpoints_path,
        ):
            path.mkdir(parents=True, exist_ok=True)
        self.events_path = self.run_path / "run_events.jsonl"

    def initialize_metadata(self, metadata: dict[str, Any], repo_root: Path) -> None:
        """Write immutable run provenance once; resume never silently replaces it."""

        metadata_path = self.run_path / "run_metadata.json"
        if metadata_path.exists():
            with metadata_path.open(encoding="utf-8") as stream:
                existing = json.load(stream)
            changed = [
                key
                for key, value in metadata.items()
                if key != "captured_at" and existing.get(key) != value
            ]
            if changed:
                raise RuntimeError(
                    "run_id already belongs to a different configuration; "
                    f"use a new run_id (changed metadata: {', '.join(changed)})"
                )
            return
        enriched = dict(metadata)
        enriched.update(
            {
                "git_commit": _git_commit(repo_root),
                "package_versions": _package_versions(),
                "dataset_sha256": _sha256(Path(metadata["paths"]["dataset"])),
                "manifest_sha256": _sha256(Path(metadata["paths"]["manifest"])),
            }
        )
        _write_json(metadata_path, enriched)

    def append_event(
        self,
        *,
        problem_id: int,
        attempt: int | None,
        status: str,
        reason: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Append one durable lifecycle event."""

        event = {
            "timestamp": datetime.now().astimezone().isoformat(),
            "problem_id": int(problem_id),
            "attempt": int(attempt) if attempt is not None else None,
            "status": status,
            "reason": reason,
            "details": details or {},
        }
        with self.events_path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(event, ensure_ascii=False) + "\n")
            stream.flush()
        return event

    def events(self) -> list[dict[str, Any]]:
        if not self.events_path.exists():
            return []
        with self.events_path.open(encoding="utf-8") as stream:
            return [json.loads(line) for line in stream if line.strip()]

    def reconcile_interrupted_attempts(self) -> list[tuple[int, int]]:
        """Mark attempts left open by a kernel interruption as interrupted."""

        grouped: dict[tuple[int, int], list[dict[str, Any]]] = defaultdict(list)
        for event in self.events():
            if event["attempt"] is not None:
                grouped[(int(event["problem_id"]), int(event["attempt"]))].append(event)

        reconciled: list[tuple[int, int]] = []
        for (problem_id, attempt), attempt_events in grouped.items():
            statuses = {event["status"] for event in attempt_events}
            if "started" in statuses and not statuses.intersection(ATTEMPT_TERMINAL_STATUSES):
                self.append_event(
                    problem_id=problem_id,
                    attempt=attempt,
                    status="interrupted",
                    reason="Run resumed after an attempt ended without a terminal event",
                )
                reconciled.append((problem_id, attempt))
        return reconciled

    def next_attempt_number(self, problem_id: int) -> int:
        attempts = [
            int(event["attempt"])
            for event in self.events()
            if int(event["problem_id"]) == int(problem_id) and event["attempt"] is not None
        ]
        return max(attempts, default=0) + 1

    def problem_statuses(self, problem_ids: Iterable[int]) -> dict[int, str]:
        """Summarize each problem without hiding failed or interrupted attempts."""

        by_problem: dict[int, list[dict[str, Any]]] = defaultdict(list)
        for event in self.events():
            by_problem[int(event["problem_id"])].append(event)

        result: dict[int, str] = {}
        for problem_id in problem_ids:
            events = by_problem.get(int(problem_id), [])
            statuses = [event["status"] for event in events]
            if "completed" in statuses:
                result[int(problem_id)] = "completed"
            elif "skipped" in statuses:
                result[int(problem_id)] = "skipped"
            elif statuses and statuses[-1] in {"failed", "interrupted"}:
                result[int(problem_id)] = statuses[-1]
            elif "started" in statuses:
                result[int(problem_id)] = "started"
            else:
                result[int(problem_id)] = "pending"
        return result

    def status_frame(self, problem_ids: Iterable[int]) -> pd.DataFrame:
        statuses = self.problem_statuses(problem_ids)
        attempts: dict[int, int] = defaultdict(int)
        reasons: dict[int, str | None] = {}
        for event in self.events():
            problem_id = int(event["problem_id"])
            if event["attempt"] is not None:
                attempts[problem_id] = max(attempts[problem_id], int(event["attempt"]))
            if event.get("reason"):
                reasons[problem_id] = event["reason"]
        return pd.DataFrame(
            [
                {
                    "problem_id": problem_id,
                    "status": status,
                    "attempts": attempts[problem_id],
                    "latest_reason": reasons.get(problem_id),
                }
                for problem_id, status in statuses.items()
            ]
        )

    def save_attempt(
        self,
        problem_id: int,
        attempt: int,
        interactions: list[dict[str, Any]],
        *,
        completed: bool,
    ) -> Path:
        """Save partial/full attempt state and a legacy-compatible completed copy."""

        attempt_path = self.attempts_path / f"problem_{problem_id}_attempt_{attempt}.json"
        serializable = _to_json_safe(interactions)
        _write_json(attempt_path, serializable)
        if completed:
            _write_json(self.interactions_path / f"problem_{problem_id}.json", serializable)
        return attempt_path

    def save_policy_checkpoint(self, policy: RewardPolicy) -> None:
        """Persist transition memory and the fitted reward model."""

        frame = policy.transition_frame()
        if not frame.empty:
            temporary = self.checkpoints_path / "memory.csv.tmp"
            frame.to_csv(temporary, index=False)
            temporary.replace(self.checkpoints_path / "memory.csv")
        policy.save_model(self.checkpoints_path / "reward_model.pkl")
        _write_json(self.checkpoints_path / "rng_state.json", policy.rng_state())

    def load_policy_checkpoint(self, policy: RewardPolicy) -> None:
        memory_path = self.checkpoints_path / "memory.csv"
        model_path = self.checkpoints_path / "reward_model.pkl"
        rng_path = self.checkpoints_path / "rng_state.json"
        if memory_path.exists():
            frame = pd.read_csv(memory_path)
            policy.load_memory(frame.to_dict(orient="records"))
        if model_path.exists():
            policy.load_model(model_path)
        if rng_path.exists():
            with rng_path.open(encoding="utf-8") as stream:
                policy.load_rng_state(json.load(stream))


def _to_json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _to_json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_to_json_safe(item) for item in value]
    if hasattr(value, "content"):
        return {"type": value.__class__.__name__, "content": value.content}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


def _write_json(path: Path, value: Any) -> None:
    temporary = path.with_suffix(path.suffix + ".tmp")
    with temporary.open("w", encoding="utf-8") as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
    temporary.replace(path)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_commit(repo_root: Path) -> str | None:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            text=True,
            capture_output=True,
            check=True,
        )
        return result.stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def _package_versions() -> dict[str, str]:
    packages = [
        "datasets",
        "langchain",
        "langchain-openai",
        "numpy",
        "pandas",
        "pydantic",
        "scikit-learn",
    ]
    versions: dict[str, str] = {}
    for package in packages:
        try:
            versions[package] = importlib.metadata.version(package)
        except importlib.metadata.PackageNotFoundError:
            versions[package] = "not installed"
    return versions
