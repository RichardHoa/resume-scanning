Status: ready-for-agent

# Web batch processing: Trích xuất hàng loạt and obvious batch evaluation

Requirement collection only. Nothing here is implemented yet. Every question raised while grilling is settled.

## Problem Statement

HR receives resumes as a folder of PDFs, but the website's extraction page takes one PDF at a time. Extracting 50 resumes means uploading 50 times and waiting through each one. Firing several uploads at once doesn't help either: the extraction endpoint blocks the server while it works, so uploads run one after another and the rest of the website stops responding meanwhile.

Evaluation already processes the selected candidates in parallel on the server, but nothing on the page says so. HR sees a checkbox list and a waiting screen with "completed/total", and has no way to tell that a batch is the intended way to use it.

The waiting screen's count and time estimate assume items run one at a time. The estimate before the first candidate finishes is the single-candidate duration × candidates left (about 45 minutes for 30 candidates that really take a few), and after that it multiplies the time to the latest completion by the number left. Every candidate starts at once and shares the server's request slots, so they all finish near the end. The count stays at 0 for most of the batch and then jumps, and a failed candidate counts as "completed", so "30/30" can hide errors.

## Solution

On the extraction page, HR drops in a folder (or picks one, or picks several PDFs) and gets **Trích xuất hàng loạt**: one Batch that the server extracts in parallel, limited only by the server's existing request limit. Before it starts, HR sees what will happen: how many PDFs, how many files were skipped (not PDF, too large), which names clash inside the Batch (these block the start), and how many already exist and will be re-extracted. While it runs, the waiting screen shows each file's live state, counts by state (done · running · failed · waiting) and a time estimate based on throughput, and HR can stop the Batch. Afterwards HR gets a results table with one row per file, can retry the failed or cancelled files without uploading them again, and can go straight to evaluation with exactly this Batch selected.

On the evaluator, Step 3 says plainly that the selection is evaluated as one parallel Batch and offers a one-click "select the Batch just extracted". The evaluation waiting screen gets the same per-candidate states, counts, estimate and stop button. The server evaluates a few candidates at a time, so they finish one after another at a steady pace and the progress means something.

Only one Batch runs on the server at a time. A page that is reloaded reconnects to the Batch still running.

## User Stories

### Uploading a Batch

1. As an HR user, I want to drop a whole folder of resume PDFs onto the extraction page, so that I don't upload them one by one.
2. As an HR user, I want a folder picker as well as drag-and-drop, so that I can choose a folder without dragging.
3. As an HR user, I want to still be able to pick several loose PDFs, so that I can extract a hand-picked set that isn't in one folder.
4. As an HR user, I want PDFs in subfolders of the folder I drop to be included, so that resumes sorted into subfolders aren't missed.
5. As an HR user, I want non-PDF files in the folder skipped, so that stray files (cover letters as .docx, images, .DS_Store) don't break the Batch.
6. As an HR user, I want to be told how many files were skipped and why before the Batch starts, so that I know nothing I expected was silently dropped.
7. As an HR user, I want a PDF over the size limit skipped and named before the Batch starts, so that one huge file doesn't stall the upload.
8. As an HR user, I want no limit on how many PDFs one Batch holds, so that I can extract a full recruitment round at once.
9. As an HR user, I want the start blocked when two files in my Batch have the same filename, with the clashing names listed, so that one resume never silently overwrites another.
10. As an HR user, I want to be told before starting how many resumes in my Batch are already extracted and will be re-extracted, losing their old evaluations, so that I don't wipe evaluations by accident.
11. As an HR user, I want to see the number of PDFs about to be extracted before I confirm, so that I can catch a wrong folder before any work starts.
12. As an HR user, I want uploading a single PDF to work exactly as it does today, opening the split view directly, so that the simple case stays simple.
13. As an HR user, I want the feature named "Trích xuất hàng loạt" on the page, so that I recognise it as batch extraction.

### Watching a Batch run

