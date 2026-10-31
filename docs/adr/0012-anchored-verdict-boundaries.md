# The rubric fixes one Verdict at each boundary the runs split on; years stay counted by the LLM

The 2026-10-31 Tech evaluator consistency run (53 resumes × 5 Repeat Evaluations, `docs/research/evaluator-consistency-2026-10-31.md`) still found 68 of 901 Criterion Verdicts changing. 66 of them were between neighbouring Verdicts (33 Partial ↔ Strong, 33 No Evidence ↔ Partial), and both sides usually cited the same facts. The model agreed on the evidence and split on the label at points the rubric never decided. So the evaluator rubric now names one Verdict for each of those points, next to the two always-No-Evidence cases of ADR 0010:

- **Implied evidence is Partial.** A skill only implied by a language, framework, tool, job title or project type (Java for "Nắm OOP") is Partial. Strong needs the skill named, or a described task that is that skill. Partial rather than Strong, because the resume never shows the skill itself. Partial rather than No Evidence, because it is still evidence about the candidate.
- **Several required parts.** Strong when every part is shown, Partial when some are, No Evidence when none are ("Phát triển, kiểm thử và bảo trì…", the most unstable Criterion at 22.6%). A list of examples or alternatives is not several parts, in the same wording as the Combined Requirement check (ADR 0010).
- **A related match is a described activity of the same kind** (unit tests for "Phối hợp QA"). A tool or process the activity usually involves, with no described activity (Git for code review), is No Evidence, like ADR 0010's context without the activity.
- **Years of experience are counted by fixed rules:**
  - overlapping periods count once;
  - a current job runs to the Reference Date;
  - a period without a stated start or end does not count;
  - the count is in whole months;
  - the reasoning lists the periods and the total.

  Internships, part-time and student jobs count only when the Criterion says so. Requirement scrutiny asks HR about it when a requirement states a number of years.

**The always-No-Evidence cases win.** ADR 0010 rejected a parts rule on its own because a candidate with experience but no N2 would be Partial and pass the Must-have. Here a stated minimum not reached stays No Evidence, whatever the parts rule gives.

**Years stay counted by the LLM.** ADR 0001 keeps the evaluator free of pre-computed work-history summaries. Each job's `duration` is also a verbatim string in any format and any language ("03/2012 - Hiện tại", "2013年4月〜現在"). So a code parser would be fragile, and it would hand the evaluator a number HR can't check against the resume. Fixed counting rules, with the counted periods written into the reasoning, give the same reproducibility, and HR can check the result.

**Internships are decided by the Criterion's wording.** HR owns the Criterion text (ADR 0005), so a Criterion that wants internships counted says so ("kể cả thực tập"). This needs no new setting or UI, and the rule is visible where the Criterion is.

## Considered Options

- **Computing years in code from each job's duration.** Rejected: it goes against ADR 0001, and parsing free-text durations in any language is fragile.
- **A per-HR-RAG setting for whether internships count.** Rejected: a new control for one rule, kept apart from the Criterion it changes.
- **Always counting, or never counting, internships.** Rejected: whether an internship is experience is a hiring decision that differs from job to job.
- **Leaving the boundaries to the model's judgement.** Rejected: that is what the runs split on.

## Consequences

- Some Verdicts get stricter: implied Strongs become Partial, and a tool without the activity, or an undated or internship period under a years minimum, becomes No Evidence. On a Must-have, a new No Evidence is a Must-have Rejection.
- Each rule's Verdict is a choice HR can change. The point is that each boundary has exactly one Verdict.
- Re-run `scripts/checks/evaluator_consistency.sh --tech` to measure the effect.
