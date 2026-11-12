import json

import pytest

from run_store import RunStore


def test_unfinished_started_event_becomes_interrupted(tmp_path):
    store = RunStore(tmp_path / "run")
    store.append_event(problem_id=7, attempt=1, status="started")

    reconciled = RunStore(tmp_path / "run").reconcile_interrupted_attempts()
    status = store.problem_statuses([7])

    assert reconciled == [(7, 1)]
    assert status[7] == "interrupted"


def test_attempt_artifacts_are_numbered_and_completed_copy_is_compatible(tmp_path):
    store = RunStore(tmp_path / "run")
    interactions = [{"student_message": {"content": "start"}}, {"stop": {"explanation": "done"}}]

    store.save_attempt(3, 2, interactions, completed=True)

    attempt_path = tmp_path / "run" / "attempts" / "problem_3_attempt_2.json"
    completed_path = tmp_path / "run" / "interactions" / "problem_3.json"
    assert json.loads(attempt_path.read_text(encoding="utf-8")) == interactions
    assert json.loads(completed_path.read_text(encoding="utf-8")) == interactions


def test_existing_run_rejects_changed_configuration(tmp_path):
    dataset = tmp_path / "dataset.jsonl.gz"
    manifest = tmp_path / "manifest.csv"
    dataset.write_bytes(b"dataset")
    manifest.write_bytes(b"manifest")
    store = RunStore(tmp_path / "run")
    metadata = {
        "run": {"run_id": "one"},
        "paths": {"dataset": str(dataset), "manifest": str(manifest)},
        "captured_at": "first",
    }
    store.initialize_metadata(metadata, tmp_path)

    changed = {**metadata, "run": {"run_id": "two"}, "captured_at": "second"}
    with pytest.raises(RuntimeError, match="different configuration"):
        store.initialize_metadata(changed, tmp_path)
