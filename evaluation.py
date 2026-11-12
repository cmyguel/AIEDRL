"""Bounded execution of generated student code."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
import json
from pathlib import Path
import subprocess
import sys
from typing import Any, Mapping


@dataclass(frozen=True)
class CodeEvaluationResult:
    """Outcome returned by the generated-code worker."""

    status: str
    code_runs: bool
    passed: int
    total: int
    score: float
    error: str | None = None
    failures: list[str] = field(default_factory=list)
    captured_output: str = ""

    @property
    def timed_out(self) -> bool:
        return self.status == "timeout"

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def evaluate_submission(
    problem: Mapping[str, Any] | Any,
    code_definitions: str,
    student_code: str,
    *,
    timeout_seconds: float,
) -> CodeEvaluationResult:
    """Evaluate code in a child process so infinite loops cannot block the run."""

    payload = {
        "entry_point": _problem_value(problem, "entry_point"),
        "test": _problem_value(problem, "test"),
        "code_definitions": code_definitions,
        "student_code": student_code,
    }
    worker = Path(__file__).with_name("evaluation_worker.py")
    creation_flags = subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0
    try:
        completed = subprocess.run(
            [sys.executable, str(worker)],
            input=json.dumps(payload),
            text=True,
            capture_output=True,
            timeout=timeout_seconds,
            cwd=worker.parent,
            creationflags=creation_flags,
            check=False,
        )
    except subprocess.TimeoutExpired:
        return CodeEvaluationResult(
            status="timeout",
            code_runs=False,
            passed=0,
            total=_assertion_count(str(payload["test"])),
            score=0.0,
            error=f"Code evaluation exceeded {timeout_seconds:g} seconds",
        )

    try:
        raw = json.loads(completed.stdout)
    except json.JSONDecodeError:
        detail = completed.stderr.strip() or completed.stdout.strip() or "no worker output"
        return CodeEvaluationResult(
            status="worker_error",
            code_runs=False,
            passed=0,
            total=_assertion_count(str(payload["test"])),
            score=0.0,
            error=detail[-2000:],
        )
    return CodeEvaluationResult(
        status=str(raw["status"]),
        code_runs=bool(raw["code_runs"]),
        passed=int(raw["passed"]),
        total=int(raw["total"]),
        score=float(raw["score"]),
        error=raw.get("error"),
        failures=list(raw.get("failures", [])),
        captured_output=str(raw.get("captured_output", "")),
    )


def _problem_value(problem: Mapping[str, Any] | Any, name: str) -> Any:
    if isinstance(problem, Mapping):
        return problem[name]
    return getattr(problem, name)


def _assertion_count(test_source: str) -> int:
    return len([part for part in test_source.split("assert")[1:] if part.strip()])
