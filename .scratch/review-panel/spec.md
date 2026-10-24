Status: ready-for-agent

# Review Panel: Candidate Feedback after evaluation

## Problem Statement

After a candidate is evaluated, the HR user gets five Category scores, short per-Category strengths and gaps, and an overall score with a match recommendation. Nothing pulls these into one readable view of the candidate. HR still has to read every Category card, compare it against the resume and the requirements, and work out what to ask in the interview. The foundation paper's "resume summarizer agent" (§4.3) solves this with a panel of reviewers who discuss the candidate and agree on feedback. This pipeline has nothing like it.

When one Category fails during evaluation, the evaluator sets that Category to 0 and still produces an overall score and a match recommendation. HR sees a candidate ranked low for a reason that has nothing to do with the candidate, with no signal that the result can't be trusted.

The pipeline also defaults to a model (Qwen3.5-35B-A3B) that is no longer the team's choice. The web batch evaluation is hard-capped at 20 concurrent candidates, which leaves the vLLM server underused.

## Solution

- **Review Panel.** After a candidate's evaluation succeeds, a Review Panel of three Panelists discusses the candidate. The Panelists are **Leadership**, **Domain Expertise** and **People & Culture**.
  - Each Panelist first writes an independent view.
  - Then, in a single **Rebuttal Round**, each Panelist reads the other two views and responds.
  - Finally a **Coordinator** merges the final views into **Candidate Feedback**.
- **Candidate Feedback is for HR.** It contains:
  - an overall summary
  - strengths
  - weaknesses and missing skills
  - things to check in the interview
  - each Panelist's final view, so HR can see where each point came from

  It is written in the evaluation's language (Vietnamese by default). It never changes any score.
- **One button.** On the web app, HR still clicks only Evaluate. Each candidate goes straight from evaluation to its Review Panel. The candidate counts as done once its Candidate Feedback is ready, has failed, or was skipped.
- **Failed Evaluations stop the line.** If any Category fails, the whole evaluation is a Failed Evaluation:
  - The candidate is shown as "Lỗi – cần chạy lại" ("Error – needs a rerun").
  - Its partial score is kept in the report but not ranked or shown as a result.
  - No Candidate Feedback is produced.

  HR reruns the candidate by selecting it and clicking Evaluate again.
- **Batch on the cluster.** Command-line evaluation produces Candidate Feedback by default. A new SLURM script fills in Candidate Feedback for a directory of existing evaluation reports.
- **New default model and throughput.** `aisingapore/Qwen-SEA-LION-v4.5-27B-IT` becomes the default model for every LLM call in the pipeline, with thinking off. The whole process keeps up to 70 requests in flight against the vLLM server.

## User Stories

### Candidate Feedback on the web

1. As an HR user, I want a written summary of each candidate after evaluation, so that I don't have to piece one together from five Category cards.
2. As an HR user, I want the candidate's strengths as bullet points, so that I can scan them quickly.
3. As an HR user, I want the candidate's weaknesses and missing skills as bullet points, so that I can see the gaps against my requirements at a glance.
4. As an HR user, I want a list of things to check in the interview, so that I know what to ask about where the resume leaves doubt.
5. As an HR user, I want to see each Panelist's final view, so that I can trace a point in the summary back to the perspective it came from.
6. As an HR user, I want the Panelist views collapsed by default in the candidate modal, so that the summary stays the first thing I read.
7. As an HR user, I want the Candidate Feedback in Vietnamese, so that I can read it as easily as the rest of the app.
8. As an HR user, I want the Candidate Feedback to judge the candidate against the job I described, so that a junior applicant and a director applicant with similar resumes get different feedback.
9. As an HR user, I want a Domain Expertise view that covers the actual skills of the role, technical or not, so that feedback for non-technical roles is still meaningful.
10. As an HR user, I want a People & Culture view that relates to my Hidden Requirements, so that my soft and culture-fit criteria are discussed explicitly.
11. As an HR user, I want a Leadership view, so that I see leadership potential even for roles where it isn't the main criterion.
12. As an HR user, I want the Panelists to respond to each other before the summary is written, so that the feedback reflects a balanced view rather than three separate opinions pasted together.
13. As an HR user, I want the scores I see to stay exactly what the evaluator produced, so that the feedback never quietly changes a candidate's ranking.
14. As an HR user, I want a Panelist to be able to say it disagrees with a score in its text, so that I learn about questionable scores without the score changing.

### One-button flow and progress

15. As an HR user, I want evaluation and Candidate Feedback to happen behind the single Evaluate button, so that I don't have to start a second step.
16. As an HR user, I want the batch progress counter to count a candidate only when its Candidate Feedback is done, so that "7/20 ứng viên" means 7 candidates are fully ready.
17. As an HR user, I want the waiting-time estimate to include feedback generation, so that the estimate matches how long I actually wait.
18. As an HR user, I want large batches to finish as fast as the server allows, so that I'm not waiting on an artificially small concurrency cap.

### Failed Evaluations

