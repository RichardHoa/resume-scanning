Status: ready-for-agent

# HR Workbench: Vietnamese UI, Clarify-Once Intake, Waiting Screens, and Editable RAG Workbench

## Problem Statement

HR users of the resume-scanning web app are Vietnamese speakers, but almost all of the interface text is in English, and the mixed English/Vietnamese labels are hard to read.

In requirement intake on the HR Evaluator page, the Clarification Question flow is confusing:
- Once the questions appear, two buttons can trigger decomposition.
- Editing the text after reading the questions triggers another clarification check, so HR can get stuck in a loop of questions instead of moving on.
- The "Use Active RAG & Skip" button stays visible after HR has typed a new set of requirements, which invites them to throw their new text away by accident.
- The Clarification Questions appear in a block below both textareas, so HR has to scroll back and forth between a question and the text it refers to.

Waiting is opaque:
- Every long operation shows only a spinning icon, with no idea of how long it will take. This includes the clarification check, decomposition, saving criteria, CV extraction and batch evaluation.
- Clicking "Confirm Criteria & Proceed" shows no feedback at all while the criteria are re-embedded, so the page looks frozen.

On the "Verify & Adjust RAG Categorization" step, Category cards sit several to a row and each Criterion is a single-line input. Long Criteria are cut off and HR has to scroll sideways inside the input to read them.

The RAG Vector Database Workbench is read-only. To fix a single Criterion, HR has to go back through the whole evaluator flow.

## Solution

- **Vietnamese interface.** Every page of the web app shows its fixed text in Vietnamese: labels, buttons, alerts, loader messages and placeholders. Technical product names ("RAG", "ChromaDB", `hr_rag.txt`) stay as they are. LLM output (Clarification Questions and the like) is requested in Vietnamese.
- **Clarify-once intake.** Clarification Questions are asked once per pass through requirement intake:
  - After they appear, the only way forward is a single "Phân rã yêu cầu" (Decompose) button. It decomposes whatever text is currently in the textareas, without another check.
  - The check runs again only if HR comes back from Category review and changes the requirement text.
- **"Use Active RAG" hides while HR types.** The button disappears as soon as either requirement textarea has text, and reappears when both are empty.
- **Side-by-side questions.** When Clarification Questions exist, each requirement textarea sits next to its own questions: Standard next to Standard, Hidden next to Hidden. Before any questions exist, the layout stays single-column.
- **One shared waiting screen.** Every operation that makes HR wait uses the same full-screen waiting screen, with a progress bar and an estimated time remaining:
  - For single LLM or embedding calls, the estimate comes from how long that operation took recently.
  - Batch evaluation shows real per-candidate progress ("7/20 ứng viên") and extrapolates the time remaining from it.
  - "Confirm Criteria" shows this waiting screen while saving.
- **Readable Category review.** Each Category card spans the full width, one per row. Each Criterion is an auto-growing, wrapping text area.
- **Editable RAG Workbench.** The Workbench uses the same editor as the Verify step: full-width cards, and Criteria that can be edited, added and deleted. One "Lưu vào RAG" button re-embeds the whole set. Saving from the Workbench keeps HR's original Standard and Hidden Requirements text intact in `hr_rag.txt`.

## User Stories

### Vietnamese interface
1. As an HR user, I want every page's labels, headings and buttons in Vietnamese, so that I can use the tool without translating in my head.
2. As an HR user, I want alerts and error messages in Vietnamese, so that I understand what went wrong and what to do.
3. As an HR user, I want placeholder examples in the requirement textareas written in Vietnamese, so that I see how to phrase requirements in my own language.
4. As an HR user, I want the five Category names shown only in Vietnamese, so that the labels aren't cluttered with two languages.
5. As an HR user, I want the step names in the progress bar in Vietnamese, so that I know where I am in the workflow.
6. As an HR user, I want the CV Extractor, Candidate Pool and RAG Workbench pages in Vietnamese too, so that the whole app feels consistent.
7. As an HR user, I want technical product names like RAG, ChromaDB and `hr_rag.txt` left as-is, so that they still match documentation and logs.
8. As an HR user, I want Clarification Questions and their stated Implicit Assumptions written in Vietnamese, so that I can answer them easily.
9. As a screen-reader user, I want each page to declare Vietnamese as its language, so that my screen reader pronounces the text correctly.

