# Evaluator consistency check

Status: ready-for-agent

The companion of the extractor consistency check (`.scratch/extractor-consistency/spec.md`). This check is about evaluation only: if HR re-evaluates the same candidate, from the same extraction, do the Verdicts, Category Scores, Overall Score and Match Recommendation stay the same, and when a Verdict flips, why.

## Run

- One SLURM job per resume set: `sbatch scripts/checks/evaluator_consistency.sh [model] --cnb|--tech [--text]`. Exactly one of `--cnb`/`--tech` is required, as in `scripts/pipeline/evaluate.sh`. Only one HR RAG is stored (ADR 0005), so HR sets the matching HR RAG on the website before each submit. `require_hr_rag` runs before the vLLM server starts.
- Each set uses its own Reference Date, as in `scripts/pipeline/extract_evaluate.sh` (Tech: 2015-12-31, CnB: today).
- **Extraction once:** each resume is extracted once at the start of the job. Combined Extraction is the default and `--text` runs text-only extraction, as in the extractor check. All 5 Repeat Evaluations read that one extraction JSON, so every difference comes from the evaluator.
  - Scanned Resumes are detected with `find_textless_pages` before any LLM call, skipped and listed once.
  - A resume whose extraction fails (invalid JSON, Repaired Extraction, error) is listed once with the reason and not evaluated.
- **5 Repeat Evaluations per resume.** The count is fixed and there is no flag. Each is a full production evaluation (`evaluate_resume` with `DEFAULT_NUM_EVALUATIONS`): `DEFAULT_NUM_EVALUATIONS` Category runs (run 1 at `temperature=0.0`, later runs sampled, ADR 0009), each Criterion's Verdict voted across them, and the Must-have majority vote. So the check measures what HR would see on a re-evaluation.
- No Review Panel: `generate_feedback=False`.

## Output

- Two run folders, `runs/evaluator-consistency-cnb` and `runs/evaluator-consistency-tech`. They are added to the run-folder whitelist (ADR 0010) and the job wipes its own set's folder at start. The website never reads them.
- Each holds:
  - the one extraction per resume (`extraction_json/<resume>.json`);
  - each Repeat Evaluation's report as `evaluation_json/<resume>/eval-<n>.json`;
  - prompt logs under `prompt_logs/eval-<n>/<resume>/`, so the 5 evaluations never overwrite each other's, and the extraction's under `prompt_logs/extraction/<resume>/`;
  - `evaluator_consistency_report.md` and `.json`.
- **Rename:** the extractor check's folders become `runs/extractor-consistency-cnb` and `runs/extractor-consistency-tech`. Update the whitelist, `use_consistency_run_dir`, `extractor_consistency.sh`'s echo lines and ADR 0010's consequence line. Old folders are not migrated.

## Comparison (per resume, across the 5 Repeat Evaluations)

No Repeat Evaluation is the baseline: each differing item lists its distinct values with the evaluations that produced them.

- **Outcome:** status (scored, Failed Evaluation, Must-have Rejection with the Must-haves it names), Match Recommendation, and Overall Score (min, max, max−min, and each value with its evaluations).
- **Per Category:** the Category Score, each value with its evaluations. A Not Applicable Category is left out.
- **Per Criterion:** the Verdict HR sees, meaning the Verdict voted across the Category's runs, with each distinct Verdict and its evaluations.
- **Reasoning:** never compared as text, because sampled runs always word it differently. Only for a Criterion whose Verdict differs, the report shows one reasoning per distinct Verdict, side by side, so the reader sees why it flipped.
- **Failed Evaluation:** a Repeat Evaluation that is a Failed Evaluation is counted and listed with its failed Categories, and the others are still compared. A request that failed (server down, timeout, rejected) is reported like the extractor check's raised runs. The report is kept and the job exits non-zero.

## Report (per resume set)

The header states the resume set, the extraction mode, the Reference Date, 5 Repeat Evaluations × `DEFAULT_NUM_EVALUATIONS` Category runs, and the HR RAG's stored requirement text, so the reader knows which job the set was judged against.

Summary:

- **Counts:**
  - resumes stable across all 5 (same status, Match Recommendation and every HR-visible Verdict);
  - resumes whose Match Recommendation changed;
  - resumes where any Verdict changed;
  - the Verdict change rate: of every (resume, Criterion) pair compared, how many had a differing Verdict. Unlike the count above, it does not grow just because the HR RAG is split into more Criteria;
  - resumes with a Failed Evaluation;
  - Scanned Resumes skipped (listed);
  - failed extractions skipped (listed).
- **Overall Score spread:** the mean max−min across resumes, and the largest max−min with its resume.
- **Most unstable Criteria:** each Criterion's text and Category, with the number of resumes in which its Verdict differed, the number of resumes it was compared in, and that change rate, most first.

Then one section per resume, least stable first: a changed Match Recommendation, then a changed status or Must-have Rejection, then the largest Overall Score spread, then the number of changed Verdicts, then name. Each section shows the outcome, Category Score and Verdict differences, the side-by-side reasoning for each flipped Verdict, and any Failed Evaluations.

## Implementation

- `scripts/checks/evaluator_consistency.sh` (the SLURM job) and `scripts/checks/evaluator_consistency.py` (one resume set per call, with `RUN_DIR` set). They are modelled on the extractor check's pair and reuse its Scanned Resume detection and extraction error handling where they can.
- Testing is manual and done by the developer.

## Out of scope

- Ranking stability (rank or Tech top-10 changes across the Repeat Evaluations).
- Candidate Feedback / Review Panel consistency.
- Running both sets in one job, or storing an HR RAG per set.
- The bias suite and DSPy.
