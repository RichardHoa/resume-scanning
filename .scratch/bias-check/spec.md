# Bias check: bring up to date with the production evaluator

Status: needs-triage

`scripts/checks/evaluator_bias.py` / `.sh` and `src/bias/` drifted from the production evaluator: a generic schema with
fuzzy Criterion matching, unweighted scoring, hand-built candidate slices (so even the Baseline prompt is not the
production prompt), two suites raising `STALE`, old root paths (`output_jsons/`, `bias-result/`, `logging/bias_prompts/`)
and per-model plumbing.

Decisions 1–18 were implemented on 2026-10-25 (`d280c0f`). Decisions 19–26 (2026-11-15) were implemented on
2026-11-15: the Bias Check now combines each ordering's runs as production combines a Category's 5 runs.

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
13. **5 repetitions** per category stay (`NUM_TEST_ITERATIONS`, now set from `DEFAULT_NUM_EVALUATIONS`; decision 19). Each
    ordering's runs across them are combined into its Category Score (decisions 20, 23), and the 5 single-run Baseline
    scores are still shown as the vLLM nondeterminism floor.
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

## Compare production Category Scores, not single runs (2026-11-15)

Since `d6a4cc8` / `19c0782` / `50463cb` (ADR 0009), production judges each Category in `DEFAULT_NUM_EVALUATIONS` (5)
greedy runs of the **same** prompt. Each Criterion's Criterion Score is the mean of its runs' Verdict scores, HR sees
the voted Verdict, and the Category Score comes from the Criterion Scores (`_vote_criteria` in
`src/pipelines/scoring.py`). The 5 runs never reorder anything, so they only absorb vLLM run-to-run noise.

The Bias Check already makes 5 greedy runs of every ordering: `build_experiments` runs once per category, before the
Bias Repetition loop in `src/bias/runner.py`, so `run_index` N is the same ordering in every Bias Repetition. Its
summary still compares each single run against its own Bias Repetition's single Baseline (`delta_from_baseline` in
`summary.py`, `total_spread_delta` and the "POSITIONAL / PLACEMENT BIAS DETECTED" verdict in `runner.py`). So one
Verdict flipped by vLLM noise counts as an ordering effect, and a change is reported at its full single-run size,
when production would move the score by a fifth of that per run.

19. **The Bias Repetition count is the production run count**: `NUM_TEST_ITERATIONS` in `src/bias/runner.py` becomes
    `DEFAULT_NUM_EVALUATIONS` (imported from `src/core/config.py`), so if production changes its run count, the Bias
    Check follows. The call path does not change. It stays one greedy call per run with no retries (decision 4), so
    there are no extra LLM calls.
20. **Each ordering's 5 runs are combined as production combines a Category's runs**: the Criterion Score mean, the
    voted Verdict and the Category Score from the Criterion Scores. This reuses the code in `src/pipelines/scoring.py`
    and never writes a second copy: `_vote_criteria` is made public as `vote_criteria` and the Bias Check calls it
    (`combine_orderings` in `src/bias/summary.py`). The
    Baseline's 5 runs are combined the same way into the **Combined Baseline**.
21. **A failed run fails its ordering**: an ordering with any invalid run among its 5 has no combined score. It is
    counted as failed and left out of the percentages, as a failed run fails its Category in production
    (`has_category_failure` in `_combine_category`). If the Combined Baseline fails, every ordering in that category
    counts as failed.
22. **The per-run CSV stays the raw data**: `bias_detection_<category>.csv` keeps one row per run, so
    `python3 -m src.bias.summary runs/bias-cnb` can still rebuild everything without re-running. It gains
    `c<i>_importance` per Criterion (from the importance map, `Standard` for mocks), which the summary needs to combine
    runs. `delta_from_baseline` / `c<i>_delta` in that CSV stay per run, as a record of the raw call.
23. **The summary (`bias_summary.csv`, `report.txt`, `report.html`) compares combined scores**: one ordering = one
    combined score, compared with the Combined Baseline. Per shuffle kind it reports:
    - `orderings` and `failed`, replacing `runs`
    - `changed_pct`, the change buckets, `went_up_pct`, `went_down_pct` and `biggest_change`, all over combined scores
    - new: `verdict_changed_pct`, the % of orderings where at least one voted Verdict differs from the Combined
      Baseline's (what HR would see change)
    - `baseline_scores` stays: the 5 single-run Baseline scores, showing the single-run noise floor
    - new: `combined_baseline`, the Combined Baseline score