### Clarify-once intake
10. As an HR user, I want to see Clarification Questions once when I first decompose my requirements, so that I have a chance to sharpen vague wording.
11. As an HR user, I want a single "Phân rã yêu cầu" button once the Clarification Questions appear, so that it's obvious how to move forward.
12. As an HR user, I want that button to decompose my current text even if I edited it after reading the questions, so that I'm not asked the questions again.
13. As an HR user, I want to be able to ignore the Clarification Questions entirely and still decompose, so that they never block me.
14. As an HR user, I want the clarification check to run again if I go back from Category review and change my requirement text, so that new wording also gets checked for Implicit Assumptions.
15. As an HR user, I want to go straight to decomposition without new questions if I go back from Category review but don't change the text, so that I don't have to dismiss the same questions twice.
16. As an HR user, I want decomposition to proceed immediately when the clarification check finds no Implicit Assumptions, so that I don't see an empty questions panel.
17. As an HR user, I want at most 5 Clarification Questions for Standard Requirements and at most 5 for Hidden Requirements, so that the list stays manageable.

### "Use Active RAG" button
18. As an HR user, I want the "Use Active RAG & Skip" button to disappear as soon as I type any requirement text, so that I don't accidentally skip past the new requirements I'm writing.
19. As an HR user, I want the button to reappear if I clear both textareas, so that I can still reuse the stored criteria when I haven't started anything new.
20. As an HR user, I want the button to appear only when the RAG actually contains stored Criteria, so that I'm never offered a skip to an empty set.

### Side-by-side layout
21. As an HR user, I want each Clarification Question shown next to the requirement textarea it refers to, so that I can edit the text while reading the question.
22. As an HR user, I want Standard Requirements questions beside the Standard textarea and Hidden Requirements questions beside the Hidden textarea, so that I never confuse which text a question is about.
23. As an HR user, I want a short "Không có câu hỏi" note when one field has no questions, so that I know that field was checked and is clear.
24. As an HR user, I want the intake form to stay single-column before any questions exist, so that the empty form isn't cramped.
25. As an HR user on a narrow screen, I want each field's questions stacked below its textarea, so that nothing gets squeezed or scrolls sideways.
26. As an HR user, I want each question to show the Implicit Assumption it's based on, so that I understand why it's being asked.

### Waiting screens and time estimates
27. As an HR user, I want an estimated time remaining for every long wait, so that I know whether to wait or come back later.
28. As an HR user, I want a progress bar that moves during a wait, so that I can see the system is working.
29. As an HR user, I want the waiting screen to tell me what is happening in Vietnamese (checking requirements, decomposing, saving criteria, extracting a CV, evaluating candidates), so that I know which step I'm waiting on.
30. As an HR user, I want a waiting screen after clicking "Confirm Criteria", so that I don't think the page has frozen while the criteria are saved.
31. As an HR user, I want a waiting screen when saving from the RAG Workbench, so that I know the save is still running.
32. As an HR user, I want the waiting screen to block clicks while it's showing, so that I can't start a second operation by accident.
33. As an HR user evaluating many candidates, I want to see how many candidates are done out of the total, so that I can trust the progress shown.
34. As an HR user evaluating many candidates, I want the time remaining based on how fast candidates are actually finishing, so that the estimate gets more accurate as the batch runs.
35. As an HR user, I want time estimates to learn from real durations on this server, so that they reflect the model and hardware actually in use.
36. As an HR user on a freshly installed server, I want a sensible default estimate even before any timings have been recorded, so that I still see something useful.
37. As an HR user, I want the estimate to switch to "sắp xong…" instead of going negative when an operation runs longer than expected, so that the screen never shows nonsense.
38. As an HR user, I want the waiting screen to close and show an error message if the operation fails, so that I'm not stuck waiting forever.
39. As an HR user uploading a CV in the Extractor, I want the same waiting screen with an estimate, so that every page behaves the same way.

### Verify & Adjust RAG Categorization
40. As an HR user, I want each Category card to span the full width, so that long Criteria have room.
41. As an HR user, I want Category cards stacked one per row, so that I can read them top to bottom.
42. As an HR user, I want each Criterion's text to wrap across lines, so that I can read all of it without scrolling sideways.
43. As an HR user, I want a Criterion's editing box to grow with its text, so that I can see and edit it all at once.
44. As an HR user, I want to keep adding and deleting Criteria in each Category, so that I can still correct the decomposition.
45. As an HR user, I want each Category card to show how many Criteria it has, so that I can spot an empty or overloaded Category at a glance.

### RAG Vector Database Workbench
46. As an HR user, I want to edit any stored Criterion directly on the RAG Workbench, so that I can fix a mistake without redoing the whole evaluator flow.
47. As an HR user, I want to add a new Criterion to any Category on the Workbench, so that I can extend the stored criteria.
48. As an HR user, I want to delete a Criterion on the Workbench, so that I can remove wrong or outdated criteria.
49. As an HR user, I want the Workbench to use the same full-width, wrapping card layout as the Verify step, so that both editors look and work the same.
50. As an HR user, I want a single "Lưu vào RAG" button that saves all my edits at once, so that the whole set is re-embedded consistently.
51. As an HR user, I want saving from the Workbench to keep my original Standard and Hidden Requirements text in `hr_rag.txt`, so that the summary file still records what I originally asked for.
52. As an HR user, I want the `hr_rag.txt` preview on the Workbench to update after I save, so that I can confirm my edits landed.
53. As an HR user, I want the redundant `[standard]`/`[hidden]` tag removed from each item, so that the list is less cluttered; the card title already names the Category.
54. As an HR user, I want the Workbench's item count and status to refresh after a save, so that the numbers match what's stored.
55. As an HR user, I want the HR Evaluator to pick up criteria I edited on the Workbench when I use "Use Active RAG", so that my Workbench edits are what candidates are evaluated against.

