# A missing Must-have rejects the candidate

A must-have is a requirement, not a preference. So a candidate whose resume shows No Evidence for any one Must-have Criterion gets a Must-have Rejection, whatever the rest of the evaluation says. Partial Evidence never rejects. But evidence below a stated minimum is No Evidence, not Partial (ADR 0010).

A rejected candidate is still scored in every Category, so HR can judge whether the resume just left the requirement out. But the candidate is never ranked and gets no Candidate Feedback, because the Review Panel does not run. Rejected candidates are listed in their own section on the results pages, after the ranked tiers and before the Scanned Resumes. HR can un-reject a candidate only by changing that Criterion's Importance in the HR RAG and re-evaluating. There is no override button.

The risk that "resumes omit things" sits with HR: a Must-have exists only because HR chose it (ADR 0007).

**Across evaluation runs.** Each Category is judged in several runs (ADR 0009). The Category shows the median-scoring run, but a Must-have rejects only when more than half of the runs gave it No Evidence, counted across every run by its exact Criterion text. So no single run decides a rejection.

**Only a fully scored evaluation is gated.** A Failed Evaluation stays a Failed Evaluation that needs a rerun, even when another Category already shows a Must-have with No Evidence, because a rerun is also a second chance at that Verdict.

## Considered Options

- **A flag only: Missing Must-Have, with weight ×3.** This was the first design. Rejected: it ignores what "must-have" means, and makes scoring harder to reason about than a pass/fail gate.
- **A soft gate: a score cap, or sorting below everyone who meets all Must-haves.** Rejected: a rejected candidate would still sit among the ranked ones.
- **Rejecting on Partial evidence too.** Rejected: Partial means the resume shows some of it, which is not the same as lacking it.
- **Stopping evaluation at the first Must-have with No Evidence.** Rejected: Categories are judged in parallel, and HR needs the scores to decide whether to rescue the candidate.

## Consequences

- A Must-have Rejection's Match Recommendation is `MUST_HAVE_REJECTED`, whatever the score, so every consumer of the report (the website, the PDF report, the API job result, the checks, prompt training) sees that the candidate is out. The scores are still computed and stored. The website and the PDF report show "Bị loại – thiếu tiêu chí bắt buộc" with the score greyed out. The status stays `ok`.
- The bias runner, DSPy and mocks score without an Importance map, so they never apply the gate.