19. As an HR user, I want a candidate whose evaluation failed in any Category to be clearly marked "Lỗi – cần chạy lại", so that I don't mistake a broken result for a weak candidate.
20. As an HR user, I want a Failed Evaluation left out of the ranking, so that the ranking contains only fully scored candidates.
21. As an HR user, I want no Candidate Feedback for a Failed Evaluation, so that I'm never shown feedback built on a score that was never actually assessed.
22. As an HR user, I want to rerun a failed candidate by selecting it and clicking Evaluate again, so that I don't need a separate retry control.
23. As a developer, I want the partial scores of a Failed Evaluation kept in the report file, so that I can see which Category failed and why.

### Feedback failure

24. As an HR user, I want a candidate's evaluation to remain valid even if its Candidate Feedback could not be generated, so that a feedback problem never costs me a score.
25. As an HR user, I want to see "could not generate feedback" when feedback failed, so that I know it's missing and not just loading.
26. As a developer, I want the Review Panel retried once before it is marked failed, so that a one-off bad response doesn't leave a gap.

### Cluster and command line

27. As a developer, I want command-line evaluation to produce Candidate Feedback by default, so that cluster runs give the same output as the web app.
28. As a developer, I want a flag to turn Candidate Feedback off in command-line evaluation, so that I can run quick scoring-only jobs.
29. As a developer, I want a SLURM script that takes a directory of evaluation reports and generates Candidate Feedback where it is missing or failed, so that I can backfill feedback without re-scoring.
30. As a developer, I want that script to skip Failed Evaluations and list them at the end, so that I know which candidates need a full re-evaluation.
31. As a developer, I want that script to skip reports that already have Candidate Feedback, so that rerunning it is cheap and safe.
32. As a developer, I want each evaluation report to contain the Standard and Hidden Requirements text and the path to the extracted resume, so that the feedback script needs only the report directory and can never pair feedback with different requirements than the scores used.
33. As a developer, I want the bias and consistency suites never to run the Review Panel, so that they measure only scoring and don't waste GPU time.

### Model, throughput and backends