## Implementation Decisions

### Vietnamese interface
- **Scope of translation.** All fixed UI text is translated directly into Vietnamese in the page markup and the front-end controllers: headings, labels, buttons, placeholders, `alert()` messages, loader titles and descriptions, empty and error states, table headers, tier titles and badges. There is no translation layer, dictionary or language toggle.
- **Page language.** Every page's language attribute changes from English to Vietnamese.
- **Category labels.** The five Category display labels become Vietnamese only, on both the Verify step and the Workbench. The Category keys (`seniority_title`, `technical_skills`, `work_experience`, `education_certifications`, `hidden_culture`) don't change.
- **LLM output language.** Every front-end call that accepts a `language` field sends `vietnamese` explicitly: scrutiny, decomposition and extraction. LLM-generated content (Clarification Questions, evaluation reasoning) is already Vietnamese by default and doesn't need further enforcement.

### Clarify-once intake state
- **State.** The evaluator controller keeps a small piece of intake state: whether Clarification Questions have been shown in the current pass, plus the requirement text they were generated from. The existing "text last sent to scrutiny" tracking is reshaped into this.
- **Rules.**
  - The main Decompose button runs the clarification check if no check has run in this pass, or if HR arrived back from Category review and the text differs from what was last checked.
  - Otherwise it decomposes directly.
  - While Clarification Questions are showing, the main Decompose button is hidden, and the panel's own "Phân rã yêu cầu" button always decomposes directly, whatever edits HR made.
  - Returning to intake from Category review starts a new pass.
  - A page reload resets all intake state.
- **Question cap.** The per-field cap of 5 Clarification Questions already exists in the scrutiny backend (`SCRUTINY_MAX_QUESTIONS_PER_FIELD`) and is unchanged.

### "Use Active RAG" visibility
- **Visibility rule.** The skip button is visible only when the RAG has stored Criteria and both requirement textareas are empty after trimming. Visibility is re-evaluated on every input event in either textarea.

### Side-by-side intake layout
- **Grid.** The intake panel becomes a two-row grid, with one row for Standard Requirements and one for Hidden Requirements. Each row has the textarea on the left and that field's Clarification Questions on the right.
- **When the right column appears.** The right-hand column and the wider panel width appear only once questions exist. Before that, the panel keeps its current single-column, capped width.
- **Empty field.** A field with no questions shows a short "Không có câu hỏi" note in its right-hand cell.
- **Narrow screens.** Below a narrow-screen breakpoint, each row stacks, with the questions below their textarea.
- **Panel note.** The panel's explanation (that the questions are optional suggestions) stays, translated into Vietnamese, above the grid or in the first right-hand cell.

### Shared waiting screen
- **Shared module.** One shared front-end waiting-screen module replaces the per-controller loader handling in the evaluator, extractor and RAG controllers. Its interface is roughly:
  - Start a single-call wait, given an operation kind, a title and a description.
  - Start a batch wait, given an operation kind, a title and a total count.
  - Report batch progress: completed count out of total.
  - Finish, on success or failure.
- **Single-call waits.** The module fetches the expected duration for the operation kind from the server. It animates the progress bar and a countdown based on elapsed time against that expected duration. The bar is capped short of 100% until the operation actually finishes. Once elapsed time exceeds the expectation, the countdown text switches to "sắp xong…".
- **Batch waits.** The time remaining is extrapolated from the average time per completed candidate multiplied by the candidates left. Until the first candidate completes, the module falls back to the expected per-candidate duration from the server.
- **Existing overlay.** The existing loader overlay markup is reused and extended with a time-remaining line and, for batches, a counter. Every page that makes the user wait includes it.
- **Operation kinds.** `scrutiny`, `decompose`, `save_criteria`, `extract`, and `evaluate_candidate` (per-candidate, for batches).

### Duration tracking (server)
- **Recording.** The server records the wall-clock duration of each completed operation per operation kind. It keeps a rolling window of recent samples, for example the last 20, in a small JSON file in the project's persistent state area, so estimates survive restarts.
- **Endpoint.** A new read endpoint returns the current expected duration per operation kind: the median of recent samples, or a hard-coded default when there are no samples yet.
- **Defaults.** The defaults are defined in server config.
- **What gets recorded.** Only successful operations are recorded. Recording happens in the scrutiny, decompose, RAG update and extract endpoints, and once per candidate inside batch evaluation.

