# 02: Shared waiting screen with time estimates and live batch-evaluation progress

**What to build:** Every operation that makes HR wait shows one shared, click-blocking waiting screen with a progress bar and an estimated time remaining. The operations are:

- the clarification check;
- decomposition;
- Confirm Criteria;
- Workbench save;
- CV extraction;
- batch evaluation.

Single LLM or embedding calls are estimated from how long that operation recently took on this server. Batch evaluation runs as a background job and shows real "completed/total" candidate progress. "Confirm Criteria" no longer appears frozen while saving.

New UI text may be written in English; ticket 03 translates it.

Spec: `.scratch/hr-workbench-vietnamese-ux/spec.md`. See the sections "Shared waiting screen", "Duration tracking (server)", "Batch evaluation as a background job" and "Confirm Criteria waiting screen".

**Blocked by:** 01 (Clarify-once intake, full-width Criteria editor, and editable RAG Workbench). Ticket 01 creates the Workbench save and reshapes the evaluator flows this ticket wraps.

**Status:** ready-for-agent

## Server
- [x] The server records durations of successful `scrutiny`, `decompose`, `save_criteria`, `extract` and per-candidate `evaluate_candidate` operations, keeping recent samples in a persistent JSON file.
- [x] A read endpoint returns the expected duration per operation kind: the median of recent samples, or a config default when there are none.
- [x] A new endpoint starts batch evaluation as a background job, with the existing concurrency limit, and returns a job id.
- [x] A status endpoint reports state (running, done or failed), completed and total counts, elapsed time, and the final results or error. Jobs are held in memory only.
- [x] The existing synchronous batch-evaluation endpoint is unchanged.

## Waiting screen
- [x] One shared front-end waiting-screen module replaces per-controller loader handling on the evaluator, extractor and RAG pages.
- [x] For single calls, it shows a progress bar and countdown based on the server's expected duration. It never goes negative and never shows over 100%, and it switches to a "nearly done" message once elapsed time exceeds the estimate.
- [x] For batches, it shows "completed/total" and a time remaining extrapolated from the actual time per candidate. Before the first candidate finishes, it falls back to the expected per-candidate duration.
- [x] Batch evaluation in the UI uses the background job and polls its status every one to two seconds. The dashboard renders from the final results exactly as before.
- [x] "Confirm Criteria" shows the waiting screen while saving and advances to candidate selection only if the save succeeds. On failure it stays on the Verify step and shows the error.
- [x] "Save to RAG" on the Workbench shows the waiting screen.
- [x] On any failure, the waiting screen closes and the error is shown.

## Verification
- [x] No automated tests are added and no browser is driven. The implementer checks the logic above by reasoning through the code paths. The developer tests by hand.
