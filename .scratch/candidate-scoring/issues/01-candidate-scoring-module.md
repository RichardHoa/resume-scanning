# 01: Move Candidate scoring into one module, with no rule changes

**What to build:**

Every rule that turns Verdicts into a Match Recommendation moves into one pure scoring module. Spec: `.scratch/candidate-scoring/spec.md`. The rules are:

- Verdict values and Importance weights
- the Nice-to-have bonus and its cap
- Criterion Points
- the lower median of a Category's runs, and which run HR is shown
- Must-have No Evidence counts and the majority Must-have Rejection gate
- Not Applicable reweighting and the failed-Category pass
- the Overall Score, the Match Recommendation thresholds, the `status`, and the `MUST_HAVE_REJECTED` override

Today these sit in the evaluator, its backend and its utils. After the change, the evaluator only runs LLM calls and assembles and saves the report.

This is a refactor only. For the same resume and the same LLM replies, every saved evaluation report is unchanged, key for key and value for value. The website, the PDF report, the Review Panel and the API therefore need no change.

- **Two entry points:**
  - `score_run(parsed, importance_map=None)`. It does exactly what per-run validation and scoring do today, and returns None to mean "retry". The retry loop and the bias runner use it.
  - `score_candidate(outcomes, num_evaluations, language)` returns a `CandidateScore`. Its seven fields are `dimension_scores`, `category_timings`, `overall_score`, `match_recommendation`, `status`, `must_have_rejection` and `failed_categories`.
- **`CategoryOutcome` NamedTuple** replaces the positional `(name, cat_res, retrieved, elapsed)` tuple. Its fields are `name`, `retrieved`, `runs`, `elapsed` and `error`.
  - `score_candidate` builds the Not Applicable, crashed-Category and median entries itself, with their Vietnamese/English text unchanged.
  - The failed-run dict produced after max retries stays with the retry loop.
- **Kept on purpose:** every quirk the spec lists under "Kept on purpose" is carried over unchanged. Existing expressions are moved, not rewritten.
- **Removed:**
  - the old scoring functions, with no re-exports;
  - the evaluator's aggregation wrapper;
  - the two unused module aliases.
- **Untouched:** the LLM-call wrappers that the bias runner and the API call.
- **Bias runner:** only its import changes.
- **Logging:**
  - The `[Eval Validation]` print stays inside `score_run`.
  - The `[Timing Log]` and `[FAILED EVALUATION]` lines move to the evaluator, with the same text. The timing lines print together after scoring.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] A new pure scoring module holds rules (a)–(d) from the spec. Its only side effect is the one `[Eval Validation]` print. It makes no LLM calls, does no file I/O and does not take `resume_name`.
- [ ] `score_run` returns the same dict (or None) as the old per-run validation for every input, with and without an Importance map.
- [ ] `score_candidate` returns values that, copied into the report, give exactly the same `status`, `overall_score`, `match_recommendation`, `dimension_scores`, `execution_timings.category_timings_seconds`, `must_have_rejection` and `failed_categories` as before.
- [ ] Every report path keeps its exact output: Not Applicable Category, crashed Category, a Category with a failed run, Failed Evaluation, Must-have Rejection, and mock mode.
- [ ] The old scoring functions, the aggregation wrapper and the two unused aliases are gone. No caller imports them.
- [ ] The bias runner's behaviour is unchanged. Only its import was updated.
- [ ] The log lines keep their text. Only when the timing lines appear has changed.
- [ ] No rule, prompt, schema, report key, JS, GLOSSARY.md or ADR is changed.
- [ ] Testing is manual and done by the developer. The implementer verifies by reasoning that each moved expression matches the original, and adds no tests.
