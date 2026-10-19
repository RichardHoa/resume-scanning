# A Nice-to-have only adds points, and the schema forces each Verdict onto its exact Criterion

Two changes to how Verdicts become a Category score.

**Nice-to-have is a bonus.** A Nice-to-have (Ưu tiên ×1) used to count in the Category's denominator, so a candidate who lacked one lost points. To HR, a nice-to-have is something that helps when it's there and costs nothing when it isn't. A Category's 100 points are now shared only by its Must-have and Standard Criteria, by Importance weight. Each Nice-to-have adds its weight's share on top, and the score is capped at 100: `min(100, Σ all weight × verdict / Σ Must-have and Standard weight × 100)`. HR sees each Criterion's share as its Criterion Points: earned / max for a Must-have or Standard, and the bonus for a Nice-to-have, on the RAG page (a live preview), in the candidate modal and in the PDF report. A Category whose Criteria are all Nice-to-have has nothing to score against, so the criteria editor refuses to save one and evaluation stops with an error on one.

**The schema forces an exact echo.** The scoring code finds each Verdict's Importance by the Criterion text the evaluator LLM writes back. That text used to be free, and was matched exactly or else by a `difflib` ratio of 0.85 or more (ADR 0006, narrowed by ADR 0011). The model reworded, skipped and repeated Criteria often enough to give Verdicts the wrong Importance and to turn reworded Must-haves into Failed Evaluations. Each Category call now sends a JSON schema in which `"criterion"` is an `enum` of that Category's exact Criterion texts, with exactly one item per Criterion, and vLLM structured outputs enforce it. The lookup is exact, the fuzzy match is gone, and a run that still misses or repeats any Criterion, at any Importance, is retried and then fails the Category. The prompt is unchanged, and the enum's order doesn't matter.

## Considered Options

- Let the score go above 100 with Nice-to-haves. Rejected: it breaks the 0–100 gauge HR reads each Category on.
- A separate Nice-to-have tie-break number. Rejected: a second number for HR to weigh, which the overall score ignores.
- Nice-to-haves counted only when they raise the score. Rejected: harder to explain than "it only adds", for the same result in most cases.
- Short IDs (C1, C2…) instead of the exact texts in the enum. Rejected: the model can still attach the wrong ID to its reasoning, and the prompt would have to change.
- Tuning the fuzzy match. Rejected: it treats the symptom; any threshold either misses rewordings or confuses similar Criteria.

## Consequences

- A candidate who meets every Must-have and Standard in a Category scores 100 there whatever their Nice-to-haves, so Nice-to-haves can't separate candidates who are already full. When the cap applies, the Category shows "Đã đạt tối đa 100 điểm" and the rows add up to more than its 100.
- With one Standard and one Nice-to-have, the Nice-to-have is worth +50: a Nice-to-have is always half a Standard.
- The evaluator's free-text gaps and the Review Panel's weaknesses may still mention a missing Nice-to-have; only the points follow the no-penalty rule.
- Callers that score without an Importance map (the bias runner, DSPy, mocks) still treat every Criterion as Standard and keep the static schema.
