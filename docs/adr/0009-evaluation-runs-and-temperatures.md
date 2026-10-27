# Three evaluation runs per Category, where only run 1 is greedy; scrutiny samples on purpose

Each LLM call's temperature is chosen for what that call is for. Do not "fix" any of them to match the others.

| Call | Temperature | Why |
| --- | --- | --- |
| Decomposition | 0.0 | One reviewable result per requirement text |
| Category evaluation, run 1 | 0.0 | A single run (`num_evaluations=1`) stays deterministic |
| Category evaluation, runs 2+ | `CATEGORY_EVAL_SAMPLE_TEMPERATURE` (0.5) | So runs can disagree |
| Any retry after a failed attempt | `CATEGORY_EVAL_RETRY_TEMPERATURE` (0.5) | An identical prompt at 0.0 fails the same way again |
| Requirement scrutiny | `SCRUTINY_TEMPERATURE` (0.7) | Varied Clarification Questions |
| Review Panel | `REVIEW_PANEL_TEMPERATURE` (0.0) | Reproducible feedback |

**Evaluation runs.** Each Category is judged in `DEFAULT_NUM_EVALUATIONS` (3) runs, which the CLI, the API and the website all use. The Category score is the median of the run scores, and a Must-have rejects only when most runs gave it No Evidence (ADR 0008). Both only help if the runs can disagree. At temperature 0 with the same prompt they almost never do, so three runs would cost three times as much and repeat run 1. That is why the later runs sample.

**Requirement scrutiny.** This step surfaces Implicit Assumptions as Clarification Questions and Combined Requirements (ADR 0010) before decomposition. It is advisory and web-only: the batch jobs never run it, and it never affects a score. A higher temperature surfaces a more varied set of ambiguities when HR re-checks edited text, which is more useful than the same fixed questions every time.

## Considered Options

- **Temperature 0 for every evaluation run, with a higher count.** Rejected: it costs about three times as much for near-identical runs, so the median and the majority vote change nothing.
- **Sampling every run, run 1 included.** Rejected: a single run would stop being deterministic, for no gain.

## Consequences

- The bias runner has its own call path at temperature 0, so the bias suite is unaffected.
- The evaluator consistency check goes through the production code, so its runs 2+ sample: it measures the spread of sampled judgements, not only vLLM's run-to-run noise.
- Each resume makes up to three times as many Category calls, all under the one shared limit on in-flight requests, so a large batch takes about three times as long.
- If any one run runs out of retries, its Category fails, so three runs give a Failed Evaluation slightly more chances to happen.
