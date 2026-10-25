# Bias check: bring up to date with the production evaluator

Status: needs-triage

`scripts/checks/evaluator_bias.py` / `.sh` and `src/bias/` drifted from the production evaluator: a generic schema with
fuzzy Criterion matching, unweighted scoring, hand-built candidate slices (so even the Baseline prompt is not the
production prompt), two suites raising `STALE`, old root paths (`output_jsons/`, `bias-result/`, `logging/bias_prompts/`)
and per-model plumbing.

## Decisions

1. **Scope**: the whole bias check: `scripts/checks/evaluator_bias.py`, `scripts/checks/evaluator_bias.sh` and `src/bias/`
   (runner, builders, registry, summary).
2. **Default model only**: no model choice. The `.sh` drops `--model` and always loads the `sea-lion-v4.5-27b`
   profile. The `.py` drops `--model` / `--concurrency`, uses `DEFAULT_LLM_MODEL` and `VLLM_MAX_CONCURRENT_REQUESTS`,
   and no longer reads `MODEL_KEY`. `MAX_EVAL_PER_SHUFFLE_KIND` is a constant (200) in the runner, not a profile value.
3. **Each bias run is one production Category run** (`ResumeEvaluator.evaluate_category`), so the Baseline prompt is
   exactly the production prompt and each Shuffle Kind only reorders that content:
   - candidate slice: `extract_relevant_resume_field(category, resume)` (raw keys, no hand-built summaries)
   - schema: `category_evaluation_schema(criteria)`; `match_criteria_evaluations`' fuzzy matching goes
   - scoring: `score_run(parsed, importance_map=rag.get_importance_map(category))`
   - temperature 0
4. **No retries**: one call per run; a broken reply is an invalid run, left out of the spread and counted.
5. **Fix the STALE suites** as `.scratch/extraction-verbatim-only/issues/01-stale-skills-bias-suites.md` proposes, then
   resolve that issue. Each suite permutes exactly the raw keys its Category receives:
   - technical_skills: permute `work_experience` entries; Atomic Interleave splits `work_experience`
   - work_experience: reorder the `work_experience` / `projects` sections; permute `projects` entries
6. **hidden_culture** stays out of scope (no bias suite).
7. **Run folder** (ADR 0010): everything the check writes goes to its own run folder (see 10), wiped when the job
   starts; it no longer writes `bias-result/` or `logging/bias_prompts/`. Update ADR 0010's line that says the bias check keeps its
   old paths.
8. **The resume under test is fixed**: `CnB - Nguyen Ho Mi Sa`, a CnB resume. It never changes, so there is no
   resume flag and no auto-pick; the `.sh`'s "extract `pdfs/` first if `output_jsons/` is empty" pre-flight goes and
   nothing reads `output_jsons/` any more. The stored HR RAG must be the CnB one before the job is submitted.
9. **Always extracted fresh**: every job first extracts the resume from its PDF with the current extractor, so the
   bias check always tests what production would produce today. The JSON's fixed location is the run folder's
   `extraction_json/CnB - Nguyen Ho Mi Sa.json`, rewritten every job.
10. **Run folder** is `runs/bias-cnb`, added to `RUN_FOLDER_NAMES`; the job takes no resume-set flag. It holds
    `bias_detection_<category>.csv` per category, `bias_summary.csv` / `report.txt` / `report.html`,
    `extraction_json/`, `prompt_logs/<category>/…` and `logs/` (job log, vLLM log).
11. **Category flags**: `--remaining` (and `CATEGORY_KEY=remaining`) goes. No flag runs all four categories;
    `--all`, the per-category flags, `--category X` and `--dry-run` stay.
12. **Not Applicable Category** (no Criteria in the HR RAG): skipped with a log line and left out of the summary, never
    tested against a made-up Criterion. A vector store whose Criteria differ from the stored HR RAG fails the category,
    as in production.
13. **5 repetitions** per category stay (`NUM_TEST_ITERATIONS`), each with its own Baseline: at temperature 0 they show
    the vLLM nondeterminism floor that ordering effects must beat.
14. **Extraction step**: `evaluator_bias.py` extracts itself with `ResumeExtractor`, `is_scanned_pdf` and
    `extraction_error`, as `evaluator_consistency.py`'s `extract_once` does; the `.sh` no longer calls
    `src/step_1_extractor.py`. The PDF is the constant `Vietnamese-dataset/CnB/CnB - Nguyen Ho Mi Sa.pdf` (missing →
    clear error). Its prompt log goes to `prompt_logs/extraction/`; the Reference Date is today.
15. **Combined Extraction, always**: the `.sh` refuses a profile that cannot see images (`require_vision_profile`),
    serves vision on (`serve_vision_on "$COMBINED_MAX_PAGES"`) and the extractor runs with `combined=True`. There is no
    text-only flag.
16. **Extraction failure stops the job**: a Scanned Resume, invalid JSON after retries, an `extraction_error`, or a
    raised request exits non-zero before any category runs.
17. **Combined Extraction everywhere** (beyond the Bias Check): there is no text-only extraction anywhere.
    - Website: `src/server.py` builds `ResumeExtractor(..., combined=True)`; `scripts/server.sh` requires a vision
      profile and serves vision on.
    - Batch: `scripts/pipeline/extract.sh` and `extract_evaluate.sh` always extract combined; `--combined` goes (and
      from `src/cli/extract.py`, which always passes `combined=True`).
    - Consistency checks: `extractor_consistency.sh` and `evaluator_consistency.sh` lose `--text` (and their `.py`s'
      `--combined`).
    - ADR 0013's "opt-in, making it the default is a later decision" is now decided: record it (new ADR superseding
      that part of 0013) and update 0013's Consequences.
18. **Vocabulary**: GLOSSARY gains **Bias Check** and **Bias Repetition** (one pass of the Baseline and every Shuffle
    Kind, compared against its own Baseline). Code identifiers (`iteration_number`) stay; user-facing log and report
    text says Bias Repetition.

## Out of scope

- hidden_culture bias suite; DSPy; the bias check for any model other than the default profile.
- No tests are added (verify by reasoning).
