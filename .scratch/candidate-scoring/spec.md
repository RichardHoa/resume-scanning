Status: ready-for-agent

# Candidate scoring: one module from Verdicts to Match Recommendation

Requirement collection only. Nothing here is implemented yet. Every question raised while grilling is settled.

**This is a refactor only. No rule changes.** The same resume with the same LLM replies gives the same Category Scores, Criterion Points, Overall Score, Match Recommendation, Must-have Rejection and report JSON as before. The rules kept are those of ADR 0006, 0011, 0012 and 0014, as GLOSSARY.md states them (Category Score, Overall Score, Match Recommendation, Criterion Points, Must-have Rejection, Not Applicable Category, Failed Evaluation).

## Problem Statement

The rules that turn Verdicts into a Match Recommendation are spread over four modules:

- `src/pipelines/evaluator_utils.py`: `validate_category_evaluation` (Verdict values, Importance weights, Nice-to-have bonus and cap, Criterion Points, the one-Verdict-per-Criterion check), `count_must_have_no_evidence`, `collect_must_have_rejection`.
- `src/pipelines/evaluator.py`: `_evaluate_single_category` (lower median, which run is shown, `all_scores`, failed flag, the Not Applicable entry), `_evaluate_all_categories` (the crashed-Category entry), `evaluate_resume` (the Must-have gate, `status`, the `MUST_HAVE_REJECTED` override).
- `src/pipelines/evaluator_backend.py`: `aggregate_evaluation_results` (Not Applicable reweighting, the failed-Category pass, Overall Score, thresholds).
- `src/core/importance.py`: `base_weight`, `criterion_max_points`.

Each recent scoring change (Must-have Rejection, sampled runs, the Nice-to-have bonus) had to touch all four. The modules are joined by shallow wrappers on `ResumeEvaluator` and by a `(name, cat_res, retrieved, elapsed)` tuple that `aggregate_evaluation_results` unpacks by position.

## Decisions

### The module

- **New file `src/pipelines/scoring.py`.** It is pure: no LLM calls, no file I/O, no `resume_name`. The one exception is a single `print` (see Logging).
- **Inside it:**
  - (a) per-run Verdict scoring;
  - (b) combining a Category's runs;
  - (c) combining Categories into the Overall Score and Match Recommendation;
  - (d) the Must-have Rejection gate, `status` and the `MUST_HAVE_REJECTED` override.
- **Outside it:** `src/core/importance.py` stays where it is, because the HR RAG side (`rag_engine.py`, `rag_exporter.py`) uses it too, and `scoring.py` imports it. Assembling the report dict, the Review Panel and saving also stay in the evaluator.
- **The old functions are removed, not re-exported:**
  - `validate_category_evaluation`, `count_must_have_no_evidence` and `collect_must_have_rejection` from `evaluator_utils.py`;
  - `aggregate_evaluation_results` from `evaluator_backend.py`.

### The interface: two entry points

- **`score_run(parsed, importance_map=None) -> run dict | None`**
  - It does exactly what `validate_category_evaluation` does today, including returning None when not every Criterion got exactly one Verdict.
  - The retry loop in `evaluate_category` uses None to decide on a retry.
  - Without an Importance map, every Criterion is Standard, which gives a plain mean. The bias runner depends on this.
  - The returned dict's keys and values are unchanged.
- **`score_candidate(outcomes, num_evaluations, language) -> CandidateScore`**
  - `outcomes` holds one `CategoryOutcome` per Category.
  - It runs steps (b), (c) and (d).

### `CategoryOutcome` (input, a NamedTuple)

It replaces the positional tuple and has these fields:

- `name`
- `retrieved`: the Criterion texts
- `runs`: each run's dict from `score_run`, or the failed-run dict after retries run out
- `elapsed`
- `error`: the exception text, if the Category crashed

From these, `score_candidate` builds three entries the evaluator builds today:

- the **Not Applicable** entry, when `retrieved` is empty (`evaluator.py:273-282`);
- the **crashed-Category** entry, when `error` is set (`evaluator.py:347-359`);
- the **combined median** entry (`evaluator.py:303-318`).

The Vietnamese/English text in these entries stays word for word, chosen by `language`.

The failed-run dict after max retries (`evaluator.py:237-244`) stays in `evaluate_category`. It is that run's result and mentions the retry count.

### `CandidateScore` (output)

It has seven fields:

- `dimension_scores`
- `category_timings`
- `overall_score`
- `match_recommendation`: already `MUST_HAVE_REJECTED` when it applies
- `status`: `ok` / `error`
- `must_have_rejection`
- `failed_categories`

The evaluator copies these into the report dict under their current keys. The report JSON stays exactly the same, so the website, the PDF report, the Review Panel and the API need no change.

### Kept on purpose (do not clean up in this change)

- The explicit-`"score"` fallback in per-run scoring. Mock replies and old outputs use it.
- The failed-Category pass only acts on Categories whose score is already `FALLBACK_ERROR_SCORE` (0). There it clears `median_score` and `all_run_scores`, as today.
- The `0.20` fallback weight for a Category missing from `DIMENSION_WEIGHTS`.
- A Category with one failed run out of three keeps its median score in `dimension_scores`. It is still a Failed Evaluation and is not ranked.
- The branch for a Category missing from the outcomes. It cannot be reached today and is kept as is.
- Mocks keep scoring without an Importance map (`importance_map = {} if self.mock`, in the evaluator).
- The existing expressions are moved as they are, not rewritten, so floating-point rounding stays the same.

### Wrappers

- **Delete** `ResumeEvaluator._aggregate_evaluation_results` and the unused module aliases `_validate_category_evaluation` and `_clean_and_deduplicate_list` (`evaluator.py:58-59`).
- **Keep** `_call_vllm_backend`, `_decompose_requirements_with_llm`, `_extract_relevant_resume_field` and `_save_evaluation_report`. They are not scoring. The bias runner and `api/evaluation.py:92` call the first two.
- **Bias runner:** `src/bias/runner.py` only changes its import from `validate_category_evaluation` to `score_run`. Its behaviour does not change.

### Logging

- `score_run` keeps its one `print`, `[Eval Validation] Not every Criterion got exactly one Verdict: [...]`, exactly as it is.
- `[Timing Log] … Category '…' evaluation took … (Median Score: …)` moves to the evaluator, with the same text. It now prints for every Category together after `score_candidate` returns, instead of as each Category finishes.
- `[FAILED EVALUATION] …` moves to the evaluator, with the same text, and is built from `failed_categories`.
- Only when these lines appear changes.

### Domain docs

- GLOSSARY.md gains **Category Score**, **Overall Score** and **Match Recommendation**. These are done.
- No new ADR. Putting the scoring in one module is a code arrangement that is easy to undo.

## Out of scope

- Writing a `kind` / `band` field into reports, or aligning the PDF report's band with the website's (architecture review candidate 02).
- Removing the explicit-score fallback, or mocks producing Verdict JSON (candidate 07).
- Any change to the HR RAG, the criteria editor, or the JS.

## Testing

Testing is manual and done by the developer. Verify the change by reasoning through the code: each moved expression matches the original, and every key in the saved report keeps its value.
