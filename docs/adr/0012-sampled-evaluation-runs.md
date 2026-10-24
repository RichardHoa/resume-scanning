# Three evaluation runs per Category, and runs after the first sample

Each Category is now judged in three runs by default (`DEFAULT_NUM_EVALUATIONS` in `src/core/config.py`, used by the CLI, the API and so the website). The Category score is the median of the run scores, and since ADR 0011 a Must-have rejects only when most runs gave it No Evidence. Both only help if the runs can disagree, and at `temperature=0.0` with the same prompt they almost never do: three runs cost three times as much and repeat run 1.

So run 1 stays greedy (`temperature=0.0`) and every later run samples at `CATEGORY_EVAL_SAMPLE_TEMPERATURE` (0.5, the same as the retry temperature, which already gives schema-valid output). A run that needs a retry samples at `CATEGORY_EVAL_RETRY_TEMPERATURE` as before. This narrows ADR 0001 and ADR 0002, which say Category evaluation runs at `temperature=0.0`: that now holds for run 1 only.

## Considered Options

- Keep `temperature=0.0` for every run and just raise the count. Rejected: about three times the cost for near-identical runs, so the median and the majority vote change nothing.
- Sample every run, run 1 included. Rejected: a single run (`num_evaluations=1`) would stop being deterministic too, for no gain.

## Consequences

- A single run is unchanged and still deterministic. The bias runner has its own call path at `temperature=0.0`, so the bias suite is unaffected.
- `scripts/run_consistency.py` goes through the same code with 20 runs, so its runs 2–20 now sample: it measures the spread of sampled judgements, not only vLLM's run-to-run noise at temperature 0. Results from before this change are not directly comparable. (That evaluator consistency check has since been replaced by an extractor-only one.)
- Each resume makes up to three times as many Category calls, all under the one shared limit on in-flight requests, so a large batch takes about three times as long.
- Any one run that runs out of retries fails its Category, so three runs give a Failed Evaluation slightly more chances to happen.