### Batch evaluation as a background job
- **Start.** A new endpoint starts a batch evaluation with the same inputs as today's batch evaluation. It returns a job id immediately and runs the evaluation in the background, with the existing concurrency limit of 20.
- **Poll.** A new status endpoint returns, for a job id:
  - the state: running, done or failed;
  - the total and completed candidate counts;
  - elapsed seconds;
  - on done, the same results payload the synchronous endpoint returns today;
  - on failure, the error message.
- **Job storage.** Jobs are held in memory in the server's shared state. Jobs don't need to survive a server restart. Finished jobs can be dropped after they have been read, or after a short time to live.
- **Front end.** The front end starts the job, polls the status endpoint every one to two seconds while updating the batch waiting screen, and renders the dashboard from the final results exactly as it does today.
- **Old endpoint.** The existing synchronous batch-evaluation endpoint stays as it is for any non-UI callers.

### Stored original requirements
- **Where it's saved.** Whenever criteria are ingested into the RAG, the RAG engine persists HR's original Standard Requirements and Hidden Requirements text alongside the stored Criteria, in the RAG's persistent storage area. This covers both decomposition and manual updates.
- **Where it's returned.** The RAG summary returned by the RAG info endpoint includes these two texts.
- **Update endpoint.** The RAG update endpoint's Standard and Hidden Requirements fields become optional. When they are omitted, the stored originals are reused for `hr_rag.txt` and re-stored unchanged. When they are provided, as from the evaluator page, they replace the stored originals.
- **Clear.** Clearing the RAG also clears the stored originals.

### Shared Criteria editor (Verify step and RAG Workbench)
- **Shared component.** The Category-card editor currently built inside the evaluator controller is extracted into a shared front-end module. It takes the current categories as `{category_key: [criterion text]}`, renders the five full-width cards, and exposes the edited categories back to the caller. The evaluator's Verify step and the RAG Workbench both use it.
- **Criterion fields.** Each Criterion is an auto-growing, wrapping textarea. Enter doesn't insert newlines; Criteria stay single logical lines.
- **Card layout.** Cards are stacked, one per row, at full width.
- **Workbench save.** "Lưu vào RAG" sends the edited categories to the RAG update endpoint without requirement text, relying on the stored originals. It shows the shared waiting screen with the `save_criteria` kind, then reloads the Workbench summary and the `hr_rag.txt` preview.
- **Type tag.** The per-item `[standard]`/`[hidden]` tag is no longer shown. It is still derived from the Category on the server.

### Confirm Criteria waiting screen
- **Behaviour.** "Xác nhận tiêu chí" (Confirm Criteria) shows the shared waiting screen with the `save_criteria` kind while saving. It advances to candidate selection only if the save succeeds. On failure it stays on the Verify step and shows the error.

## Testing Decisions

- **No automated tests.** This repo doesn't get new automated tests for this work: no unit, API or browser tests.
- **Implementer's verification.** The implementer checks correctness by reasoning through the code paths, in particular:
  - the clarify-once state transitions;
  - "Use Active RAG" visibility;
  - job state transitions and failure handling;
  - the fallback to stored original requirements when the update endpoint omits them;
  - that the time estimate never shows negative or above-100% values.
- **Manual testing.** All behavioural and visual checks are done manually by the developer in the running app. The implementer doesn't launch or drive a browser.

## Out of Scope

- An English/Vietnamese language toggle, or any translation infrastructure.
- Translating LLM prompt templates, log output, CLI tools, or files written to disk other than what is already language-parameterized.
- Real progress reporting inside a single LLM call (streaming tokens or partial results).
- Persisting batch-evaluation jobs across server restarts, or cancelling a running job.
- Changing how Criteria are decomposed, scored or weighted.
- Changing the per-field cap of 5 Clarification Questions.
- Per-item saving on the RAG Workbench; saving is always whole-set.
- Changing the Candidate Pool's features beyond translation and adopting the shared waiting screen where it waits.

## Further Notes

- **Two meanings of "category".** In conversation, "category" was used for the Standard/Hidden split. In this codebase's glossary, Category means one of the five fixed buckets, and Standard/Hidden are *fields*. This spec uses the glossary terms.
- **Glossary update.** The clarify-once rule is recorded in `CONTEXT.md` under **Clarification Question**.
- **Suggested order of work.** Rough dependency order: stored original requirements and duration tracking on the server → background batch job → shared waiting screen → shared Criteria editor → intake flow changes → Vietnamese translation last, so strings are translated once in their final place.