14. As an HR user, I want each file's live state on the waiting screen (waiting, running, done, failed), so that I can see what is happening to my resumes.
15. As an HR user, I want separate counts for done, running, failed and waiting, so that failures are never hidden inside "N/N".
16. As an HR user, I want a time-remaining estimate that reflects files running in parallel, so that I can plan around a realistic finish time.
17. As an HR user, I want a sensible estimate even before the first file finishes, based on how long past Batches took per file, so that I'm not shown a figure many times too long at the start.
18. As an HR user, I want the estimate to switch to the speed actually measured once files start finishing, so that it gets more accurate as the Batch goes on.
19. As an HR user, I want to stop a Batch with "Dừng lô", so that a wrong folder doesn't occupy the server for half an hour.
20. As an HR user, I want files already running when I stop to finish and be kept, so that work already paid for isn't thrown away.
21. As an HR user, I want files not yet started when I stop to be marked cancelled, so that I can see which ones still need doing.
22. As an HR user, I want to reload or reopen the page and land back on my running Batch's progress, so that an accidental reload doesn't lose track of it.
23. As an HR user, I want a second Batch refused while one is running, with "Đang có một lô khác chạy" and a link to the running one, so that two Batches don't slow each other down or confuse the estimates.

### Batch extraction results

24. As an HR user, I want a table with one row per file after the Batch finishes, so that I can review the whole Batch at a glance.
25. As an HR user, I want each row to show the file's outcome (extracted, Scanned Resume, Repaired Extraction, extracted with Fidelity Warnings, failed, cancelled), so that I know which resumes need attention.
26. As an HR user, I want each row to show the Missing Position flag, so that I see right after upload which resumes state no position.
27. As an HR user, I want each row to show how long that file took, so that I can spot unusually slow resumes.
28. As an HR user, I want a failed row to show why it failed, so that I can decide whether a retry will help.
29. As an HR user, I want to click a row and open the existing split view (JSON and visual profile) for that resume, so that I can inspect any extraction in detail.
30. As an HR user, I want to get back from the split view to the Batch table, so that I can go through the resumes one after another.
31. As an HR user, I want one failed resume never to stop the rest of the Batch, so that a bad PDF doesn't cost me the other 49.
32. As an HR user, I want a "Thử lại các CV lỗi" button that reruns only the failed and cancelled files, so that I don't redo the ones that worked.
33. As an HR user, I want the retry to need no re-upload, so that I don't have to find those files again.
34. As an HR user, I want an "Đánh giá các CV này" button on the results table that opens the evaluator with exactly this Batch selected, so that I go from extraction to evaluation in one click.
35. As an HR user, I want a Scanned Resume in the Batch still to show up, marked as scanned, so that I know to ask that candidate for a PDF with selectable text.

### Batch evaluation

36. As an HR user, I want Step 3 to show a fixed summary like "Đã chọn 37 CV — sẽ đánh giá song song", so that it's obvious all selected candidates are evaluated together as one Batch.
37. As an HR user, I want a "Chọn lô vừa trích xuất" shortcut in Step 3, so that I can select the Batch I just extracted without ticking boxes.
38. As an HR user, I want that shortcut to still work after I reload the page, so that a reload between extraction and evaluation doesn't lose my Batch.
39. As an HR user, I want the evaluation waiting screen to list every candidate with their live state, so that I can see progress per candidate.
40. As an HR user, I want candidates to finish one after another throughout the Batch rather than all at the very end, so that the progress count and estimate mean something.
41. As an HR user, I want a failed candidate counted as failed, not as completed, so that I know before Step 4 opens that some need a rerun.
42. As an HR user, I want to stop an evaluation Batch too, with running candidates finishing and waiting ones cancelled, so that a wrong selection can be stopped.
43. As an HR user, I want Step 4 to open only when the whole Batch is done, so that rankings and KPIs don't re-sort while I'm reading them.
44. As an HR user, I want to reconnect to a running evaluation Batch after a reload, so that a long evaluation isn't lost from view.

### Operators and developers

45. As a developer, I want Batch concurrency to come only from the server's existing request limit set by the model profile (40 for the default model), so that there is one setting to tune, never shown to HR.
46. As a developer, I want the Python fallback for that limit to match the default model's 40, so that a server started without the script behaves the same.
47. As a developer, I want the extraction endpoint to no longer block the server while it works, so that progress polls and other pages stay responsive during a Batch.
48. As a developer, I want every finished Batch to record its seconds per item, so that the next Batch's first estimate is grounded in real runs.
49. As a developer, I want a server restart to drop running Batches and their temporary PDFs, as evaluation jobs are dropped today, so that there's no persistence layer to keep consistent.
50. As a developer, I want the existing synchronous batch-evaluation endpoint kept for non-UI callers, so that scripts that use it don't break.

## Implementation Decisions

### Batch job model (shared by extraction and evaluation)

