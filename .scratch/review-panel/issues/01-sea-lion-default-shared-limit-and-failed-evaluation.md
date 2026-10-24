# 01: SEA-LION default, shared 70-request limit, and Failed Evaluation

**What to build:**

- **New default model.** Every pipeline step defaults to `aisingapore/Qwen-SEA-LION-v4.5-27B-IT`: both the default model key in the model profiles and the Python default model. The `sea-lion-v4.5-27b` profile sets `CONCURRENCY=70`, with thinking off.
- **One shared request limit.** One limit for the whole process caps requests in flight to vLLM at 70. It defaults from the profile's `CONCURRENCY`, and it is shared by every vLLM caller, including the Review Panel's client added in ticket 02.
  - The web batch's hard-coded cap of 20 candidates no longer limits throughput. Candidates are scheduled freely, and the request-level limit does the throttling.
  - Command-line workers behave the same way.
- **Transformers refused.** Any evaluation run with the transformers backend exits with a clear error. The code path stays in the repo; removing it is separate work.
- **Failed Evaluation.** If any Category fails, the evaluation report gets a top-level `status: "error"` and a list of the failed Categories. The partial scores stay in the file. A fully scored report gets `status: "ok"`.
- **Self-contained reports.** Every evaluation report also stores the Standard Requirements text, the Hidden Requirements text, and the path to the extracted resume.
- **Candidate Pool.** Error reports show "Lỗi – cần chạy lại" and are left out of ranking and score display. HR reruns a failed candidate by selecting it and clicking Evaluate again.

See `.scratch/review-panel/spec.md` and the Failed Evaluation entry in `GLOSSARY.md`.

**Blocked by:** None (can start immediately)

**Status:** done

- [x] Running with no model argument uses SEA-LION v4.5 27B, from both the SLURM scripts and the Python CLIs and server
- [x] The `sea-lion-v4.5-27b` profile sets `CONCURRENCY=70`
- [x] No more than 70 requests are ever in flight to vLLM from one process, across all callers
- [x] The web batch no longer has its own 20-candidate cap
- [x] Evaluation with `--backend transformers` exits with a clear error message
- [x] A report with any failed Category has `status: "error"`, lists the failed Categories, and keeps its partial scores
- [x] A fully scored report has `status: "ok"`
- [x] Every report contains the Standard Requirements text, the Hidden Requirements text, and the extracted resume's path
- [x] The Candidate Pool shows error reports as "Lỗi – cần chạy lại", unranked and without a score
- [x] Re-evaluating a failed candidate from the web replaces its error report
- [x] The bias and consistency suites still run unchanged
- [x] Testing is manual and done by the developer; no automated tests are added

## Comments

Implemented in commit 007e317 ("ticket 01"). Verified by reading the code against each acceptance criterion:

- Default model: `DEFAULT_MODEL_KEY="sea-lion-v4.5-27b"` in `scripts/model_profiles.sh` (all submit scripts and `server.sh` resolve through it), and `DEFAULT_LLM_MODEL` in `src/core/config.py`. The profile sets `CONCURRENCY=70`.
- Shared limit: `request_slots` in `src/providers/vllm_client.py` is held around every vLLM HTTP request and sized from `VLLM_MAX_CONCURRENT_REQUESTS` (env `CONCURRENCY`, default 70). Agent Framework's client does not go through it; ticket 02's **Request limit** section covers how the panel is capped.
- The web batch's `Semaphore(20)` is gone. Candidates run on a dedicated executor, and command-line `--workers` defaults to the request limit.
- Transformers refused in `ResumeEvaluator.__init__`, `src/cli/evaluate.py`, `src/server.py` and `scripts/submit_eval_transformer.sh`.
- Reports carry `status`, `failed_categories`, `standard_requirements`, `hidden_requirements` and `resume_path`. Re-evaluation overwrites the same `<name>_evaluation.json`.
- Candidate Pool and evaluator results show "Lỗi – cần chạy lại", with no score, and exclude failed candidates from stats and ranking.
- Bias and consistency suites only call `evaluate_resume`, so the new aggregate return value does not affect them.