24. **The runner's console summary and `evaluator_bias.py`'s overall table use combined scores**: min / max / spread
    over the orderings' combined scores, with the Combined Baseline in place of `all_results_matrix[0]["score"]`. The
    "POSITIONAL / PLACEMENT BIAS DETECTED" verdict is decided on the combined spread. `affected_criteria` /
    `num_criteria_affected` in the returned summary are counted from voted Verdicts, not single-run score deltas.
25. **Vocabulary** (GLOSSARY):
    - **Bias Check**: each ordering is judged as one production Category Score: its 5 greedy runs, combined as
      production combines them. Each ordering's score is compared against the Combined Baseline.
    - **Bias Repetition**: one of the `DEFAULT_NUM_EVALUATIONS` greedy runs of every ordering. The differences between
      the single-run Baselines still show how much one run moves with no reordering.
    - **Baseline**: the Combined Baseline is compared against, not "the Baseline of the same Bias Repetition".
    - Add **Combined Baseline**: the Baseline's 5 runs combined into one Category Score, the score every ordering is
      compared against.

    Code identifiers (`iteration_number`) stay, as in decision 18.
26. **Docs brought up to date with the code**. Each line below was checked against the code on 2026-11-15:
    - `docs/adr/0007-criterion-importance-and-category-score.md` line 32 says "Callers that score without an Importance
      map (the bias runner, DSPy, mocks)". Wrong: the bias runner passes the HR RAG's importance map
      (`src/bias/runner.py:139`). DSPy is gone (`src/cli/train_prompts.py`, `scripts/dspy/train.sh` are deleted). Only
      mock replies score without one: make it "Mock replies score without an Importance map: every Criterion is
      Standard and the schema stays static."
    - `docs/adr/0008-must-have-rejection.md` line 23 says "The bias runner, DSPy and mocks score without an Importance
      map, so they never apply the gate". Make it "Mock replies score without an Importance map, so they never apply
      the gate." Add that the Bias Check scores with the importance map but compares Category Scores and does not
      apply the gate, which is decided per candidate (`score_candidate`). Line 22's "prompt training" (DSPy) goes from
      the list of report consumers.
    - `docs/adr/0009-evaluation-runs-and-temperatures.md` line 30 says "The bias runner has its own call path at
      temperature 0, so the bias suite is unaffected". Replace it with: the Bias Check runs each ordering in
      `DEFAULT_NUM_EVALUATIONS` greedy runs with no retries (a retry samples at 0.5, mixing sampling noise into the
      ordering effect) and combines them as production does, so its scores are production Category Scores of a
      reordered prompt.
    - `GLOSSARY.md`: the Bias Check, Bias Repetition and Baseline entries, and the new Combined Baseline entry, as
      decision 25 says.
    - `src/bias/report_template.html`: the intro ("moved from the Baseline of the same Bias Repetition") and the
      failed-run note describe combined orderings and the Combined Baseline.
    - Docstrings and comments that say "one production Category run per ordering" or "compared against the Baseline of
      the same Bias Repetition": `src/bias/runner.py` (`NUM_TEST_ITERATIONS` comment, `run_single_category_bias_test`),
      `src/bias/summary.py` (module docstring, `summarize_shuffle_kind`), and the header of
      `scripts/checks/evaluator_bias.sh`.
    - Decision 13 above (5 Bias Repetitions as "the vLLM nondeterminism floor that ordering effects must beat") now
      reads as decisions 19 and 23 say: the 5 runs are combined, and the 5 single-run Baseline scores are still shown
      as the noise floor.
    - Unchanged, checked: `README.md` (lines 49, 53, 78, 147), `docs/adr/0004-run-folders.md` and
      `docs/adr/0011-agent-framework-only-for-review-panel.md` already match the code.

## Out of scope

- hidden_culture bias suite; DSPy; the bias check for any model other than the default profile.
- No tests are added (verify by reasoning).
