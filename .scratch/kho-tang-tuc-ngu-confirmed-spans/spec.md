Status: ready-for-agent

# Kho tàng tục ngữ người Việt: Confirmed Spans, one developer decision that lasts

Grilled 2026-11-06. Changes the Fixes of `.scratch/kho-tang-tuc-ngu-review-editing/` and the saved Entry Span answers of `.scratch/kho-tang-tuc-ngu-entry-spans/`. Vocabulary: `vsc-project/khoTangTucNguoiNguoiViet/GLOSSARY.md` (new: Confirmed Span; removed: Fix). Decision records: `vsc-project/khoTangTucNguoiNguoiViet/docs/adr/0006-confirmed-spans-override-the-layout.md`, which changes `0005-two-reads-and-model-edits.md`.

## Problem Statement

A Fix holds the developer's corrected Blocks of a whole PDF page, and it goes stale when a rerun changes that page's answer, so a new prompt can undo the developer's work. Warnings the developer has already judged come back on every view, and a Model Edit can't be dismissed at all. Every rerun also pays to read text the developer has already settled.

## Solution

The developer edits or confirms one Entry Span at a time on the review page. Either way it becomes a Confirmed Span: its full detail is appended to the review log, its Warnings disappear, and every later run takes its Blocks from that record and sends no request for it. One decision by the developer lasts until the developer undoes it.

## User Stories

### Confirming and editing
1. As the developer, I want a Confirm button for an Entry Span, so that I can say its text is right without changing it.
2. As the developer, I want saving an edit of an Entry Span to confirm it, so that I never have an edited span still raising Warnings.
3. As the developer, I want Edit and Confirm on each Proverb Entry's card, acting on the Entry Span holding that entry's Blocks on this page, so that I keep working from the entries I read.
4. As the developer, I want the editor to open the whole Entry Span, so that what I save is exactly what becomes confirmed.
5. As the developer, I want two Proverb Entries in one Entry Span to share its confirmation, so that a missed start line doesn't stop me confirming them.
6. As the developer, I want an entry running onto the next page confirmed separately on each page, so that each page's span is judged against its own scan.
7. As the developer, I want to edit a Confirmed Span again, with the latest save winning, so that I can correct my own mistake.
8. As the developer, I want an Undo on a Confirmed Span, so that a misclick is not permanent.
9. As the developer, I want Undo to put the model's Blocks and their Warnings back straight away, so that I see at once what I reverted to.
10. As the developer, I want the editor's live preview to show the Warnings the Blocks would raise, so that I catch a typo before saving clears them.
11. As the developer, I want those preview Warnings not to block saving, so that I stay the final judge.

### Warnings
12. As the developer, I want no Warning raised on a Confirmed Span's Blocks, so that a judged span never asks for my attention again.
13. As the developer, I want a Confirmed Span's numbers to still feed the checks of other spans, so that an unconfirmed A 16 still warns that it follows A 14.
14. As the developer, I want a second A 4 to keep its duplicate Warning after the first is confirmed, so that confirming one entry doesn't hide a problem in another.
15. As the developer, I want to edit and confirm a page's printed number, permanently, so that a Page number Warning can be settled.
16. As the developer, I want to undo a printed number I set, so that it can be reversed like a span.
17. As the developer, I want a Leading Block with no owner Warning cleared when its Leading span is confirmed, so that I can settle it like any other.
18. As the developer, I want Missing page and Ink outside the lines Warnings to stay, so that a page with no answer and ink in no span are never hidden by a confirmation.

### Reruns
19. As the developer, I want no Entry Span request sent for a Confirmed Span, so that a rerun doesn't pay for settled text.
20. As the developer, I want a fully confirmed page to send no request at all, so that it costs nothing on any later run.
21. As the developer, I want a page to need its layout request again once one of its spans is undone, so that the unconfirmed span can be cut and read.
22. As the developer, I want a partly confirmed page to get requests only for its layout and its unconfirmed spans, so that only unsettled text is paid for.
23. As the developer, I want a Confirmed Span to keep its place when a new layout answer cuts the page differently, so that a new prompt can't undo my decision.
24. As the developer, I want it to keep its place if the line finder changes the Line Numbers, so that my Blocks never attach to the wrong lines.
25. As the developer, I want lines left below a Confirmed Span read as a continuation of the entry above, so that the model doesn't invent a proverb for them.
26. As the developer, I want a run to stop before any request if a Confirmed Span was made from another PDF, so that my Blocks are never placed on different text without my knowing.
27. As the developer, I want a page with a failed request to keep its Confirmed Spans in the log, so that they return when the page succeeds.
28. As the developer, I want confirmations made since the last run to show at once, so that the review page never waits for a run.
29. As the developer, I want a run without my latest log to lose nothing, so that forgetting to push only wastes requests.
30. As the developer, I want a model span only partly overlapping a Confirmed Span kept with a Warning, so that text is never dropped or doubled silently.

### The record
31. As the developer, I want each Confirmed Span's full detail in the review log, so that the record stands alone with nothing looked up elsewhere.
32. As the developer, I want the model's Blocks kept in the record, so that the diff against the transcription survives once the span stops being read.
33. As the developer, I want the review log append-only and never written by a run, so that no run can lose my decisions.
34. As the developer, I want my laptop's review log to be the master copy, carried to the cluster by my own push, so that no extra command is needed.

### The review page
35. As the developer, I want "Confirmed" and "Edited" tags on a card, so that I see at a glance what I have settled and what I changed.
36. As the developer, I want a Confirmed Span's rectangle on the scan in its own colour, so that I see which of a page's spans are settled.
37. As the developer, I want the progress line to count spans confirmed, with no total and no "next unconfirmed" jump, so that review doesn't become a checklist of 16,000 entries.
38. As the developer, I want the next-Warning jumps to skip Confirmed Spans, so that they lead only to what is unsettled.
39. As the developer, I want a Confirmed list showing edited spans by default and all with a toggle, so that I can find what I changed.

