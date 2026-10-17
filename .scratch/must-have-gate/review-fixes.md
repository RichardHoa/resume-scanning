Status: ready-for-agent

# Must-have gate: fixes from code review

Follow-up to `spec.md` in this folder. The must-have gate is implemented (uncommitted, in the working tree), and a code review found the problems below. The user has decided each fix. Read `spec.md`, `docs/adr/0011-must-have-rejection.md` and the **Must-have Rejection** / **Importance** entries in `CONTEXT.md` first.

Project rules: never commit, never add tests or check in a browser (verify by reasoning; `python3 -m py_compile` and `node --check` are fine).

## What is already built

- `src/core/config.py`: Must-have weight ×2 (same as Standard), Nice-to-have ×1.
- `src/pipelines/evaluator_utils.py`: `collect_must_have_rejection(dimension_results)` lists must-have Criteria with `NO_EVIDENCE` in the reported `criteria_evaluations`.
- `src/pipelines/evaluator.py` (`evaluate_resume`): `must_have_rejection` is computed only when no Category failed. It is stored on the report, and when non-empty the Review Panel is skipped (no `candidate_feedback`). The status stays `"ok"`.
- Decomposer prompt and `decompose_requirements_with_llm` return plain strings with no Importance.
- `src/providers/rag_engine.py`: `_reset_proposed_importance` does the one-time reset of old HR RAGs. **Out of scope here: the user resolved the review findings about this reset themselves.**
- Review Panel drops `must_have_rejection` / `missing_must_haves` from its input. The panel rule about Missing Must-Haves is removed. `backfill_feedback.py` skips rejected reports.
- PDF report, criteria editor warning, candidates page and Evaluate dashboard all show rejected candidates in their own section, "Bị loại – thiếu tiêu chí bắt buộc".

## Fix 1: Importance matching must not decide rejection by fuzzy match

### Background

The evaluator LLM never sees Importance. It echoes each Criterion's text with a Verdict. `match_criterion_importance` (in `evaluator_utils.py`) maps the echoed text back to a stored Criterion:
- an exact match (whitespace and case normalised) takes that Criterion's Importance;
- otherwise the most similar stored text with a `difflib` ratio of at least `IMPORTANCE_MATCH_MIN_RATIO` (0.85) takes its Importance;
- otherwise the Verdict reads as Standard.

It matches by text, never by position, because the Criteria Permutation bias test reorders the Criteria. Before the gate, a wrong match only changed a weight. Now it decides rejection:

- **A. A missed Must-have never rejects.** Must-have "Tốt nghiệp đại học chuyên ngành CNTT". The model echoes "Bằng đại học CNTT" with NO_EVIDENCE, which is below the 0.85 ratio, so it reads as Standard and the candidate is not rejected. The same happens if the model skips the Criterion entirely.
- **B. A wrong rejection.** Must-have "3 năm kinh nghiệm Python", Standard "3 năm kinh nghiệm Java". The model echoes the Java one with a slip that happens to be closer to the Python text, so the Java NO_EVIDENCE inherits Must-have and a candidate who meets the Python Must-have is rejected.

### Decided fix

1. **Only an exact match can make a Verdict a Must-have.** In `match_criterion_importance`, the exact (normalised) match keeps any Importance. The fuzzy fallback may still assign Standard or Nice-to-have, but if the closest match is a Must-have it returns Standard (a fuzzy match costs only weight, never a rejection). This removes B.
2. **Every Must-have in a Category must get a Verdict.** After a category run is validated, check that each must-have Criterion in that Category's `importance_map` has an exactly matched entry in `criteria_evaluations`. If any is missing, treat that run as failed, so it goes through the normal retry path (`evaluate_category` retries, the later ones at `CATEGORY_EVAL_RETRY_TEMPERATURE`). If it still fails after retries, the Category fails and the candidate becomes a Failed Evaluation that needs a rerun. This removes A.
   - A good place is `validate_category_evaluation` (it already receives `importance_map`; returning `None` makes the run invalid) or right after it in `evaluate_category` (`src/pipelines/evaluator.py` ~line 211).
   - Callers without an Importance map (bias runner, DSPy, mocks) are unaffected: no map means no must-haves to check.
3. Update ADR 0011 (and the ADR 0006 superseded note if needed) to record that Must-have Importance needs an exact echo, and that an unjudged Must-have fails the Category.

## Fix 2: Reject only when most runs give No Evidence

### Background

With `num_evaluations > 1`, `_evaluate_single_category` (`src/pipelines/evaluator.py` ~lines 270–300) sorts the runs by score and keeps the median run's whole result, including its `criteria_evaluations`. `collect_must_have_rejection` reads only that run, so rejection depends on which run sorts into the middle. For example, runs 1 and 3 give the Must-have STRONG and run 2 (the median) gives NO_EVIDENCE, so the candidate is rejected.

### Decided fix

A must-have Criterion counts toward a Must-have Rejection only when it got NO_EVIDENCE in **a majority** of that Category's runs (more than half of `num_evaluations`; with one run that is just that run). Match Criteria across runs by exact normalised text, the same as Fix 1.
- Keep the per-run must-have verdicts available to `collect_must_have_rejection`, e.g. store a small per-category `must_have_no_evidence_counts` / run count on `cat_res` before the median run is picked, and have `collect_must_have_rejection` read that instead of the median run's verdicts.
- The displayed `criteria_evaluations` stays the median run's (no UI change).

## Fix 3: The evaluator marks the recommendation itself

### Background

A rejected report keeps its computed `match_recommendation` (e.g. `STRONG_MATCH`) and `status: "ok"`. Only `candidates.js`, `evaluator.js` and `candidate_report.py` special-case `must_have_rejection`, so other consumers see a match: `scripts/run_consistency.py`, `src/bias/*`, `src/cli/train_prompts.py` (reads `match_recommendation`), the API job result, and server logs.

### Decided fix

- In `evaluate_resume`, when `must_have_rejection` is non-empty, set `match_recommendation` to `"MUST_HAVE_REJECTED"`. The overall score and Category scores stay as computed. `status` stays `"ok"`.
- Front ends can then key off the recommendation:
  - `candidates.js`: `matchPill`, `isMustHaveRejection`
  - `evaluator.js`: `mustHaveRejection` usages and `RECOMMENDATION_LABELS` (add `MUST_HAVE_REJECTED: 'Bị loại – thiếu tiêu chí bắt buộc'`). A `rec-MUST_HAVE_REJECTED` CSS class is needed in `src/static/css/components-buttons.css`, styled like `.rec-REJECT`, or keep mapping it to `rec-REJECT`.
  - `candidate_report.py`: `_match`

  Keep reading `must_have_rejection` for the list of missing Criteria.
- Check anything that switches on `match_recommendation` values and would mis-handle the new value: `src/cli/train_prompts.py` (~line 152) and the candidates page status filter in `applyCandidateFiltersAndSort`.
- Update ADR 0011's Consequences line, which currently says the recommendation is still computed and stored.

## Not doing

- Review findings about the one-time Importance reset (destructive rewrite, cross-process race): out of scope, the user resolved them.
- `CATEGORY_EVAL_MAX_TOKENS` 4096 → 8192 in `config.py`: the user's own pre-existing change, not part of this work.
- Duplicated rejection label and the duplicated `mustHaveRejection` between the two JS controllers: left as is, matching how existing labels like "Lỗi – cần chạy lại" are already duplicated.
