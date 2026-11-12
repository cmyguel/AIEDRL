from typing import Any, Tuple
from pathlib import Path
import csv
import gzip
import hashlib
import json

import pandas as pd

def load_leetcodedataset_data(path_data:Path)->Tuple[pd.DataFrame, pd.DataFrame]:
    """ 
    loads data from local if exists, otherwhise from Huggingface and writes on local disk.
    """
    # Login using e.g. `huggingface-cli login` to access this dataset
    splits = {
        "train": "LeetCodeDataset-train.jsonl",
        "test": "LeetCodeDataset-test.jsonl",
    }

    train_path = path_data / splits["train"]
    test_path  = path_data / splits["test"]

    # Train data
    if not train_path.exists():
        df_train = pd.read_json(
            "hf://datasets/newfacade/LeetCodeDataset/" + splits["train"],
            lines=True,
        )
        df_train.to_json(train_path, orient="records", lines=True)
        # df_train.to_csv(train_path.with_suffix('.csv'), index=False, encoding="utf-8-sig")
    else:
        df_train = pd.read_json(train_path, lines=True)

    # Test data
    if not test_path.exists():
        df_test = pd.read_json(
            "hf://datasets/newfacade/LeetCodeDataset/" + splits["test"],
            lines=True,
        )
        df_test.to_json(test_path, orient="records", lines=True)
        # df_test.to_csv(test_path.with_suffix('.csv'), index=False, encoding="utf-8-sig")
    else:
        df_test = pd.read_json(test_path, lines=True)

    return df_train, df_test

def load_or_create_shuffled_data(path_data: Path, random_seed: int = 42):
    """
    Load pre-shuffled data if available, otherwise load original data,
    shuffle it with stratification by difficulty, and save as train_shuffled.jsonl/test_shuffled.jsonl.
    Resets question_id to be sequential after shuffling.
    """
    from sklearn.model_selection import StratifiedShuffleSplit
    
    shuffled_train_path = path_data / "train_shuffled.jsonl"
    shuffled_test_path = path_data / "test_shuffled.jsonl"
    
    # Check if shuffled versions exist
    if shuffled_train_path.exists() and shuffled_test_path.exists():
        print("Loading pre-shuffled data...")
        df_train = pd.read_json(shuffled_train_path, lines=True)
        df_test = pd.read_json(shuffled_test_path, lines=True)
        return df_train, df_test
    
    # Load original data
    print("Loading original data...")
    df_train, df_test = load_leetcodedataset_data(path_data)
    
    # Stratified shuffle by difficulty
    print("Shuffling data with stratification by difficulty...")
    if "difficulty" in df_train.columns:
        sss = StratifiedShuffleSplit(n_splits=1, random_state=random_seed)
        for train_idx, _ in sss.split(df_train, df_train['difficulty']):
            df_train = df_train.iloc[train_idx].reset_index(drop=True)
        for test_idx, _ in sss.split(df_test, df_test['difficulty']):
            df_test = df_test.iloc[test_idx].reset_index(drop=True)
    else:
        raise Exception("difficulty column required. ")
    
    # Reset question_id to be sequential after shuffle
    if "question_id" in df_train.columns:
        df_train["question_id"] = range(len(df_train))
        # For test set, sort by existing question_id to order them
        df_test = df_test.sort_values('question_id').reset_index(drop=True)
    
    # Save shuffled versions as JSONL (preserves types, consistent with raw data format)
    print("Saving shuffled data...")
    df_train.to_json(shuffled_train_path, orient='records', lines=True)
    df_test.to_json(shuffled_test_path, orient='records', lines=True)
    print(f"✓ Saved shuffled train_shuffled.jsonl ({len(df_train)} rows) and test_shuffled.jsonl ({len(df_test)} rows)")
    
    return df_train, df_test


EXPERIMENT_PROBLEM_FIELDS = (
    "scheduled_problem_index",
    "task_id",
    "difficulty",
    "problem_description",
    "starter_code",
    "entry_point",
    "test",
)


def load_experiment_snapshot(snapshot_path: Path, manifest_path: Path) -> pd.DataFrame:
    """Load and verify the tracked 2,000-problem reproduction snapshot.

    The first 200 rows are the exact ordered inputs scheduled by the submitted
    paper run.  Hash validation makes accidental edits or upstream drift visible
    before an API-backed experiment begins.
    """

    snapshot_path = Path(snapshot_path)
    manifest_path = Path(manifest_path)
    if not snapshot_path.exists():
        raise FileNotFoundError(f"experiment snapshot not found: {snapshot_path}")
    if not manifest_path.exists():
        raise FileNotFoundError(f"experiment manifest not found: {manifest_path}")

    records: list[dict[str, Any]] = []
    record_hashes: list[str] = []
    with gzip.open(snapshot_path, "rt", encoding="utf-8") as stream:
        for line in stream:
            encoded_line = line.rstrip("\r\n")
            if not encoded_line:
                continue
            records.append(json.loads(encoded_line))
            record_hashes.append(hashlib.sha256(encoded_line.encode("utf-8")).hexdigest())
    # ``utf-8-sig`` accepts both ordinary UTF-8 and Windows-authored CSV files
    # with a byte-order mark without polluting the first column name.
    with manifest_path.open(newline="", encoding="utf-8-sig") as stream:
        manifest = list(csv.DictReader(stream))

    if len(records) != 2000 or len(manifest) != 2000:
        raise ValueError(
            f"expected 2,000 snapshot records and manifest rows, got "
            f"{len(records)} and {len(manifest)}"
        )
    expected_indices = list(range(2000))
    actual_indices = [int(record["scheduled_problem_index"]) for record in records]
    if actual_indices != expected_indices:
        raise ValueError("snapshot indices must be contiguous and ordered from 0 to 1999")
    task_ids = [str(record["task_id"]) for record in records]
    if len(set(task_ids)) != len(task_ids):
        raise ValueError("snapshot task_id values must be unique")

    for record, record_hash, row in zip(records, record_hashes, manifest):
        index = int(record["scheduled_problem_index"])
        if int(row["scheduled_problem_index"]) != index:
            raise ValueError(f"manifest index mismatch at problem {index}")
        if row["task_id"] != str(record["task_id"]):
            raise ValueError(f"manifest task_id mismatch at problem {index}")
        expected_paper_flag = "true" if index < 200 else "false"
        if row["paper_run"].lower() != expected_paper_flag:
            raise ValueError(f"manifest paper_run flag mismatch at problem {index}")
        if row["record_sha256"] != record_hash:
            raise ValueError(f"snapshot content hash mismatch at problem {index}")

    return pd.DataFrame(records)