### Export and job
40. As the developer, I want an entry marked `fixed` in the export only if a span holding it was actually edited, so that a span confirmed unchanged isn't called fixed.
41. As the developer, I want this job to run 60 requests at a time, so that a Part finishes sooner.
42. As the developer, I want other jobs and the default model profile left at 40, so that they aren't affected.

## Implementation Decisions

### Confirmed Span replaces Fix
- Page-level Fixes and the stale state are removed. Nothing can make a Confirmed Span stale.
- Old Fix lines in the review log are ignored, with no migration.
- There is no "edited but unconfirmed" state.

### The review log's lines
Lines are written only by the review server. A span is identified by its PDF page and its band, and the latest `confirmed` or `unconfirmed` line for a span wins.

- **`confirmed`**: PDF page, PDF hash, band, first and last Line Numbers, whether it is Leading, crop, each line's readings and crop reads, Blocks, the model's Blocks, whether it was edited, and time.
- **`unconfirmed`**: PDF page, band and time.
- **`printed_page`**: PDF page, the developer's printed number (null undoes it) and time.
- **`page_complete`**: PDF page, printed number, body start and time, appended by the server when a page's last span is confirmed.

The band is the pixel rows of the 300 dpi scan from the top of the span's first line to the bottom of its last. `edited` is true when the Blocks differ from the model's. Confirming a span again carries its model's Blocks forward.

### The span holds its place
- A line whose centre falls inside a band belongs to that Confirmed Span, whatever its Line Number is now.
- Model start lines inside a band are ignored. The first line below a band is forced to be a start, and the rest of the page is cut as usual.
- A span beginning at a forced start, and not at a start the model named, is sent as a Leading span. The Leading span's user text is reworded to fit a continuation in the middle of a page. This changes the prompt hash, so every span not yet confirmed is read again on the next run.
- Before any request, a run stops if a Confirmed Span's PDF hash differs from the current PDF, naming the pages. The review server makes no such check, as it has no PDF.

### Requests
- No Entry Span request is sent for a Confirmed Span.
- A partly confirmed page still gets its layout request, reused from its saved answer as usual, and requests for its unconfirmed spans.
- A run sends no request for a page with a `page_complete` line whose lines from body start down all fall in bands. Once a span is undone that condition fails, so the line is ignored and the layout runs again.
- The printed number comes from the developer's `printed_page` line if there is one, then `page_complete` while it applies, then the layout answer.
- A page with any failed request still has no answer.

### Rebuilding the entries
- The review module holds the one function that lays Confirmed Spans over a page's spans. The CLI, the review server and the export all use it. It stays standard library only, as it is copied into the store.
- Each page in the store's answers carries its spans, with each span's Block range, band, crop, Line Numbers and whether it is Leading, so the overlay works with no PDF and no line data.
- If the cluster ran without the latest log, a model span lying inside a band is replaced by the Confirmed Span. A model span only partly overlapping a band can't be divided, so it is kept and raises a new `confirmed_overlap` Warning on the model's span until a run with the log cuts the page again.
- Undoing a span puts its model's Blocks back straight away, whether or not its saved answer still exists. The next run reuses that answer if it is current, and otherwise reads the span again.

### Warnings
- Checks skip Blocks of a Confirmed Span: Model Edits, Diacritic Disagreements, Citation problems, number gaps and duplicates. The filter is by Block index, before the per-entry counting.
- A Confirmed Span's lines stay in the page's reads, so the Blocks of the other spans still line up against them.
- The Page number Warning clears when the developer edits or confirms the number. Missing page and Ink outside the lines stay, including false alarms.
- Accepted cost: confirming A 14 permanently hides "A 14 follows A 12", even if A 13 really is missing.

### The review page
- "Edit the page" and everything for stale Fixes are removed.
- The Edits list becomes the Confirmed list.
- The server gains what the page needs to confirm, undo and set a printed number. Its preview keeps raising Warnings on the Blocks being edited, whether or not the span is already confirmed.

### Export
- `fixed` is true when any span holding the entry has been edited. No `confirmed` field is added, as the website doesn't read this export yet.

### Concurrency
- This job's concurrency goes from 40 to 60, in its submit script only. The default model profile and the shared default stay at 40.
- The job's GPU memory share stays at 0.85. Its comment, sized for "the KV cache of its 40 requests", is updated to the new count. The first job at 60 should be a small batch of pages, to show whether the cache still fits.

### Docs
- The README's review steps and store table, and the docstrings of the CLI, the review server, the review module and the export, are updated.

## Testing Decisions

No tests are added and nothing is checked in a browser, as is the rule in this repo. The change is verified by reasoning through the code, then by the developer's own use of the page on a real store.

## Out of Scope

- Typing in a span whose request keeps failing (such as p042-L02). Allowing pages with holes changes assembly, so it would be its own spec.
- Dismissing a false Ink outside the lines Warning.
- Confirming every span of a page in one click.
- Moving Blocks between spans, or re-cutting a span by hand.
- A `confirmed` field on the website's data.
- A command to copy the review log to the cluster.

## Further Notes

- From one 15-page trial, a page has about 5.7 Entry Spans, and a layout request takes about 39 s against a median of 13.7 s for an Entry Span. With about 40 requests or more in flight, the trial's pace would make Part 1 about 1.5–2 hours. So a confirmed span saves little of the layout's cost until its whole page is confirmed.
