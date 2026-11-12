# Experiment protocol and operator guide

## System flow

For each scheduled problem, the runner creates a synthetic student, tutor,
student judge, and tutor judge. On every turn:

1. The policy observes turn index, difficulty, previous levels, previous action,
   previous reward, and previous coding score.
2. The random-forest reward model predicts immediate reward for each candidate
   pedagogical action.
3. Softmax sampling plus epsilon exploration selects an action.
4. The tutor responds under the selected action prompt.
5. The student responds with short dialogue and a current Python implementation.
6. The generated code is evaluated against dataset tests in a bounded child
   process.
7. Judge agents estimate student level, tutor abstraction level, topic drift,
   and solution leakage.
8. The transition is rewarded, logged, checkpointed, and optionally used to
   retrain the reward model.

This is a per-turn contextual controller. The multi-turn history affects the LLM
conversation, while the policy receives only the compact state described above.

## Agent models and prompts

The paper-run configuration uses:

| Role | Model alias |
|---|---|
| Tutor | `gpt-4.1` |
| Student | `gpt-4.1-mini` |
| Student judge | `gpt-4.1` |
| Tutor judge | `gpt-4.1` |

Exact prompts are versioned under `prompts/`. Every new run records their SHA-256
hashes. Provider-side model aliases may change over time, so this documents the
requested models but cannot freeze their remote weights.

## Implemented reward

```text
scaffolding = 2 - abs(student_level - tutor_level)
pedagogical_quality = -1 if leakage else scaffolding
student_success = current_code_score if current_code_score changed else 0

reward = 0.7 * student_success
       + 0.3 * pedagogical_quality
       + 0.1 if code runs
       - 0.1 if the selected action repeats
```

This reproduces the code, including the fact that `student_success` is not the
change in score. Scientific changes belong in a separate revised-study
configuration, not in the reproduction configuration.

## Policy update schedule

- Random forest: 200 trees, `random_state=42`.
- Cold start: random action selection.
- First fit: 10 logged transitions.
- Retraining: whenever the accumulated transition count is divisible by 3.
- Epsilon: constant at 0.1.
- Temperature: linearly decays from 2.0 to effectively zero over the first 60%
  of the configured problem range.
- Maximum episode length: 10 tutoring turns.

Near-zero temperature makes the non-epsilon choice effectively greedy; epsilon
exploration continues throughout the run.

## Supervised execution

`reproduce_experiment.ipynb` exposes four operations:

```python
runner.run_next(batch_size=1)
runner.status()
runner.retry(problem_id=4)
runner.skip(problem_id=4, reason="documented operator reason")
```

`run_next` selects only untouched problems. A failed or interrupted problem is
listed for attention and is not silently attempted again. `retry` starts a new
numbered attempt; `skip` requires a reason.

Any configured skips are written to the status log at initialization. The
default reproduction configuration has no skips: it attempts all 200 scheduled
problems under the bounded evaluator. If an operator adds skips, use a new run
ID so the decision is not mixed into an existing trajectory.

## Failure and interruption behavior

- Code syntax/runtime failures receive score zero and remain part of the episode.
- Code exceeding the configured evaluation timeout receives status `timeout`,
  score zero, and cannot block the notebook.
- Transient LLM requests use the configured provider retries.
- An unrecoverable agent or structured-output error fails the current attempt;
  the next `run_next` call advances to an untouched problem.
- `KeyboardInterrupt` saves partial interactions and memory before re-raising.
- If the kernel is forcibly stopped before cleanup, the next initialization finds
  a `started` event with no terminal event and records it as `interrupted`.

## Output layout

```text
outputs/<run_id>/
  run_metadata.json       resolved configuration and provenance
  run_events.jsonl        append-only problem/attempt lifecycle
  interactions/           completed, analysis-compatible problem_<id>.json
  attempts/               partial and retried attempt artifacts
  checkpoints/
    memory.csv            state-action-reward transitions
    reward_model.pkl      latest fitted sklearn pipeline
    rng_state.json        action-sampling state for exact local resume
```

Memory is checkpointed after each turn. Completed interactions retain the
historical filename convention so the existing visualization notebook can load
them. New memory rows add `attempt`, `code_evaluation_status`, and
`explored_randomly`; existing analysis columns are unchanged.

## Extending to 2,000 problems

The default configuration stops at 200 to reproduce the submitted protocol. To
continue through the tracked extension, copy the TOML file, choose a new run ID,
set `problem_stop = 2000`, and review the skip list. Do not append an extended
study to a run already presented as a reproduction of the paper.

## Cost and safety

Each turn can require four remote LLM calls. Review the problem range and account
limits before increasing batch size. Do not commit credentials. Generated code
is time-bounded in another process but is not securely sandboxed from the host;
use an isolated research environment for untrusted execution.