34. As a developer, I want SEA-LION v4.5 27B as the default model for every pipeline step, so that I don't have to pass a model on every run.
35. As a developer, I want thinking off for the Review Panel, so that panel turns stay short and the request budget goes further.
36. As a developer, I want one process-wide limit of 70 requests in flight, shared by Category evaluation and the Review Panel, so that the vLLM server stays busy without being oversubscribed.
37. As a developer, I want the SEA-LION model profile set to a concurrency of 70, so that SLURM jobs use the same limit.
38. As a developer, I want overlapping work across candidates (one candidate's Review Panel running while others are still being scored), so that the 70 slots stay full for the whole batch.
39. As a developer, I want any run with the transformers backend refused with a clear error, so that nobody accidentally uses a path that is no longer supported.
40. As a developer, I want a mock mode that returns canned Candidate Feedback, so that I can work on the web app without a GPU.

### Observability

41. As a developer, I want every Review Panel call logged the same way as evaluator calls, so that I can inspect prompts and responses in the per-candidate log folder.
42. As a developer, I want a Coordinator response that doesn't match the schema logged as broken JSON, so that I can debug parsing failures the same way as today.
43. As a developer, I want the Review Panel's run time recorded in the report, so that I can see how much feedback adds to each candidate.

## Implementation Decisions

- **Framework.** The Review Panel is built on Microsoft Agent Framework (Python package `agent-framework`), using its OpenAI-compatible chat client pointed at the existing vLLM server. Every other LLM call (extraction, requirement scrutiny, decomposition, Category evaluation) stays on the existing hand-rolled vLLM client. See ADR 0002.
- **New module: the Review Panel.** A deep module with one entry point. It takes:
  - the evaluation report
  - the extracted resume
  - the Standard and Hidden Requirements text
  - the language

  It returns a Candidate Feedback object, either complete or marked failed. Panelist personas, prompts, the three waves, the retry and the schema check all stay inside it. A mock variant behind the same interface returns canned Vietnamese Candidate Feedback.
- **Three waves, seven calls.**
  1. **Independent views:** three Panelist calls at once.
  2. **Rebuttal Round:** three Panelist calls at once. Each sees its own view and the other two.
  3. **Coordinator:** one call.

  Temperature is 0.0 everywhere. Thinking is off.
- **Panelist inputs.** The resume JSON, the evaluation report and the requirement text. The report is sent without `retrieved_criteria` or timing fields, to fit the 20k-token context. Each Panelist turn is limited to about 400 words of free text.
- **Coordinator inputs.** The evaluation report and the requirement text, plus the three final Panelist views. No resume JSON.
- **Coordinator output** is schema-enforced JSON, through vLLM structured output. Panelist turns are not schema-enforced.
- **Candidate Feedback shape**, stored as a new `candidate_feedback` field in the evaluation report:
  - `status`: one of `ok`, `failed` or `skipped`
  - `summary`: a paragraph
  - `strengths`, `weaknesses`, `interview_checks`: lists of strings
  - `panelist_views`: the final view of each of Leadership, Domain Expertise and People & Culture
  - `processing_time_seconds`
  - on failure, a short `error` string
- **Scores are read-only.** The Review Panel never writes any score, weight, recommendation or Category field. Panelists may disagree with a score in their text.
- **Retry.** If the Review Panel fails (any call errors or times out, or the Coordinator's JSON fails validation), it is retried once from the beginning. If it fails again, `candidate_feedback.status` is `failed` and the evaluation report is still saved.
- **Failed Evaluation.** The evaluator's behaviour on a partial Category failure changes:
  - Any failed Category marks the whole report with a top-level `status: "error"` and the list of failed Categories.
  - The partial scores stay in the file for debugging.
  - The Review Panel is not run, and `candidate_feedback` is absent.
  - A successful report carries `status: "ok"`.
  - The web Candidate Pool shows error reports as "Lỗi – cần chạy lại", excluded from ranking and score display.
- **Report contents.** The evaluator also writes the Standard Requirements text, the Hidden Requirements text and the extracted resume's file path into every evaluation report. The feedback script reads everything it needs from the report.
- **Evaluation flow.** The evaluation entry point gains a "generate feedback" switch.
  - On (default): after a successful, non-error evaluation, run the Review Panel and attach its result before the report is saved.
  - Web batch and command-line evaluation turn it on.
  - The bias and consistency suites turn it off.
  - Command-line evaluation gets a `--no-feedback` flag.
- **Concurrency.**
  - **One process-wide limit** of 70 requests in flight to vLLM, shared by both the existing vLLM client and the Agent Framework client. It is configurable and defaults from the model profile's `CONCURRENCY`.
  - **Web batch:** its candidate-level cap (currently 20) no longer limits throughput. Candidates are scheduled freely, and the request-level limit does the throttling, so one candidate's Review Panel overlaps with other candidates' Category evaluations.
  - **Command-line workers:** behave the same way.
- **Default model.**
  - The default model key becomes `sea-lion-v4.5-27b`, and the Python default model becomes `aisingapore/Qwen-SEA-LION-v4.5-27B-IT`.
  - The `sea-lion-v4.5-27b` profile sets `CONCURRENCY=70` and keeps thinking off.
  - The developer sizes the vLLM server for 70 sequences (e.g. `--max-num-seqs`).
- **Transformers backend refused.** Any evaluation or feedback run with the transformers backend exits with a clear error. The code path stays in the repo but is never used. Removing it is separate work.
- **New SLURM script** (alongside the existing evaluation submit scripts, reusing the same profile loading and vLLM startup helpers). It takes a directory of evaluation reports:
  - skips reports with `status: "error"`
  - skips reports whose `candidate_feedback.status` is `ok`
  - runs the Review Panel on the rest, using the same 70-request limit
  - writes `candidate_feedback` back into each report
  - prints a final list of Failed Evaluations that need re-evaluation
- **Web display.**
  - **Candidate modal:** shows Candidate Feedback (summary, strengths, weaknesses, interview checks), with each Panelist's view in a collapsed section. A `failed` feedback shows "không thể tạo nhận xét" ("could not generate feedback").
  - **Waiting screen:** the `evaluate_candidate` duration estimate now naturally includes feedback time. No new operation kind.
  - **Progress:** a candidate counts as complete when its report, including feedback, is final.
- **Logging.** Every Review Panel call is logged through the existing LLM call logger into the candidate's log folder. Coordinator schema failures go through the existing broken-JSON logger.
- **Language.** Panel prompts and output follow the evaluation's `language` setting (Vietnamese default, English optional).

## Testing Decisions

- There are no automated tests in this repository, and none are added for this feature (no unit, API or browser tests). Testing is manual and done by the developer.
- Implementers verify their work by reasoning through the code: that scores are never written by the Review Panel; that a Failed Evaluation never reaches the Review Panel; that a feedback failure never discards an evaluation; and that the bias and consistency suites run with feedback off.
- Mock mode exists so the developer can check the web flow by hand without a GPU.

## Out of Scope

- Migrating extraction, requirement scrutiny, decomposition or Category evaluation to Agent Framework.
- Removing the transformers backend code (refused at runtime here; removal is separate work).
- Candidate-facing feedback, or sending anything to candidates.
- Letting the Review Panel adjust scores, weights or match recommendations.
- The paper's "score formatter agent": the existing aggregation already produces structured scores.
- A separate "regenerate feedback" button on the web app.
- Thinking or reasoning mode for Panelists (off for now, may be revisited).
- vLLM server sizing and GPU capacity for 70 concurrent sequences (handled by the developer).

## Further Notes

- The foundation paper's evaluator scores different sections (self-evaluation, skills, work experience, basic info, education). This pipeline's Review Panel works on this repo's five Categories instead.
- The paper's CEO, CTO and HR agents became Leadership, Domain Expertise and People & Culture: "CTO" doesn't fit non-technical roles, and "HR" in this project always means the human HR user. See the Panelist entry in `GLOSSARY.md`.
- New glossary terms: Review Panel, Panelist, Rebuttal Round, Coordinator, Candidate Feedback, Failed Evaluation.
- ADR 0002 records why Agent Framework is limited to the Review Panel.
- Before implementing, confirm the current Agent Framework Python API for an OpenAI-compatible client with a custom base URL and for structured output against vLLM, since the framework is still evolving.
