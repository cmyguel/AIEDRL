"""Child process used to execute generated Python with a hard parent timeout.

This is a reliability boundary, not a security sandbox.  The parent process can
terminate an infinite loop, but generated code should still be treated as
untrusted and run only on an appropriate research machine.
"""

from __future__ import annotations

import ast
from contextlib import redirect_stderr, redirect_stdout
from io import StringIO
import json
import sys
import traceback

from utils.code_dependencies import *  # noqa: F401,F403 - dataset test prelude


MEANINGFUL_NODES = (
    ast.Assign,
    ast.AugAssign,
    ast.AnnAssign,
    ast.FunctionDef,
    ast.AsyncFunctionDef,
    ast.ClassDef,
    ast.Return,
    ast.For,
    ast.While,
    ast.If,
    ast.With,
    ast.Try,
    ast.Expr,
    ast.Import,
    ast.ImportFrom,
)


def evaluate(payload: dict) -> dict:
    """Execute one submitted solution and return JSON-safe test diagnostics."""

    student_code = str(payload.get("student_code", ""))
    code_definitions = str(payload.get("code_definitions", ""))
    test_source = str(payload.get("test", ""))
    entry_point = str(payload.get("entry_point", ""))

    if not student_code.strip():
        return _result("empty", False, 0, 0, "Student code is empty")

    try:
        tree = ast.parse(student_code)
    except SyntaxError as error:
        return _result("syntax_error", False, 0, 0, _short_error(error))
    if not any(isinstance(node, MEANINGFUL_NODES) for node in ast.walk(tree)):
        return _result("empty", False, 0, 0, "No executable statements found")

    expressions = [part.strip() for part in test_source.split("assert")[1:] if part.strip()]
    if not expressions:
        return _result("test_error", False, 0, 0, "Problem contains no parsed assertions")

    namespace = dict(globals())
    output = StringIO()
    try:
        with redirect_stdout(output), redirect_stderr(output):
            exec(code_definitions, namespace)
            exec(student_code, namespace)
    except Exception as error:
        return _result("runtime_error", False, 0, len(expressions), _short_error(error))

    passed = 0
    failures: list[str] = []
    for index, expression in enumerate(expressions):
        candidate_expression = expression.replace("candidate", entry_point, 1)
        try:
            # Re-executing the class/function definitions matches the paper-run evaluator.
            with redirect_stdout(output), redirect_stderr(output):
                exec(student_code, namespace)
                succeeded = bool(eval(candidate_expression, namespace))
            if succeeded:
                passed += 1
            else:
                failures.append(f"test {index}: expression returned false")
        except Exception as error:
            failures.append(f"test {index}: {_short_error(error)}")

    status = "passed" if passed == len(expressions) else "failed"
    return {
        **_result(status, True, passed, len(expressions), None),
        "failures": failures[:10],
        "captured_output": output.getvalue()[-2000:],
    }


def _short_error(error: BaseException) -> str:
    return "".join(traceback.format_exception_only(type(error), error)).strip()


def _result(
    status: str,
    code_runs: bool,
    passed: int,
    total: int,
    error: str | None,
) -> dict:
    return {
        "status": status,
        "code_runs": code_runs,
        "passed": passed,
        "total": total,
        "score": passed / total if total else 0.0,
        "error": error,
        "failures": [],
        "captured_output": "",
    }


def main() -> int:
    try:
        payload = json.load(sys.stdin)
        json.dump(evaluate(payload), sys.stdout)
        return 0
    except Exception as error:  # Worker protocol errors, not student-code errors.
        json.dump(_result("worker_error", False, 0, 0, _short_error(error)), sys.stdout)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
