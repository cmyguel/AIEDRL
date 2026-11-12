# data/

The tracked reproduction artifacts are:

- `experiment_problems_2000.jsonl.gz`: fields consumed by the experiment for
  2,000 problems in fixed order;
- `experiment_problems_2000_manifest.csv`: task IDs, difficulty, paper-run flag,
  and per-record content hashes;
- `experiment_problems_2000_provenance.json`: source and artifact hashes.

Indices 0-199 are the exact problem order scheduled in the submitted paper run.
Indices 200-1999 are an optional extension. The snapshot was derived from the
local `train_shuffled.jsonl` created with random seed 42.

The source is
[newfacade/LeetCodeDataset](https://huggingface.co/datasets/newfacade/LeetCodeDataset),
licensed Apache-2.0. Full downloaded and shuffled source files remain ignored by
Git. The tracked subset can be rebuilt, when the original ignored source is
present, with:

```powershell
python -m scripts.build_experiment_snapshot
```
