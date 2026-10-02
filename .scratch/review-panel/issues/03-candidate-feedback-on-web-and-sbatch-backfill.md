# 03: Candidate Feedback on the web and sbatch backfill

**What to build:**

- **Web, one button.** Evaluate runs evaluation and then the Review Panel for each candidate. Candidates overlap: one candidate's panel runs while others are still being scored, all under the shared 70-request limit.
  - The progress counter ("7/20 ứng viên") counts a candidate only when its report, including Candidate Feedback, is final.
  - The waiting-screen estimate keeps using the `evaluate_candidate` duration, which now includes feedback time.
- **Candidate modal.** Shows the Candidate Feedback (summary, strengths, weaknesses, interview checks), with each Panelist's final view in a collapsed section. Failed feedback shows "không thể tạo nhận xét". Failed Evaluations keep the "Lỗi – cần chạy lại" state from ticket 01.
- **sbatch backfill.** A new SLURM script, alongside the existing evaluation submit scripts and reusing their profile-loading and vLLM-startup helpers. It takes a directory of evaluation reports and:
  - skips reports with `status: "error"`
  - skips reports whose `candidate_feedback.status` is `ok`
  - runs the Review Panel on the rest, under the 70-request limit
  - writes `candidate_feedback` back into each report
  - prints a final list of Failed Evaluations that need re-evaluation

  It needs nothing but the report directory: the requirement text and the resume path come from the report itself.

**Blocked by:** 02

**Status:** ready-for-agent

- [ ] Clicking Evaluate on the web produces reports with Candidate Feedback, with no extra button
- [ ] The batch progress counter only advances once a candidate's feedback is ok, failed or not needed (Failed Evaluation)
- [ ] The candidate modal shows the summary, strengths, weaknesses and interview checks, with Panelist views collapsed
- [ ] Failed feedback shows "không thể tạo nhận xét"; the scores still show normally
- [ ] Web mock mode shows canned Candidate Feedback without a GPU
- [ ] The backfill script fills in missing or failed feedback and leaves ok feedback untouched
- [ ] Rerunning the backfill script on a finished directory makes no LLM calls
- [ ] The backfill script lists Failed Evaluations at the end and doesn't touch them
- [ ] Testing is manual and done by the developer; no automated tests are added

## Comments

Implemented (uncommitted). The acceptance boxes are left for the developer's manual run.

- **Web:** the batch now calls `evaluate_resume(generate_feedback=True)`. The progress counter (`_mark_candidate_done`) and the `evaluate_candidate` duration already wrap that whole call, so both now include the Review Panel without further changes. Web mock mode gets canned feedback through `MockReviewPanel`.
- **Candidate modal** (`src/static/js/modules/candidates.js`): a "Nhận xét của hội đồng đánh giá" card between the score banner and the Category cards. It shows the summary, strengths, weaknesses and interview checks, with each Panelist's final view in a closed `<details>`. `failed` feedback shows "Không thể tạo nhận xét", and the Category cards still render. Skipped or absent feedback (scoring-only runs, older reports) and Failed Evaluations show no card.
- **Backfill:** `sbatch scripts/submit_feedback_vllm.sh [REPORT_DIR] [MODEL]` (REPORT_DIR defaults to `evaluation_json`). It runs `src/cli/backfill_feedback.py --dir ...`, which:
  - skips `status: "error"` reports and those whose feedback is `ok`
  - reviews the rest in parallel, throttled by the shared request limit (the profile's `CONCURRENCY`)
  - rewrites only `candidate_feedback`, through a temp file
  - prints the Failed Evaluations at the end

  Reports it can't review from the file alone are listed separately as unusable: no `status` field, no requirement text, or a missing `resume_path`. A finished directory creates no panel and makes no LLM calls, although the SLURM job still starts vLLM.
- **Language:** evaluation reports now store `language`, and the backfill uses it. Older reports fall back to `--language` (default `vietnamese`). The panel doesn't see this field.
