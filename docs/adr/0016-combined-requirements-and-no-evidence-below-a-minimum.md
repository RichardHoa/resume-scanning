# Combined Requirements are flagged for HR to split, and a minimum not reached is No Evidence

The Tech evaluator consistency run (`runs/evaluator-consistency-tech/evaluator_consistency_report.md`, 53 resumes × 5 Repeat Evaluations) found the Must-have Rejection flipping between evaluations of the same resume. Every one of the 73 Verdict differences was between neighbouring Verdicts (43 Strong ↔ Partial, 30 Partial ↔ No Evidence, none Strong ↔ No Evidence), and the reasoning on both sides was nearly identical: the model agreed on the facts and split on the label. The Must-have that flipped most, "Riêng BrSE: JLPT N2 trở lên + kinh nghiệm thực chiến giao tiếp kỹ thuật", joins two requirements. A candidate with N3, or no JLPT at all, but some Japan experience reads as "partial or related match", and Partial never rejects (ADR 0011), so candidates HR meant to reject passed in most evaluations. Two changes close this.

**Combined Requirements are flagged at intake.** A Criterion is HR's text copied verbatim, so the decomposer cannot split a line; only HR can rewrite it. The scrutiny call that asks the Clarification Questions now also lists each Combined Requirement per field under `split_suggestions`, as `{"requirement", "parts"}`: the line exactly as HR wrote it and the separate lines HR could write instead. They are shown under the questions beside each field, up to `SCRUTINY_MAX_SPLITS_PER_FIELD` (8), and don't count against the 1–5 questions, which would otherwise lose their seniority and education probes to a job description full of combined lines. The prompt tells the model never to flag a list of examples or alternatives (items in parentheses, "hoặc", "ít nhất 1", "thể hiện qua…"), since splitting "DB (MySQL, MS SQL, MongoDB...)" would demand all three. A suggestion whose requirement is not in HR's text (ignoring whitespace), or that has fewer than two distinct parts, is dropped; a reply without `split_suggestions` is malformed and retried, like one missing a question list. It is non-blocking: HR may ignore it, and the panel shows if there are questions or suggestions.

**The evaluator rubric names two cases that are always No Evidence.** A stated minimum not reached (JLPT N3 or an uncertified Japanese level against "JLPT N2 trở lên", about 2 years against "3 năm trở lên") is No Evidence, also when the Criterion joins that minimum with parts the candidate does meet. Context without the activity a Criterion asks for (the client's country, Japanese project names, the employer's market, with no described client communication) is No Evidence too. This holds the N2 gate even when HR keeps a Combined Requirement as one line.

## Considered Options

- Let the decomposer split Combined Requirements itself. Rejected: Criteria are verbatim HR text, and a split the LLM invents would be judged and could reject candidates on wording HR never wrote.
- Ask about splits as Clarification Questions. Rejected: they share the 1–5 limit with the questions that probe seniority and education, and a split is a rewrite to suggest, not a meaning to confirm.
- A per-criterion rule for compound criteria (Strong = every part, Partial = some, No Evidence = none) instead of the minimum rule. Rejected on its own: a candidate with experience but no N2 would still be Partial and pass the gate HR set.
- Check JLPT levels in code. Not done now: it covers one kind of minimum, while the rubric rule covers years and levels in any Criterion.

## Consequences

- This narrows ADR 0011's "Partial means the resume shows some of it": evidence below a stated minimum is not "some of it".
- Candidates who had Partial on a minimum they don't reach now get No Evidence; on a Must-have that is a Must-have Rejection, and on a Standard Criterion it costs the Partial's half points. Results from before this change aren't directly comparable.
- The Clarification Question flow is otherwise unchanged: asked once per pass, and the check runs again only if HR returns from Category review with changed text.
- Testing is manual, done by the developer; re-run `scripts/checks/evaluator_consistency.sh --tech` to measure the effect.
