Status: needs-triage

# Criterion Points: exact Verdict matching, a per-Criterion points breakdown, and Nice-to-have as a bonus

Requirement collection only. Nothing here is implemented yet. Every question raised while grilling is settled.

## Problem Statement

1. **The Verdict-to-Criterion matching is unstable.** The evaluator LLM writes each Criterion's text back freely in `"criterion"`. The scoring code finds the Importance from that echo (`match_criterion_importance`, `src/pipelines/evaluator_utils.py`): an exact match ignoring case and whitespace, otherwise a `difflib` fuzzy match at 0.85 or more, otherwise Standard. When the model rewords, skips or repeats a Criterion, the Verdict can get the wrong Importance, a Standard or Nice-to-have can quietly drop out of the score or be counted twice, and a reworded Must-have makes the run invalid and can end as a Failed Evaluation. `CATEGORY_EVALUATION_SCHEMA` lets `"criterion"` be any string, so nothing forces an exact copy.
2. **HR can't see where a Category's points come from.** The Category gauge shows "x / 100", but not how much each Criterion is worth or how much it earned.
3. **A missing Nice-to-have (Ưu tiên ×1) lowers the score.** Its weight is in the denominator, so lacking it costs points. HR's intent: having it raises the score, and lacking it never costs anything.
4. **The candidate cards use different Category labels** (`dimShortNames` in `candidates.js`, e.g. "Cấp bậc") from the modal and the RAG page (`CATEGORY_NAMES` in `criteria-editor.js`, e.g. "Vị trí & Số năm kinh nghiệm"), and list the Categories in a different order.

## Decisions

### Exact matching (replaces the fuzzy match)

- **The schema forces an exact echo.** For each Category evaluation call, the JSON schema is built from that Category's Criteria: `"criterion"` is an `enum` of the exact stored Criterion texts, and `criteria_evaluations` has `minItems = maxItems =` the number of Criteria. vLLM structured outputs then rule out any other text.
- **The prompt doesn't change.** The order of the enum doesn't matter.
- **The Importance lookup is a plain dictionary lookup** on the exact text. `match_criterion_importance`'s fuzzy branch, `IMPORTANCE_MATCH_MIN_RATIO`, and the "only an exact echo can make a Must-have" special case are removed: every echo is now exact.
- **Every Criterion is judged exactly once, or the run is invalid.** This applies at every Importance level, not just Must-haves (it replaces `_unjudged_must_haves`). A run with a missing or doubled Criterion is retried like broken JSON. If retries run out, the Category fails and the candidate is a Failed Evaluation.

### Nice-to-have is a bonus that never costs points

- **Category score** = `min(100, (Σ Must-have/Standard weight × verdict + Σ Nice-to-have weight × verdict) / Σ Must-have/Standard weight × 100)`. Verdict values stay Strong 1, Partial 0.5, No Evidence 0.
- Nice-to-haves only ever add to the numerator. A candidate who meets every Standard scores 100 with or without them, and a missing Nice-to-have costs nothing.
- **The cap is per Category** (each Category's own gauge is 0–100). The overall 0–100 score and `MATCH_THRESHOLDS` are unchanged.
- **A Category needs at least one Bắt buộc or Tiêu chuẩn Criterion.** Otherwise the formula has no base. The criteria editor (RAG page and Verify step) blocks saving a Category whose Criteria are all Ưu tiên, with a message on that Category such as "Nhóm này cần ít nhất một tiêu chí Bắt buộc hoặc Tiêu chuẩn". As a fallback, evaluation stops with an error on such an HR RAG.
- The Must-have Rejection is unchanged (ADR 0011).
- **Prompts are unchanged.** The evaluator never sees Importance, so its free-text gaps and the Review Panel's weaknesses may still mention a missing Nice-to-have. Only the points follow the no-penalty rule.

### Criterion Points: the breakdown HR sees

The points are **within each Category's own 100**, not shares of the candidate's overall 100.

- A Bắt buộc or Tiêu chuẩn Criterion is worth `weight / Σ(Bắt buộc + Tiêu chuẩn weights) × 100`. A Ưu tiên is worth a bonus of `1 / Σ(same) × 100`.
  - 2 Tiêu chuẩn + 1 Ưu tiên → 50 / 50, Ưu tiên +25.
  - 1 Tiêu chuẩn + 1 Ưu tiên → 100, Ưu tiên +50 (accepted as intended).
- **Earned points** = max points × verdict value (Partial earns half).
- **Computed in Python and stored in the report.** Each entry of `criteria_evaluations` gets `max_points` and `earned_points`, and the modal and the PDF report only read them.
- **The RAG page shows a live preview.** Next to each Criterion the criteria editor shows "33.3 điểm" or "+16.7 điểm thưởng", updating as HR changes an Importance. This needs a small JS copy of the same formula. After evaluation, the report's stored points are the source of truth.
- **Candidate modal:** each Criterion row shows earned / max, e.g. "25 / 50" for a Partial. Ưu tiên rows show "+25" under "Tiêu chí đáp ứng" when met, and "+0 · không trừ điểm" under "Tiêu chí chưa có bằng chứng" when missing.
- **When a Category reaches the cap**, the rows still show the points earned (e.g. 50/50, 50/50, +25), with one Category-level note: "Đã đạt tối đa 100 điểm".
- **PDF candidate report:** an earned/max column per Criterion, following the same rules.
- **Rounding:** one decimal place. Rows may add up to 99.9 while the gauge shows 100, because the gauge uses the unrounded score.

### Candidate card labels

- Remove `dimShortNames` from `candidates.js`. The pool card imports `CATEGORY_NAMES`, and lists the Categories in the same order as the modal and the RAG page (seniority → skills → experience → education → culture). The longer names may wrap.

## Out of scope

- Migration of old evaluation reports or HR RAGs: stored data is deleted whenever this lands.
- The bias runner, consistency scripts and DSPy, beyond not breaking their imports if `CATEGORY_EVALUATION_SCHEMA` changes shape.

## To do when this is built

- New ADR: Nice-to-have becomes a no-penalty bonus capped at the Category's 100, superseding ADR 0006's rejected "Nice-to-haves as bonus points only" option and the fuzzy text matching that ADRs 0006 and 0011 describe. It also records the schema-enforced exact echo.
