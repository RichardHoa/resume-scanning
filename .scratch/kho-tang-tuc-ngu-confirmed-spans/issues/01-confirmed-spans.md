# 01: Confirmed Spans replace Fixes, from the review page through reruns and the export

**What to build:** The developer edits or confirms one Entry Span at a time on the review page. Either way it becomes a Confirmed Span: its full detail is appended to the review log, its Warnings disappear, and it shows as confirmed straight away. Every later run takes its Blocks from that record and sends no request for it, however the layout is read later, until the developer undoes it. A fully confirmed page sends no request at all. Page-level Fixes and the stale state are gone. The job also runs 60 requests at a time. Full decisions and user stories: `.scratch/kho-tang-tuc-ngu-confirmed-spans/spec.md`, with ADR 0006.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

### The review log
- [ ] Saving an edit or confirming appends a `confirmed` line holding the span's full detail as the spec lists it, including its PDF hash, band, the model's Blocks and whether it was edited; nothing else is needed to rebuild the span
- [ ] Undo appends an `unconfirmed` line, the printed number has its own `printed_page` lines, and confirming a page's last span also appends `page_complete`
- [ ] The latest line for a span wins, old Fix lines are ignored with no migration, the log is append-only, and no run writes to it

### Reruns
- [ ] No Entry Span request is sent for a Confirmed Span, and a partly confirmed page gets only its layout request and requests for its unconfirmed spans
- [ ] A page whose `page_complete` applies sends no request, and once one of its spans is undone the layout runs again
- [ ] A line whose centre falls inside a band belongs to that Confirmed Span, whatever its Line Number or the layout answer now says
- [ ] Model start lines inside a band are ignored, and the first line below a band is forced to be a start
- [ ] A span beginning at a forced start is sent as a Leading span, with the Leading span's user text reworded to fit a continuation in the middle of a page
- [ ] A run stops before any request, naming the pages, if a Confirmed Span's PDF hash differs from the current PDF
- [ ] A page with a failed request still has no answer, and its Confirmed Spans return when it succeeds

### Rebuilding the entries
- [ ] The CLI, the review server and the export share one standard-library function that lays Confirmed Spans over a page's spans, so a confirmation shows with no run
- [ ] Each page in the store's answers carries its spans, so that function needs no PDF and no line data
- [ ] After a run without the latest log, a model span inside a band is replaced, and one only partly overlapping stays and raises a `confirmed_overlap` Warning
- [ ] Undo puts the model's Blocks and their Warnings back straight away, whether or not the span's saved answer still exists
- [ ] The printed number comes from the developer's line, then `page_complete` while it applies, then the layout answer

### Warnings
- [ ] Blocks of a Confirmed Span raise no Model Edit, Diacritic Disagreement, Citation problem, number gap or duplicate, and the Blocks of other spans still line up against the page's reads
- [ ] A Confirmed Span's numbers still feed other spans' checks: an unconfirmed A 16 warns that it follows A 14, and a second A 4 keeps its duplicate Warning
- [ ] The Page number Warning clears when the number is edited or confirmed, a Leading Block with no owner clears when its Leading span is confirmed, and Missing page and Ink outside the lines stay

### The review page
- [ ] Each entry card has Edit and Confirm acting on the Entry Span holding its Blocks on this page, the editor opens the whole span, and a span holding two entries is shared by their cards
- [ ] A Confirmed Span shows Undo and a "Confirmed" tag, plus "Edited" if its text changed, and its rectangle on the scan has its own colour
- [ ] The editor's preview shows the Warnings the Blocks would raise, without blocking the save
- [ ] The page info line can edit, confirm and undo the printed number
- [ ] "Edit the page" and everything for stale Fixes are gone
- [ ] The progress line says "N spans confirmed", with no total and no "next unconfirmed" jump
- [ ] The Edits list becomes a Confirmed list, showing edited spans by default with a toggle to show all
- [ ] The diff against the transcription comes from the record's model Blocks

### Export, job and docs
- [ ] The export's `fixed` is true only if a span holding the entry was edited, and no `confirmed` field is added
- [ ] This job's concurrency is 60 in its submit script, and the default model profile and shared default stay at 40
- [ ] The GPU memory share stays at 0.85, with its comment updated to the new count
- [ ] The README's review steps and store table, and the docstrings of the CLI, review server, review module and export, describe Confirmed Spans and no longer mention Fixes
- [ ] Verified by reasoning through the code: no tests added, nothing checked in a browser, nothing committed
