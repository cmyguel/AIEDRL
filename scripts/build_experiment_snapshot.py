"""Build the tracked 2,000-problem snapshot from the original shuffled data.

This script exists for provenance.  Normal reproduction uses the committed
snapshot and does not need the ignored 83 MB source file.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
import gzip
import hashlib
import json
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
SOURCE = REPO_ROOT / "data" / "train_shuffled.jsonl"
SNAPSHOT = REPO_ROOT / "data" / "experiment_problems_2000.jsonl.gz"
MANIFEST = REPO_ROOT / "data" / "experiment_problems_2000_manifest.csv"
PROVENANCE = REPO_ROOT / "data" / "experiment_problems_2000_provenance.json"
RECORD_COUNT = 2000


def main() -> None:
    if not SOURCE.exists():
        raise FileNotFoundError(f"Original shuffled dataset is required: {SOURCE}")

    records: list[dict] = []
    with SOURCE.open(encoding="utf-8") as stream:
        for scheduled_index, line in enumerate(stream):
            if scheduled_index >= RECORD_COUNT:
                break
            source_record = json.loads(line)
            record = {
                "scheduled_problem_index": scheduled_index,
                "task_id": source_record["task_id"],
                "difficulty": source_record["difficulty"],
                "problem_description": source_record["problem_description"],
                "starter_code": source_record["starter_code"],
                "entry_point": source_record["entry_point"],
                "test": source_record["test"],
            }
            records.append(record)
    if len(records) != RECORD_COUNT:
        raise ValueError(f"Expected {RECORD_COUNT} source rows, found {len(records)}")

    encoded_records: list[str] = []
    with gzip.open(SNAPSHOT, "wt", encoding="utf-8", newline="\n") as stream:
        for record in records:
            encoded_record = json.dumps(record, ensure_ascii=False, separators=(",", ":"))
            encoded_records.append(encoded_record)
            stream.write(encoded_record + "\n")

    with MANIFEST.open("w", encoding="utf-8", newline="") as stream:
        writer = csv.DictWriter(
            stream,
            fieldnames=[
                "scheduled_problem_index",
                "task_id",
                "difficulty",
                "paper_run",
                "record_sha256",
            ],
        )
        writer.writeheader()
        for record, encoded_record in zip(records, encoded_records):
            writer.writerow(
                {
                    "scheduled_problem_index": record["scheduled_problem_index"],
                    "task_id": record["task_id"],
                    "difficulty": record["difficulty"],
                    "paper_run": str(record["scheduled_problem_index"] < 200).lower(),
                    "record_sha256": hashlib.sha256(encoded_record.encode("utf-8")).hexdigest(),
                }
            )

    provenance = {
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_file": SOURCE.name,
        "source_sha256": file_sha256(SOURCE),
        "snapshot_file": SNAPSHOT.name,
        "snapshot_sha256": file_sha256(SNAPSHOT),
        "manifest_file": MANIFEST.name,
        "manifest_sha256": file_sha256(MANIFEST),
        "record_count": RECORD_COUNT,
        "paper_run_indices": [0, 199],
        "source_dataset": "newfacade/LeetCodeDataset",
        "source_license": "Apache-2.0",
    }
    PROVENANCE.write_text(json.dumps(provenance, indent=2) + "\n", encoding="utf-8")


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


if __name__ == "__main__":
    main()