- **One in-memory Batch job store** replaces today's evaluation-only job dictionary and serves both kinds (`extract`, `evaluate`). A job holds its kind, state (`running`, `done`, `cancelled`, `failed`), start/finish times, a cancel flag and an **ordered list of items**. Each item has a name, a state (`waiting`, `running`, `done`, `failed`, `cancelled`), its seconds taken and, when it ends, its outcome or error.
- **Only one Batch runs at a time.** Starting a job while another is `running` is refused with a conflict response that carries the running job's id and kind. The page shows "Đang có một lô khác chạy" with a link that reconnects to it. A retry is a new Batch and follows the same rule.
- **Job status endpoint** returns the job's state, elapsed seconds, per-state counts (`done`, `running`, `failed`, `waiting`, `cancelled`), the item list with each item's state, and, once finished, the results. Failed items count as `failed`, never as done.
- **Cancel endpoint** sets the cancel flag. Items not yet started are marked `cancelled` and never start. Running items finish and keep their results. The job then ends as `cancelled`, with results for everything that finished.
- **Lifetime**: finished jobs, and the uploaded PDFs they still hold, are dropped after the existing job TTL (`EVAL_JOB_TTL_SECONDS`). Nothing is persisted: a server restart loses running jobs and their PDFs.
- **Reload**: the page stores the running job's id in the browser. On load it asks the server for that job and, if it is still running or recently finished, shows its waiting screen or results. The browser storage is per viewer and wrapped against failure. A missing or expired job is ignored silently.

### Concurrency

- **The only concurrency limit** is the existing process-wide vLLM request limit (`CONCURRENCY`, set by the model profile, 40 for `sea-lion-v4.5-27b`). The Python fallback when the variable is unset changes from 50 to 40. No new setting, and nothing shown to HR.
- **Extraction**: up to `CONCURRENCY` files in flight, since one extraction is one request (plus retries).
- **Evaluation**: candidates in flight are capped at `ceil(CONCURRENCY / (5 × num_evaluations)) + 1`, which is 4 at the defaults. Each candidate already sends its 5 Categories × `num_evaluations` runs at once, so without the cap every candidate shares the slots with every other one and they all finish near the end. The +1 keeps the slots busy while one candidate is in its Review Panel, which sends fewer requests. The code that sets the cap should say why in a comment.
- **The extraction endpoint stops blocking the event loop**: extraction runs in worker threads, never directly inside an async handler.

### Batch extraction

- **Start endpoint**: one multipart upload with every PDF. The server saves them to a per-job temp folder, checks them, and either refuses (duplicate names inside the Batch) or starts the job and returns its id.
- **Pre-flight check** (shown before the upload, done in the browser from the file list, and checked again on the server): duplicate filenames inside the Batch block the start and are listed. Non-PDF files and files over the 20 MB per-file limit are skipped and reported with the reason. Names that already have an extraction are counted and reported as "will be re-extracted, their old evaluations deleted". HR confirms before the upload. There is no limit on the number of files.
- **Folder input**: the picker accepts a directory as well as multiple files. Dropping a folder walks it recursively. Only the base filename is used as the resume's name (resumes are keyed by base filename, ADR 0010), which is why duplicates across subfolders must block.
- **Each item** runs exactly today's single-file path: clear what is stored for the resume, extract, store the JSON and PDF, record the single-extraction duration on success. Its outcome is one of: extracted, Scanned Resume (kept, as today), Repaired Extraction, extracted with Fidelity Warnings, failed (with the error). A failed item never stops the Batch. The item result carries what the results table needs: outcome, Missing Position flag, seconds taken, error.
- **Retry**: a "retry" start takes the finished job's id and reruns only its failed and cancelled items from the PDFs still in that job's temp folder: no re-upload. It is a new Batch. If the old job has expired, the page says the files must be uploaded again.
- **A Batch of one** shows today's split view directly when it finishes. The table is only for two or more files. Once all uploads go through the Batch path, the single-file endpoint can be removed if nothing else uses it.

### Batch evaluation

