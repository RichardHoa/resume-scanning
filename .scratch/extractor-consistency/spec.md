# Extractor consistency check

Status: ready-for-agent

Replaces the outdated evaluator consistency check (`scripts/run_consistency.py`, `scripts/check_evaluator_consistency.sh`, the 20-round evaluator score CSV). This check is about extraction only: does extracting the same resume again give the same JSON, and does the extractor make errors.

## Run

- One SLURM job runs both resume sets, CnB then Tech, on one vLLM server. No `--cnb`/`--tech` flag.
- Every resume is extracted 5 times. The count is fixed; there is no flag.
- Each set uses its own Reference Date, the same as `scripts/pipeline/extract_evaluate.sh` (Tech: 2015-12-31, CnB: today).
- Combined Extraction is the default. `--text` runs text-only extraction instead. (This is the reverse of the extract/evaluate job, where text is the default and `--combined` opts in.) The default model can see images.
- Production settings: extraction stays at `temperature=0.0`, so any difference is vLLM run-to-run noise.
- No evaluation, no HR RAG needed.

## Output

- Two new run folders, `runs/consistency-cnb` and `runs/consistency-tech`, added to the run-folder whitelist (ADR 0010) and wiped when the job starts.
- Each holds all 5 extraction JSONs per resume, plus `consistency_report.md` and `consistency_report.json`.

## Comparison

- Field by field, by position: each leaf value at its path (`work_experience[0].title`) is compared across the 5 runs.
- Strings are trimmed and inner whitespace is collapsed; nothing else is normalised (case and punctuation differences count).
- A path that is missing in some runs and present in others is a difference.
- No run is the baseline: a differing field lists each distinct value with the runs that produced it.
- The `warning` field is not part of the field comparison.

## Report (per resume set)

Summary at the top:

- counts: resumes identical across all 5 runs, resumes with differences, resumes with errors, resumes with a failed run;
- Scanned Resumes, skipped (never extracted), listed once;
- the most unstable fields: field paths grouped by shape (`work_experience[*].end_date`), each with the number of resumes in which it differed.

Then one section per resume, unstable ones first:

- **Field differences**: each differing path, its distinct values and their runs.
- **Errors**: each Fidelity Warning with the runs it appeared in, and every failed run (invalid JSON after all retries, parse error). The other runs are still compared.
- **PDF Notes**: one short line; these describe the file and are not model errors.

## Implementation

- `scripts/checks/extractor_consistency.sh` (SLURM job, `sbatch scripts/checks/extractor_consistency.sh [model] [--text]`) and `scripts/checks/extractor_consistency.py` (one resume set per call, with `RUN_DIR` set).
- Fidelity Warnings are told apart from PDF Notes by `FIDELITY_WARNING_PREFIX` in `src/pipelines/extractor.py`.
- Scanned Resumes are detected before any run with `find_textless_pages`, so they cost no LLM calls.
- A Repaired Extraction is marked with `REPAIRED_EXTRACTION_WARNING` in its `warning` list (also shown on the website), and the check counts it as a failed run instead of comparing its cut-off fields.
- Each run's prompt logs go to `prompt_logs/run-<n>/<resume>/`, through `ResumeExtractor.extract(..., log_dir=...)`, so the 5 runs do not overwrite each other's raw responses.
- Testing is manual and done by the developer.

## Out of scope

- Evaluation consistency.
- A repair pass that re-asks the model to fix Fidelity Warnings (discussed and dropped).
- The bias suite and DSPy.
