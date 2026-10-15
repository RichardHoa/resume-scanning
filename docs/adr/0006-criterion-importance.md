# Criterion Importance weights Verdicts inside a Category

Every Criterion in a Category used to count the same: the Category score was the plain mean of its Verdicts. In real hiring, missing the core language costs far more than missing a minor tool, and the Clarification Questions already ask HR which requirements are must-haves, but nothing carried the answer into scoring. Each Criterion now has an Importance: Must-have (weight 3), Standard (2) or Nice-to-have (1), from the fixed `IMPORTANCE_WEIGHTS` in `src/core/config.py`. The Category score is `Σ(weight × verdict score) / Σ(weight) × 100`, so a Category of only Standard Criteria scores exactly as before.

The decomposer proposes an Importance from HR's own wording ("bắt buộc", "yêu cầu", "phải", "must", "required" → Must-have; "ưu tiên", "là lợi thế", "điểm cộng", "preferred", "a plus", "nice to have" → Nice-to-have; anything else → Standard), and HR changes it per Criterion in the criteria editor when reviewing the HR RAG (ADR 0005). Importance is a separate field: the Criterion text stays verbatim (ADR 0003). HR Check Items have none, since they are never scored (ADR 0004). A stored Criterion without one (an older HR RAG, a plain-string payload) reads as Standard.

The evaluator LLM never sees Importance and still gives one Verdict per Criterion. The deterministic scoring code applies it, finding each Criterion's Importance by matching the LLM's echoed criterion text (exact after normalising whitespace and case, else the closest at a `difflib` ratio of 0.85 or more, else Standard), never by position, because the Criteria Permutation bias test reorders the Criteria. So the bias tests (Shuffle Kinds) are unaffected.

A Must-have Criterion with No Evidence is recorded as a Missing Must-Have on the evaluation, shown to HR and given to the Review Panel. It never rejects the candidate, who is still ranked and gets Candidate Feedback.

## Considered Options

- LLM-assigned numeric weights. Rejected: unstable from run to run, and HR can't review free numbers the way they can review three levels.
- The evaluator judging importance per candidate. Rejected: importance is one decision per job, which belongs at decomposition where HR can review it (the same argument as ADR 0004).
- Nice-to-haves as bonus points only. Rejected: it breaks the 0–100 scale and the `MATCH_THRESHOLDS`.
- Auto-reject on a missing must-have. Rejected: resumes omit things, so HR decides.

## Consequences

- A PARTIAL_EVIDENCE on a Must-have only costs weight and raises no flag.
- There is no score cap for a Missing Must-Have yet; the overall match can still reach STRONG with one.
- Callers that score without an Importance map (the bias runner, DSPy, mocks) keep the unweighted mean.
