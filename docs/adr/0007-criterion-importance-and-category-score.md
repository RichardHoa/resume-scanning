# Criterion Importance, set only by HR, weights the Category score; a Nice-to-have only adds

Each Criterion has an Importance: Must-have (Bắt buộc, weight 2), Standard (Tiêu chuẩn, weight 2) or Nice-to-have (Ưu tiên, weight 1), from `IMPORTANCE_LEVELS` in `src/core/config.py`. In real hiring, missing the core language costs far more than missing a minor tool, but a plain mean of the Verdicts treated every Criterion the same.

**The Category score.** A Category's 100 points are shared only by its Must-have and Standard Criteria, by weight. Each Nice-to-have adds its weight's share on top, and the score is capped at 100:

`min(100, Σ all (weight × verdict score) / Σ Must-have and Standard weight × 100)`

To HR, a nice-to-have helps when it is there and costs nothing when it is not. A Category with only Standard Criteria scores as a plain mean. A Must-have weighs the same as a Standard, because a candidate who passes the Must-have Rejection (ADR 0008) meets it. HR sees each Criterion's share as its Criterion Points: earned out of maximum for a Must-have or Standard, and the bonus for a Nice-to-have. They appear on the RAG page (as a live preview), in the candidate modal and in the PDF report.

**Only HR sets Importance.** The decomposer makes every Criterion Standard. HR marks Must-haves and Nice-to-haves in the criteria editor (ADR 0005), which always warns that a missing Must-have rejects the candidate. Importance is a separate field, so the Criterion text stays verbatim HR text. HR Check Items have no Importance (ADR 0006).

**The schema forces each Verdict onto its exact Criterion.** The evaluator LLM never sees Importance and gives one Verdict per Criterion. The deterministic scoring code applies the weights and finds each Verdict's Importance by the Criterion text the LLM echoes back, never by position, because the Criteria Permutation bias test reorders the Criteria. Each Category call sends a JSON schema in which `"criterion"` is an `enum` of that Category's exact Criterion texts, with exactly one item per Criterion, and vLLM structured outputs enforce it. The lookup is exact. A run that still misses or repeats a Criterion, at any Importance, is retried, and if it still fails, the Category fails.

## Considered Options

- **LLM-assigned numeric weights.** Rejected: they are unstable from run to run, and HR cannot review free numbers the way they can review three levels.
- **The evaluator judging importance per candidate.** Rejected: importance is one decision per job, and it belongs where HR reviews it.
- **The decomposer proposing Importance from HR's wording** ("bắt buộc", "yêu cầu", "phải" → Must-have; "ưu tiên", "là lợi thế" → Nice-to-have). This was tried and rejected: "yêu cầu" and "phải" head whole Vietnamese requirement sections, and a wrong Must-have removes candidates.
- **Must-have weight 3.** Rejected once the Must-have Rejection existed: the gate already enforces it.
- **Nice-to-have in the denominator.** This was the first design. Rejected: candidates lost points for lacking something HR only preferred.
- **Scores above 100, a separate tie-break number, or counting a Nice-to-have only when it raises the score.** Rejected: these break the 0–100 gauge, add a second number HR has to weigh, or are harder to explain than "it only adds".
- **Free echoed text with a `difflib` fuzzy match (ratio 0.85 or more).** This was the first design. Rejected: the model reworded, skipped and repeated Criteria often enough to give Verdicts the wrong Importance, and any threshold either missed rewordings or confused similar Criteria.
- **Short IDs (C1, C2…) in the enum.** Rejected: the model could still attach the wrong ID to its reasoning, and the prompt would have to change.

## Consequences

- A candidate who meets every Must-have and Standard Criterion in a Category scores 100 there, whatever their Nice-to-haves. When the cap applies, the Category shows "Đã đạt tối đa 100 điểm", and the rows add up to more than 100.
- A Nice-to-have is always worth half a Standard. With one of each, the Nice-to-have is worth +50.
- A Category whose Criteria are all Nice-to-have has nothing to score against, so the criteria editor refuses to save it, and evaluation stops with an error if it meets one.
- The evaluator's free-text gaps and the Review Panel's weaknesses may still mention a missing Nice-to-have. Only the points follow the no-penalty rule.
- Callers that score without an Importance map (the bias runner, DSPy, mocks) treat every Criterion as Standard and keep the static schema.
