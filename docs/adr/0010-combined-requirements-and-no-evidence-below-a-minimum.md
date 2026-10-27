# Combined Requirements are flagged for HR to split, and a minimum not reached is No Evidence

The Tech evaluator consistency run (53 resumes × 5 Repeat Evaluations) found the Must-have Rejection flipping between evaluations of the same resume. All 73 Verdict differences were between neighbouring Verdicts (43 Strong ↔ Partial, 30 Partial ↔ No Evidence, none Strong ↔ No Evidence). The reasoning on both sides was nearly identical: the model agreed on the facts and split on the label. The Must-have that flipped most, "Riêng BrSE: JLPT N2 trở lên + kinh nghiệm thực chiến giao tiếp kỹ thuật", joins two requirements. A candidate with N3, or no JLPT at all, but some Japan experience reads as a "partial or related match". Partial never rejects (ADR 0008), so candidates HR meant to reject passed in most evaluations. Two changes close this gap.

**Combined Requirements are flagged at intake.** A Criterion is HR's text copied verbatim, so the decomposer cannot split a line; only HR can rewrite it. So the requirement scrutiny call also lists each Combined Requirement per field under `split_suggestions`, as `{"requirement", "parts"}`: the line exactly as HR wrote it, and the separate lines HR could write instead. These appear beside each field, up to `SCRUTINY_MAX_SPLITS_PER_FIELD` (8), and they do not count against the 1–5 Clarification Questions. The prompt tells the model never to flag a list of examples or alternatives (items in parentheses, "hoặc", "ít nhất 1", "thể hiện qua…"), because splitting "DB (MySQL, MS SQL, MongoDB...)" would demand all three. A suggestion is dropped if its requirement is not in HR's text (ignoring whitespace) or if it has fewer than two distinct parts. A reply without `split_suggestions` is malformed and retried. The suggestions do not block anything: HR may ignore them.

**The evaluator rubric names two cases that are always No Evidence.** The first is a stated minimum not reached: JLPT N3, or an uncertified Japanese level, against "JLPT N2 trở lên", or about 2 years against "3 năm trở lên". This holds even when the Criterion joins that minimum with parts the candidate does meet. The second is context without the activity a Criterion asks for: the client's country, Japanese project names or the employer's market, with no described client communication. The rubric keeps the N2 gate even when HR keeps a Combined Requirement as one line.

## Considered Options

- **The decomposer splitting Combined Requirements itself.** Rejected: Criteria are verbatim HR text, and a split the LLM invents would be judged, and could reject candidates on wording HR never wrote.
- **Asking about splits as Clarification Questions.** Rejected: they would share the 1–5 limit with the questions that probe seniority and education, and a split is a rewrite to suggest, not a meaning to confirm.
- **A per-Criterion rule for compound Criteria alone** (Strong for every part, Partial for some, No Evidence for none). Rejected: a candidate with experience but no N2 would still be Partial and pass the gate HR set.
- **Checking JLPT levels in code.** Not done for now: it covers one kind of minimum, while the rubric rule covers years and levels in any Criterion.

## Consequences

- A candidate who was Partial on a minimum they do not reach now gets No Evidence. On a Must-have that means a Must-have Rejection, and on a Standard Criterion it costs the Partial's half points.
- Re-run `scripts/checks/evaluator_consistency.sh --tech` to measure the effect.
