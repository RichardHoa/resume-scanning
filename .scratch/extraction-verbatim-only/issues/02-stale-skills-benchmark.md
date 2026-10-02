# 02: Update the extraction benchmark for the verbatim `skills` field

**Status:** needs-triage

**What's stale:**

The extraction benchmark (`src/cli/benchmark.py`, also run through `src/evaluate.py`) and its metrics (`src/metrics/lexical.py`) still score `skills_and_specialties` against ground truth. That field no longer exists: the extractor now writes a verbatim `skills` list instead (`docs/adr/0003-verbatim-only-extraction.md`).

The whole `benchmark` command raises a `STALE` error on entry, because a benchmark with one column silently missing is easy to trust by mistake.

**To resolve:**

- Drop the `skills_and_specialties` metric, and its entries in the benchmark's per-field tables, from `lexical.py` and `benchmark.py`.
- Optionally add a `skills` metric, once ground truth has `skills` labels. `data/candidate_ground_truth.json` still has `skills_and_specialties` labels.
- Remove the `STALE` guard and the header comments once this is done.
