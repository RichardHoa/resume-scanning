# 01: Retarget the technical_skills and work_experience bias suites

**Status:** needs-triage

**What's stale:**

The extractor now only copies text from the resume (`docs/adr/0003-verbatim-only-extraction.md`). The generated `skills_and_specialties` field is gone, and each Category is judged on raw resume keys (`CATEGORY_RESUME_KEYS` in `src/pipelines/evaluator_utils.py`). Two bias suites are still built on the old field:

- `src/bias/technical_skills.py` shuffles `skills_and_specialties` items, and its Atomic Interleave splits that list.
- `src/bias/work_experience.py` reorders the `work_experience` / `skills_and_specialties` sections and shuffles the skill items.

Both suites raise a `STALE` error from `extract_candidate_data`, so they can't produce results that mean nothing. They must be fixed before they run again.

**Proposed direction (from the grilling session):**

- technical_skills: permute `work_experience` entries; Atomic Interleave splits `work_experience`.
- work_experience: reorder the `work_experience` / `projects` sections, and permute `projects` entries.

Each suite should permute exactly the raw keys its Category now receives. Remove the `STALE` guard and header comment once this is done.
