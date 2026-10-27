# A missing Must-have rejects the candidate, and only HR sets Importance

> **Partly superseded by [ADR 0014](0014-nice-to-have-bonus-and-schema-enforced-criteria.md):** the schema now forces every echoed Criterion text to be exact, with one Verdict per Criterion at every Importance, so the fuzzy-match rules below no longer apply. A Nice-to-have weighs ×1 only as a bonus.
>
> **Narrowed by [ADR 0016](0016-combined-requirements-and-no-evidence-below-a-minimum.md):** evidence below a stated minimum (JLPT N3 against N2) or context without the activity a Criterion asks for is No Evidence, not Partial.

A must-have is a requirement, not a preference, so a candidate whose resume shows No Evidence for any one Must-have Criterion is now a Must-have Rejection: out, whatever the rest of the evaluation says. This reverses ADR 0006, where a Must-have only weighed ×3 and a Missing Must-Have was a flag that never rejected anyone. Partial evidence on a Must-have never rejects. A rejected candidate is still scored in every Category, so HR can judge whether the resume just left the requirement out, but is never ranked, gets no Candidate Feedback (the Review Panel does not run), and is listed in its own section on the results pages, after the ranked tiers and before the Scanned Resumes. HR un-rejects a candidate only by changing that Criterion's Importance in the HR RAG and re-evaluating; there is no override button.

ADR 0006 rejected auto-reject because resumes omit things. That risk now sits with HR: the decomposer no longer proposes an Importance at all (every Criterion it produces is Standard), so a Must-have exists only because HR chose it on the RAG page or the Verify step, where the criteria editor always warns that a missing Must-have rejects the candidate. The keyword mapping in ADR 0006 is gone, because "yêu cầu" and "phải" head whole Vietnamese requirement sections, and a wrong Must-have now removes candidates instead of shifting a weight. A Must-have no longer needs extra weight either: a candidate who passes the gate meets it, so it counts like a Standard (×2), and the weights are Must-have ×2, Standard ×2, Nice-to-have ×1. Only the Must-have Rejection sets the two levels apart.

Because a Verdict now decides a rejection, how it is tied back to its Criterion matters more than it did for a weight. The evaluator LLM never sees Importance and echoes each Criterion's text with its Verdict, and the scoring code finds the Importance by that text (ADR 0006). Only an exact echo (ignoring whitespace and case) can make a Verdict a Must-have: a fuzzy match to a Must-have reads as Standard, so a slip in the echo costs weight but never rejects a candidate for a Criterion they were not judged on, such as a Standard "3 năm kinh nghiệm Java" echoed closer to a Must-have "3 năm kinh nghiệm Python". In the other direction, every Must-have in a Category must get an exactly echoed Verdict in each run: a run that skips one or rewords it is invalid and retried like broken output, and if the retries run out the Category fails and the candidate is a Failed Evaluation. Otherwise a reworded Must-have with No Evidence would never reject anyone.

With several evaluation runs per Category, the Category shows the median-scoring run, but a Must-have rejects only when a majority of the runs (more than half) gave it No Evidence, counted across every run by exact text. One run that sorts into the middle never decides a rejection on its own.

The gate is applied only to a fully scored evaluation. A Failed Evaluation stays a Failed Evaluation that needs a rerun, even when another Category already shows a Must-have with No Evidence, because a rerun is a second chance at that Verdict too.

Every HR RAG saved before this change has Importance values the decomposer proposed, which HR may never have reviewed. Each is reset to Standard once, the first time the RAG store loads it, and the HR RAG is saved again with a marker (`importance_set_by_hr`) on every Criterion so the reset never runs twice. Evaluation reports from before the change keep their old `missing_must_haves` field, which nothing reads any more: those candidates are not rejected.

## Considered Options

- Keep the flag only (ADR 0006). Rejected: it ignores what "must-have" means, and makes scoring harder to reason about than a pass/fail gate.
- A soft gate: score cap, or sort below everyone who meets all Must-haves. Rejected: a rejected candidate still sits among the ranked ones.
- Reject on Partial evidence too. Rejected: Partial means the resume shows some of it, which is not "lacks".
- Stop evaluating at the first Must-have with No Evidence. Rejected: Categories are judged in parallel, and HR needs the scores to decide whether to rescue the candidate.
- Keep decomposer-proposed Importance and rely on HR's review. Rejected: a run with no HR review would reject candidates on a Must-have nobody chose.

## Consequences

- The bias runner, DSPy and mocks score without an Importance map, so they never apply the gate.
- A Must-have Rejection's match recommendation is `MUST_HAVE_REJECTED`, whatever the score, so every consumer of the report (the website, the PDF report, the API job result, the consistency and bias scripts, prompt training) sees the candidate is out. The overall and Category scores are still computed and stored; the website and the PDF report show "Bị loại – thiếu tiêu chí bắt buộc" with the score greyed out. The status stays `ok`.
- A Must-have the LLM keeps rewording turns the candidate into a Failed Evaluation rather than a silent pass, so HR reruns it instead of seeing a candidate wrongly ranked.
