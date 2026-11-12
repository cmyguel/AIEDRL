# AIEDRL

AIEDRL is a simulated programming-tutoring experiment. A lightweight reward
model selects one of three pedagogical actions for a fixed LLM tutor:

- `SOCRATIC_PROBE`
- `CONCEPTUAL_HINT`
- `STRUCTURAL_SCAFFOLD`

The project does **not** fine-tune the tutor or student language models. It is a
contextual, per-turn action controller evaluated in a synthetic environment.

## Reproduce the submitted experiment

The supported workflow is supervised because external model calls and generated
student code can fail or become inefficient.

1. Create the environment:

   ```powershell
   conda env create -f environment.yml
   conda activate rlhf
   python -m ipykernel install --user --name rlhf --display-name rlhf
   ```

2. Copy `secrets/openai.env.example` to `secrets/openai.env` and add your own
   `OPENAI_API_KEY`. Never commit the populated file.

3. Run the offline test suite:

   ```powershell
   pytest -q
   ```

4. Review `configs/paper_reproduction.toml`. Use a new `run_id` for a logically
   separate run.

5. Open `reproduce_experiment.ipynb`, select the `rlhf` kernel, and execute the
   setup and status cells. The live-run cell is guarded by
   `CONFIRM_LIVE_API_RUN = False`.

The notebook runs one problem at a time by default, checkpoints after every
turn, and supports explicit retry and skip decisions. See
[`docs/EXPERIMENT.md`](docs/EXPERIMENT.md) for the full protocol.

## Repository map

| Location | Purpose |
|---|---|
| `reproduce_experiment.ipynb` | Supported supervised experiment entry point |
| `experiment.py` | Episode orchestration, reward calculation, retry/skip interface |
| `policy.py` | Random-forest reward model and action selection |
| `evaluation.py` | Bounded generated-code evaluation |
| `agents.py`, `prompts/` | LLM roles, structured outputs, and exact prompts |
| `data/experiment_problems_2000*` | Tracked ordered problem snapshot and provenance |
| `results_visualization.ipynb` | Historical analysis used for the submitted paper |
| `agents_and_training.ipynb` | Historical exploratory development notebook |
| `outputs/20260315_gpt_4_1_beginner_test2/` | Submitted paper-run artifacts |

## What “the paper run” means

The submitted result is one sequential online run. The reward model was updated
as transitions accumulated; it was not an epoch over a conventional fixed
training set, and no held-out evaluation was performed.

- 200 programming problems were scheduled.
- 196 interaction JSON files were saved.
- 190 problem IDs contributed numeric transitions.
- 636 state-action transitions were logged.
- Problems 102, 126, 181, and 182 were manually skipped after non-terminating
  behavior.

The reproduction snapshot contains 2,000 ordered problems. Indices 0-199 are the
exact inputs scheduled in the paper run; 200-1999 support optional extensions.
The fresh reproduction configuration attempts all 200 scheduled inputs because
generated-code evaluation is now bounded by a child-process timeout.

## Reproducibility boundaries

- New runs record resolved configuration, Git commit, prompt hashes, package
  versions, dataset hashes, and attempt events.
- Random-forest and action-sampling seeds are explicit.
- The original experiment used moving OpenAI model aliases and did not pin every
  provider generation setting. Exact language-model outputs therefore cannot be
  guaranteed even with identical local code and data.
- Code evaluation runs in a child process with a timeout so an infinite loop
  cannot freeze the notebook. This is a reliability boundary, **not a security
  sandbox**; generated code remains untrusted.
- The reward formula is preserved as implemented, including its known choice to
  use the current code score when the score changes rather than the score delta.

## Data attribution

The problem snapshot is derived from
[newfacade/LeetCodeDataset](https://huggingface.co/datasets/newfacade/LeetCodeDataset),
licensed Apache-2.0. See `data/README.md` and the tracked provenance JSON for the
source and content hashes.