- The existing evaluation job keeps its request shape and behaviour (Evaluation Order, clearing each candidate's old evaluation, Candidate Feedback, Failed Evaluation and Must-have Rejection rules). It moves onto the shared job store and gains per-candidate item states, cancel and the candidate cap. The synchronous endpoint for non-UI callers stays.
- **Step 4 opens only when the job ends**, as today. Nothing renders partially. A cancelled evaluation Batch opens Step 4 with the candidates that finished.

### Time estimate

- **New duration kinds** record, for every finished Batch, its seconds per item (Batch wall time ÷ items finished): one kind for extraction Batches, one for evaluation Batches. They sit beside the existing single-item kinds (`extract`, `evaluate_candidate`) in the same rolling-median store, with config defaults for the first run.
- **Before the first item finishes**: remaining = `max(single-item expected duration, seconds-per-item expected × N) − elapsed`.
- **After k items finish**: remaining = `(items left) ÷ (k / elapsed)`. That is measured throughput, not the time of one item × items left. "Sắp xong…" and the 95% bar cap stay. The bar's fraction counts finished items, whether done or failed.
- The waiting screen shows the per-state counts and the item list for both kinds of Batch. Single-call waits (scrutiny, decompose, save criteria) are unchanged.

### Pages

- **Extraction page**: the dropzone and picker accept a folder or several PDFs. A pre-flight panel shows counts, skipped files, clashes and re-extractions, and asks for confirmation. Batch waiting screen with "Dừng lô". A results table (name, outcome badge, Missing Position, seconds, error), where a row opens the existing split view, the split view has a way back to the table, and the table has "Thử lại các CV lỗi" and "Đánh giá các CV này". The page title and labels say "Trích xuất hàng loạt".
- **"The Batch just extracted"**: when an extraction Batch finishes, the page keeps its list of resume names in browser storage (per viewer, wrapped against failure). "Đánh giá các CV này" and Step 3's "Chọn lô vừa trích xuất" both select exactly the names in that list that are present in Step 3.
- **Evaluator Step 3**: a fixed summary bar "Đã chọn N CV — sẽ đánh giá song song" and the "Chọn lô vừa trích xuất" shortcut, next to the existing search and select-all.
- All new HR-facing text is Vietnamese, matching the rest of the website.

### Domain language

- **Batch** is added to the glossary: a set of resumes that one extraction or evaluation job processes together, in parallel. A failed resume never stops the rest. Only one runs at a time. Avoid "bulk", "job" alone, "run" (taken by Category runs and run folders).

## Testing Decisions

- This project adds no automated tests and is not checked in a browser. Changes are verified by reasoning through the code paths (see the project's working agreement). No new test seams are introduced.
- Highest-value paths to reason through on review: the one-Batch-at-a-time refusal and reconnect; cancel with items in each state; a failed item not stopping the Batch; retry from the kept PDFs after a job has expired; duplicate names across subfolders; the evaluation candidate cap at the default `num_evaluations` and at 1; the estimate before and after the first completion; the extraction endpoint no longer blocking the event loop.
- The existing evaluation job (background task, progress callback, polling) is the reference pattern for the extraction job.

## Out of Scope

- The CLI and SLURM batch scripts (`--workers`, the pipeline run folders): unchanged.
- Model profiles other than the default `sea-lion-v4.5-27b`, and per-model concurrency tuning.
- Combined Extraction on the website.
- Persisting jobs across server restarts.
- Running more than one Batch at once, or a queue of Batches.
- Showing evaluation results partially in Step 4 before the Batch ends.
- Changing the Step 4 KPIs, ranking, scoring or the Review Panel.
- A Batch spanning both resume sets, or uploading into a pipeline (read-only) run folder.
- The bias runner, extractor consistency check and DSPy.

## Further Notes

- Resume identity stays the base filename (ADR 0010). That is why same-named files in different subfolders block the Batch instead of being renamed automatically.
- Old reports and RAGs are not migrated. The data is wiped on change, as usual.
- No ADR was written: the candidate cap and the one-Batch rule are easy to reverse. The cap's reasoning belongs in a code comment beside it.

## Comments

- 2026-10-25: Implemented in the working tree, uncommitted (no tickets were cut; built straight from this spec). New: `src/core/batch_jobs.py` (job store, cap, cancel, per-item duration), `src/api/batch.py` (shared status/cancel), `src/static/js/modules/batch-job.js` (reconnect storage, polling). The single-file `/api/extract` and `/api/evaluate_batch/jobs/{id}` are gone; `/api/extract/jobs`, `/api/extract/jobs/{id}/retry`, `/api/extractions/{name}`, `/api/batch_jobs/{id}` and `/api/batch_jobs/{id}/cancel` replace them. Deviation: a Batch of one records no seconds-per-item sample (its time is one item's latency, which would inflate later estimates). Note: Starlette's form parser caps one upload at 1000 files by default.
