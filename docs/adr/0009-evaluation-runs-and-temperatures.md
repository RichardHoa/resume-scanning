# Five greedy evaluation runs per Category, voted per Criterion; scrutiny samples on purpose

Each LLM call's temperature is chosen for what that call is for. Do not "fix" any of them to match the others.

| Call | Temperature | Why |
| --- | --- | --- |
| Decomposition | 0.0 | One reviewable result per requirement text |
| Category evaluation, every run | 0.0 | The same input should give the same Verdict; a run that disagrees shows one it does not |
| Any retry after a failed attempt | `CATEGORY_EVAL_RETRY_TEMPERATURE` (0.5) | An identical prompt at 0.0 fails the same way again |
| Requirement scrutiny | `SCRUTINY_TEMPERATURE` (0.7) | Varied Clarification Questions |
| Review Panel | `REVIEW_PANEL_TEMPERATURE` (0.0) | Reproducible feedback |

**Evaluation runs.** Each Category is judged in `DEFAULT_NUM_EVALUATIONS` (5) runs, which the CLI, the API and the website all use. Each Criterion's Verdict is voted across the runs: the Verdict more than half of them gave, or Partial Evidence when none has a majority. That voted Verdict is what HR is shown, with how many runs gave it. But the Category score and Criterion Points are computed from each Criterion's Criterion Score, the mean Verdict score of its runs (Strong 1, Partial ½, No Evidence 0), not from the voted Verdict. A Must-have rejects only when most runs gave it No Evidence (ADR 0008).

**Why every run is greedy.** What matters is whether the same input gives the same judgement. Runs 2+ used to sample at 0.5, so they could disagree. But then a changed Verdict could just be sampling noise, and the consistency check could not tell that apart from real instability. Greedy runs take sampling out. A Verdict that still differs between runs at temperature 0 sits on a near-tie the model cannot settle: vLLM's batch-dependent numerics are enough to tip it. Five runs are kept to show where that happens, and the vote and the mean still cover it. The 2026-11-02 Tech consistency run (`research/evaluator-consistency-tech.md`) measured 8.9% of Verdicts changing with runs 2+ at 0.5. That was the baseline when this switch was made.

Voting per Criterion replaced showing the median-scoring run's Verdicts. With about 18 Criteria per HR RAG, each shown Verdict was one sampled run's opinion, and most Verdict flips between re-evaluations were a single run disagreeing. Five runs instead of three let a vote outvote that run. Scoring the mean instead of the voted Verdict came from the next consistency run (53 Tech resumes × 5 Repeat Evaluations, `docs/research/evaluator-consistency-2026-10-31.md`). A Criterion on borderline evidence split 3 to 2 one evaluation and 2 to 3 the next, so the vote moved its full points, and one Verdict in a 2-Criterion Category moved the Overall Score by about 12.5. The mean moves it by a fifth of that per run.

**Requirement scrutiny.** This step surfaces Implicit Assumptions as Clarification Questions and Combined Requirements (ADR 0010) before decomposition. It is advisory and web-only: the batch jobs never run it, and it never affects a score. A higher temperature surfaces a more varied set of ambiguities when HR re-checks edited text, which is more useful than the same fixed questions every time.

## Considered Options

- **Sampling runs 2+ at 0.5.** This was the design until 2026-11-02. Replaced: a changed Verdict could not be told apart from sampling noise.
- **One greedy run (`num_evaluations=1`).** Rejected for now: five greedy runs cost five times as much, but they show which Verdicts are near-ties even at temperature 0.
- **Scoring the voted Verdict.** This was the first design. Rejected: a split vote moved a Criterion's full points between Repeat Evaluations (Overall Score spread mean 3.6, largest 18.8).
- **Sampling every run, run 1 included.** Rejected: a single run would stop being deterministic, for no gain.

## Consequences

- The bias runner has its own call path at temperature 0, so the bias suite is unaffected.
- The evaluator consistency check goes through the production code, so it measures only what changes between greedy runs of the same input: vLLM's run-to-run noise, and the near-tie Verdicts it tips.
- Retries after a failed attempt still sample at 0.5, so a resume that needed a retry can give a different Verdict on a re-evaluation.
- Most runs will agree, so the vote and the mean will usually just repeat run 1. That is expected, not a reason to sample again.
- Each resume makes up to five times as many Category calls, all under the one shared limit on in-flight requests, so a large batch takes about five times as long as a single run.
- If any one run runs out of retries, its Category fails, so five runs give a Failed Evaluation more chances to happen.
- A Criterion's earned Criterion Points can fall between the three Verdict levels (e.g. 0.8 of its points for 3 Strong and 2 Partial), and may not match the shown Verdict's own share.
- A Verdict voted Partial Evidence for lack of a majority may have no run that gave Partial; its reasoning then states how the runs split, with the quotes of a run that found evidence.
- The Category's strengths, gaps and summary come from the run that agrees with the most voted Verdicts, so they can still mention a Verdict the vote overturned.
