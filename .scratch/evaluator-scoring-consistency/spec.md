# Evaluator scoring consistency: Criterion Scores averaged over the runs, and a rubric anchored at the observed boundaries

Status: ready-for-agent

Fixes R1 and R2 from `docs/research/evaluator-consistency-2026-10-31.md`. R3 (splitting Combined Requirements in the Tech HR RAG) is a separate step HR takes, with no code.

## Problem Statement

When HR re-evaluates the same candidate from the same extraction, the result still moves. In the latest Tech evaluator consistency run (53 resumes × 5 Repeat Evaluations), 68 of 901 Criterion Verdicts changed (7.5%), 38 resumes had at least one changed Verdict, and the Overall Score moved by 3.6 points on average and by 18.8 at most (Vo Tan Vuong_BrSE). HR can't trust a ranking whose order changes when nothing about the candidate changed.

There are two causes, and they make each other worse:

- **The vote turns a borderline Criterion into a jump.** Each Category is judged in 5 runs, and runs 2–5 sample on purpose (ADR 0009). Each Criterion's score is the score of its voted Verdict. On borderline evidence, 3 Strong / 2 Partial scores 1.0 and the next evaluation's 2 Strong / 3 Partial scores 0.5, so one sampled run's change of mind moves the Criterion's whole value. In a Category with 2 Criteria, that moves the Overall Score by about 12.5 points.
- **The rubric leaves the boundaries the runs split on undefined.** 66 of the 68 changes are between neighbouring Verdicts (33 Partial ↔ Strong, 33 No Evidence ↔ Partial), and both sides usually cite the same facts. The model agrees on the evidence and splits on the label, at points the rubric never decides:
  - evidence that is only implied ("uses Java" for "Nắm OOP");
  - a Criterion that joins several parts, some of which are shown ("Phát triển, kiểm thử và bảo trì…", 22.6%, the worst Criterion);
  - what a "partial or related match" is ("wrote test scripts" for "Phối hợp QA để fix bug");
  - how to count years (whether the internship counts decided Vo Tan Vuong's Strong ↔ No Evidence flip on "3 năm"; Cao Ba Loc got Partial for 2 years 9 months, which the rubric already says is No Evidence).

## Solution

Two changes, made together.

1. **Criterion Score.** Each Criterion is scored by the mean of its runs' Verdict scores (Strong 1, Partial ½, No Evidence 0), not by the score of the voted Verdict. Five runs that split 3 Strong / 2 Partial give 0.8, and 2 / 3 gives 0.7, so a split vote moves the score a little instead of all the way. The Category Score and Criterion Points are computed from the Criterion Scores. HR still sees one Verdict per Criterion, voted exactly as today, now shown with how many runs gave it (e.g. "3/5 lần"). The Must-have Rejection is unchanged: it still needs a majority of No Evidence.
2. **Anchored rubric.** The evaluator rubric names a fixed Verdict for each boundary the runs split on: implied evidence, a Criterion with several parts, what counts as a related match, and how years of experience are counted. Years stay counted by the LLM (ADR 0001: the evaluator gets no pre-computed work-history summaries), but by fixed rules. Internships count toward years only when the Criterion says so, so HR decides by how they word the Criterion.

## User Stories

1. As an HR user, I want re-evaluating the same candidate to give nearly the same Overall Score, so that I can trust the ranking.
2. As an HR user, I want a Criterion on which the runs disagree to move the Category Score a little, not by its full points, so that one sampled run can't reorder my candidates.
3. As an HR user, I want a Category with only 2 Criteria to stop swinging the Overall Score by about 12 points between evaluations, so that Position & Seniority Match is as dependable as the larger Categories.
4. As an HR user, I want to keep seeing one Verdict per Criterion (Strong, Partial or No Evidence), so that the report still reads as a decision and not as a number.
5. As an HR user, I want to see how the runs split behind each Verdict (e.g. "3/5 lần"), so that I can tell a clear Verdict from a borderline one.
6. As an HR user, I want a Verdict all runs agreed on to show no split, or the full count (5/5), so that unanimous Verdicts stand out from close ones.
7. As an HR user, I want a Criterion's earned Criterion Points to match its Criterion Score (e.g. 0.8 of 10 points is 8.0), so that the rows still explain the Category Score.
8. As an HR user, I want a Criterion every run judged Strong to still earn its full points, and one every run judged No Evidence to earn none, so that clear cases score as before.
9. As an HR user, I want a single-run evaluation to score exactly as it does today, so that `num_evaluations=1` stays deterministic.
10. As an HR user, I want the Must-have Rejection to keep rejecting only when most runs gave No Evidence, so that averaging never rejects or rescues a candidate on its own.
11. As an HR user, I want the shown Verdict of a Must-have to be No Evidence exactly when it rejects the candidate, as today, so that the report and the rejection always agree.
12. As an HR user, I want a Nice-to-have to add its Criterion Score's share of its bonus, capped at the Category's 100 as today, so that Nice-to-haves still only add.
13. As an HR user, I want a Criterion whose runs split with no majority to keep showing, as today, the reasoning of a run that gave Partial, or the "the runs disagreed" reasoning when none did, so that I know why it shows Partial.
14. As an HR user, I want the candidate modal, the RAG page preview and the PDF report to show the same Verdict, split and Criterion Points, so that every view agrees.
15. As an HR user, I want evidence only implied by a language, framework, tool or job title (C# for OOP, "Developer" for testing) to always get Partial, so that the same resume doesn't flip between Strong and Partial.
16. As an HR user, I want Strong to require the skill named, or a described task that is that skill, so that Strong means the resume actually shows it.
17. As an HR user, I want a Criterion that joins several required parts to be Strong when every part is shown, Partial when some are, and No Evidence when none are, so that "Phát triển, kiểm thử và bảo trì…" is judged the same way every time.
18. As an HR user, I want a stated minimum not reached to stay No Evidence even inside a Criterion with several parts (ADR 0010), so that the new parts rule never turns a missed JLPT N2 back into Partial.
19. As an HR user, I want a list of examples or alternatives ("DB (MySQL, MS SQL, MongoDB...)", "ít nhất 1 stack: …") never treated as several required parts, so that one of them is enough, as I meant.
20. As an HR user, I want a "related match" to need a described activity of the same kind (e.g. "wrote unit tests" for "phối hợp QA"), so that Partial means something specific.
21. As an HR user, I want a tool or a process the activity usually involves (Git for code review, Jira for working with BA/PM), with no described activity, to be No Evidence, so that it is treated like the existing context-without-activity rule.
22. As an HR user, I want years of experience counted by fixed rules, so that two runs reading the same work history reach the same total.
23. As an HR user, I want overlapping jobs counted once, so that two jobs at the same time don't double the years.
24. As an HR user, I want a job that is still current ("Hiện tại", "present", "nay") to run to the Reference Date, so that the Tech set (Reference Date 2015-12-31) and today's sets are counted correctly.
25. As an HR user, I want a period whose dates the resume doesn't state to not count toward years, and the reasoning to say so, so that a guess never decides a minimum.
26. As an HR user, I want internships, part-time and student jobs to count toward years only when the Criterion says so (e.g. "kể cả thực tập"), so that I decide by how I word the Criterion.
27. As an HR user, I want the reasoning of a years Criterion to state the total it counted and which periods it counted, so that I can check the arithmetic.
28. As an HR user, I want the requirement check to ask whether internships count when a requirement states a number of years, so that I remember to say so in the Criterion.
29. As an HR user, I want the glossary and ADRs to describe the new scoring and rubric rules, so that the next change doesn't undo them.
30. As a developer, I want the evaluator consistency report to also show each Criterion's Criterion Score spread across Repeat Evaluations, so that I can see the averaging work even where the shown Verdict still changes.
31. As a developer, I want the Category Score and Overall Score spreads in the consistency report computed from the new scores, so that I can compare a re-run with the 3.6 / 18.8 baseline.
32. As a developer, I want the scoring code to stay pure (no LLM call, no file I/O), so that it remains easy to reason about.
33. As a developer, I want callers that score without an Importance map (bias runner, DSPy, mocks) to keep working, so that nothing outside this change breaks.

## Implementation Decisions

### Criterion Score (R1)

- **New domain term: Criterion Score.** A Criterion's value from 0 to 1: the mean of the Verdict scores (Strong 1, Partial ½, No Evidence 0) of the runs that judged it. With one run it is that run's Verdict score. Add it to GLOSSARY.md, and update the definitions of Category Score, Criterion Points and Verdict so that they say the score comes from the Criterion Score and the shown Verdict comes from the vote.
- **Scoring module (`src/pipelines/scoring.py`).** The per-Criterion vote stays, but now only decides the shown Verdict, its reasoning and quotes, and the representative run's free text, exactly as today. Next to it, the voting step works out each Criterion's Criterion Score and puts it in the Criterion's `score` field, which `_score_criteria` already weights by Importance. So `_score_criteria`, the Nice-to-have cap and Criterion Points need no new rule: `earned_points` becomes max points × Criterion Score, rounded to 0.1 as now.
- **The split HR sees.** Each voted Criterion carries a count of the runs per Verdict (e.g. `verdict_runs: {"STRONG_EVIDENCE": 3, "PARTIAL_EVIDENCE": 2, "NO_EVIDENCE": 0}`) and the number of runs that judged it. The candidate modal (`candidate-report-view.js`), the RAG page preview where it shows Verdicts, and the PDF report (`candidate_report.py`) show beside the Verdict a tag with the count of runs that gave it, e.g. "3/5 lần", or "không thống nhất" when no run gave the shown Partial, and leave it out when there was only one run. The RAG page preview shows no Verdicts, so it is unchanged.
- **Must-have Rejection: unchanged.** It still counts No Evidence runs per Must-have and rejects on a majority (ADR 0008). The shown Verdict still comes from the same vote, so it is No Evidence exactly when it rejects.
- **A Criterion a run skipped** (possible only without an Importance map) is averaged over the runs that judged it, as the vote already counts only those runs.
- **Failed runs and mock replies.** The existing fallback to the median run is untouched. A failed run already fails the Category.
- **`median_score` and `all_run_scores`** stay the runs' own scores, as today.
- **ADR 0009** is amended. The "Evaluation runs" paragraph says each Criterion is scored by its Criterion Score, with the vote kept for the shown Verdict and the Must-have gate. Add a considered option, "Scoring the voted Verdict", rejected because a split vote moved a Criterion's full points between Repeat Evaluations; cite the consistency run's numbers and the research note.
- No migration: old reports and RAGs are wiped and re-run.

### Anchored rubric (R2)

- **Evaluator system prompt (`get_evaluator_system_prompt` in `src/prompts/evaluator_prompts.py`).** Rewrite PARTIAL_EVIDENCE's definition and add the rules below beside the two existing "always NO_EVIDENCE" cases. Each rule names one Verdict. Keep the existing two cases word for word.
  1. **Implied evidence is PARTIAL_EVIDENCE.** A skill or practice only implied by a language, framework, tool, job title or project type is PARTIAL_EVIDENCE (C# or Java for OOP, a "Developer" title for testing). STRONG_EVIDENCE needs the resume to name the skill or describe a task that is that skill.
  2. **Several required parts.** When a criterion joins several things the candidate must each show (e.g. developing, testing and maintaining), judge each part. Every part shown is STRONG_EVIDENCE, some is PARTIAL_EVIDENCE, none is NO_EVIDENCE. A stated minimum not reached is still NO_EVIDENCE, whatever the other parts show (the existing rule wins). A list of examples or alternatives, where any one is enough (items in parentheses, "hoặc", "ít nhất 1", "thể hiện qua…"), is not several required parts. This wording matches the Combined Requirement definition the scrutiny prompt already uses.
  3. **What a related match is.** PARTIAL_EVIDENCE through a related match needs a described activity of the same kind as the one the criterion asks for (e.g. writing unit tests for coordinating with QA). A tool or a process that the activity usually involves, with no described activity (Git for code review, Jira for working with BA/PM), is context without the activity, so NO_EVIDENCE.
  4. **Counting years of experience.** When a criterion states a number of years, add up the periods of the work history entries that the criterion counts:
     - overlapping periods count once;
     - a period still running ("Hiện tại", "present", "nay", or the same in another language) ends at the current date the prompt already states (the Reference Date);
     - a period whose start or end the resume doesn't state doesn't count, and the reasoning says so;
     - internships, part-time and student jobs count only when the criterion says they do;
     - count in whole months.

     The reasoning states the total in years and months and lists the periods it counted. The result is then judged against the minimum under the existing rule.
- **The JSON schema and the order "evidence → reasoning → verdict" are unchanged.**
- **Requirement scrutiny prompt (same module).** Where it already asks what counts as relevant experience for a number of years, it also asks whether internships count, so that HR writes the answer into the Criterion. Scrutiny stays advisory and web-only (ADR 0009).
- **No code computes years.** ADR 0001 keeps the evaluator free of pre-computed work-history summaries, and each job's `duration` is a verbatim free-text string in any language. The new ADR below records this.
- **New ADR, `docs/adr/0012-anchored-verdict-boundaries.md`.** It records the four rules and why each Verdict was picked. It explains why years stay counted by the LLM under fixed rules (ADR 0001, verbatim durations in any language), and why internships are decided by the Criterion's wording (HR owns the Criterion, with no new setting or UI). It also explains how rule 2 coexists with ADR 0010's rejection of a parts rule on its own: the minimum-not-reached rule takes precedence.
- **GLOSSARY.md "Verdict"** lists the new rules next to the two always-No-Evidence cases.

### Evaluator consistency check

- `scripts/checks/evaluator_consistency.py` adds, per (resume, Criterion), the Criterion Score of each Repeat Evaluation, and to the summary the mean and largest Criterion Score spread (max − min) across Repeat Evaluations. It reads the score from the report and keeps the "Verdict change rate", which now counts changes in the shown Verdict. The `.scratch/evaluator-consistency/spec.md` Comparison and Report sections get one line each for this.

## Testing Decisions

- Following this repo's practice, no automated tests are added and nothing is checked in a browser. The implementing agent checks correctness by reasoning through the code paths:
  - a single run;
  - 5 unanimous runs;
  - a 3/2 split;
  - a no-majority split: 2 Strong / 2 No Evidence / 1 Partial shows Partial with the Partial run's reasoning ("1/5 lần") and scores 0.5; 2 Strong / 2 No Evidence with no Partial run (4 runs judged it) shows the "runs disagreed" reasoning ("không thống nhất");
  - a Must-have with 3 of 5 No Evidence, which rejects and shows No Evidence, with a Criterion Score from 0 to 0.4, so its row can show some earned points;
  - a Nice-to-have over the cap;
  - a call without an Importance map.
- The developer measures the effect by re-running `scripts/checks/evaluator_consistency.sh --tech` on the compute machine and comparing it with the 2026-10-31 baseline:
  - Verdict change rate 7.5%;
  - Overall Score spread mean 3.6 and largest 18.8;
  - 1 changed Match Recommendation;
  - the flip rate on the six most unstable Criteria.
- Step 0(c) of the research note can be done before the re-run: recompute the old run's scores from its saved per-run Verdicts.
- The developer runs any test manually.

## Out of Scope

- R3: splitting the Combined Requirements in the Tech HR RAG (HR's step), and a per-part checklist in the schema.
- R4: sampling settings (top-p/top-k from the model card) and per-run seeds.
- R5: changing Category weights or Criterion counts for small Categories.
- R6: vLLM batch-invariant mode (blocked for this model's Gated DeltaNet layers).
- Verdict probabilities from token logprobs (the G-Eval variant of R1).
- Computing years of experience in code, and any new extraction field.
- A setting or UI control for whether internships count.
- The bias runner, the consistency scripts other than the one change above, and DSPy, apart from not breaking them.
- Migrating old reports or RAGs.

## Further Notes

- R1 reduces score movement, not necessarily changes in the shown Verdict. Judge it by the Overall Score spread, Match Recommendation changes and the new Criterion Score spread. R2 is the change aimed at the Verdict change rate.
- The rubric rules make some Verdicts stricter. Some former Strongs become Partial (implied evidence). Some former Partials become No Evidence (tool or process without the activity, or undated or internship periods under a years minimum). On a Must-have, a new No Evidence means a Must-have Rejection. Expect lower scores on the Tech set, and look at the Must-have Rejections after the re-run.
- The Verdicts in rules 1–3 are a first choice. If HR wants a different level at one of these boundaries, change that rule's level: the point is that each boundary has exactly one.
