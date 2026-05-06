from typing import Tuple 
from pathlib import Path
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