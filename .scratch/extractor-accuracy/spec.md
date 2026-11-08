# Extractor Accuracy Check

Status: ready-for-human

Replaces the extractor consistency check (`.scratch/extractor-consistency/spec.md`). Only the extractor's accuracy matters, not how stable it is between runs: each resume that has a Ground Truth Extraction is extracted 5 times and every value is compared against it.

## Ground Truth Extractions

- Move the untracked `accuracy check/` folder to `data/extraction_ground_truth/` and commit it (next to `data/candidate_ground_truth.json`).
- One file per resume, `<resume name>.json`, in the extractor's own schema. Its PDF is `Vietnamese-dataset/CnB/<resume name>.pdf` or `Vietnamese-dataset/Tech/<resume name>.pdf`; the folder it is found in decides its resume set. No manifest.
- A ground-truth file with no matching PDF is an error that stops the check before the vLLM server starts.
- Today: 5 CnB and 5 Tech resumes.

## Run

- One SLURM job, `sbatch scripts/checks/extractor_accuracy.sh [model]`, runs both resume sets on one vLLM server: CnB first, then Tech.
- `scripts/checks/extractor_accuracy.py` is run once. It extracts the CnB resumes, then the Tech resumes, setting each set's Reference Date before its extractions (Tech: 2015-12-31, CnB: today), because the Reference Date is a process-wide setting.
- Every resume is extracted 5 times. The count is fixed; there is no flag.
- Production settings: Combined Extraction only (needs a profile that can see images, `require_vision_profile` / `serve_vision_on`), extraction at `temperature=0.0`.
- A resume's runs run one after another, never in flight together, so they never write its extraction markdown at the same time (as the consistency check did). Different resumes run in parallel.
- Each run's prompt logs go to `prompt_logs/run-<n>/<resume>/`.
- Scanned Resumes are detected before any run with `find_textless_pages`, skipped, and listed in the report.
- No evaluation, no HR RAG needed.

## Output

- One run folder, `runs/extractor-accuracy`, wiped when the job starts and added to the run-folder whitelist (`src/core/config.py`, `reset_run_dir` in `scripts/lib/config.sh`).
- It holds `extraction_json/<resume>/run-<n>.json` (or `run-<n>.txt` for invalid JSON) and `accuracy_report.md` / `accuracy_report.json`.

## Comparison

- The top-level `warning` field is never compared, in either the ground truth or the AI output.
- **Strings**: trimmed with inner whitespace (line breaks included) collapsed, as the consistency check did; nothing else is normalised. Case and punctuation differences count.
- **Lists** (of objects and of strings alike) are aligned before their fields are compared:
  - similarity between two entries is the `difflib.SequenceMatcher` ratio of their whitespace-collapsed JSON;
  - an order-preserving alignment that maximises total similarity pairs ground-truth entries with AI entries; a pair needs a ratio of at least 0.5;
  - nested lists (e.g. `languages[*].certificates`) are aligned recursively inside paired entries;
  - an unpaired ground-truth entry is a **missed entry**, and an unpaired AI entry is an **extra entry**.
- Each ground-truth leaf in each run gets one outcome:
  - **correct**: same value;
  - **wrong**: both have a value and they differ;
  - **missed**: the ground truth has a value, the AI is empty or missing;
  - **invented**: the ground truth is empty, the AI has a value.
  
  Every leaf with a value in a missed entry counts as missed, and every leaf with a value in an extra entry counts as invented. An AI path the ground truth does not have at all (outside any list) counts as invented when it has a value.
- **Accuracy** = correct ÷ leaves where the ground truth has a value. Invented values are counted separately, never in that denominator.
- A wrong value also shows its 0–1 similarity (same ratio) to the ground-truth value, so a dropped bullet is told apart from an unrelated value. It does not change the outcome.
- **Failed runs** (a request that raised, invalid JSON after all retries, a Repaired Extraction, a run rejected as a Scanned Resume, an `error` key) are left out of every accuracy number and listed in the report. A run whose request raised says nothing about the model: the report is still written, and the job then exits non-zero.

## Report

The unit is one ground-truth leaf in one run. Sections in order: overall, then CnB, then Tech, each with:

1. **Summary**: accuracy; counts of correct, wrong, missed and invented; failed runs; Scanned Resumes skipped.
2. **Per section** (`basic_information`, `work_experience`, `skills`, …): accuracy, the four counts, missed and extra entries.
3. **Per field shape** (`work_experience[*].duration`): the four counts, worst first.
4. **Per resume**, worst first (only in the set sections): accuracy as the mean and the min–max across its runs, then every leaf that was not correct in every run, with the ground-truth value and each distinct AI value with its runs and its similarity. Long values (e.g. `responsibilities`) are shown in full. Missed and extra entries are listed with their runs. Failed runs are listed with their error.

`accuracy_report.json` holds the same data.

## Shared helpers

- `is_scanned_pdf`, `extraction_error` and `run_extraction` move from `extractor_consistency.py` to a new `scripts/checks/extraction_runs.py`. The accuracy check, `evaluator_consistency.py` and `evaluator_bias.py` import them from there.

## Removing the extractor consistency check

- Delete `scripts/checks/extractor_consistency.py` and `scripts/checks/extractor_consistency.sh`.
- Remove `extractor-consistency-cnb` / `-tech` from the whitelist in `src/core/config.py` and `scripts/lib/config.sh`, and add `extractor-accuracy`. The `use_consistency_run_dir` helper stays for the evaluator consistency check.
- Update the README's script and run-folder tables and the run-folder table in `docs/adr/0004-run-folders.md`.
- Set `.scratch/extractor-consistency/spec.md` to `Status: wontfix`, with one line saying this check replaces it.
- Leave `docs/research/extractor-consistency-2026-10-25.md`, the older `.scratch` specs that mention the consistency check, and the fidelity-threshold comment in `src/pipelines/extractor.py` unchanged: they are a historical record.

## Testing

Manual, by the developer. No tests are added.

## Out of scope

- Run-to-run stability (the removed consistency check).
- Comparing Fidelity Warnings or PDF Notes.
- Evaluation, the bias check and DSPy.
