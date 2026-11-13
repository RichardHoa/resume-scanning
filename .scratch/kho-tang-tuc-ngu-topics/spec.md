Status: ready-for-agent

# Kho tàng tục ngữ người Việt: the Hệ thống tra cứu theo chủ đề

Vocabulary: `vsc-project/khoTangTucNguoiNguoiViet/GLOSSARY.md`, plus the terms defined under Implementation Decisions (add them to the GLOSSARY as part of this work). Grilled 2026-11-13.

## Problem Statement

After its last proverb page (PDF 542), Part 4's PDF holds the book's topic index, the Hệ thống tra cứu theo chủ đề. It files Proverb Entries under four chủ đề and their numbered tiểu chủ đề, naming each entry only by letter and number. The digitizing website should let a reader browse and filter proverbs by these headings, and show the index's Lời dẫn as its own section beside the Front Matter's intro.

The index pages are almost all numbers: roughly 15-25k entry names on about 128 pages. A VLM reading them alone will hallucinate in ways that look right, such as skipping, repeating or extending a run like `1385, 1386, … 1414`. The developer needs a scan where no number reaches the export unchecked, and a review server where they only look at the lines that need a human.

## Solution

`sbatch scripts/khotangtucngu/submit.sh --part-4-final-section` reads PDF 547-674 one printed line at a time. Each line is read twice, independently: by Apple Vision on the Mac, as for the proverb pages, and by the VLM from the line's crop, **without** Vision's read in its prompt. A number is accepted only when both reads agree, and every accepted number also passes structural checks: it names a real Proverb Entry, numbers ascend within a row, the item counts match, letters stay in alphabet order, and headings are numbered in sequence. Anything else becomes a Warning.

A review server in the section's own store shows each page with its lines marked as agreed, warned or confirmed. Next to it is the index as assembled (headings, letter rows, numbers) and a list of Warnings. The developer confirms or corrects a line, and that goes into an append-only review log that every rebuild lays over the model's reads.

An export writes `topics.json` (the headings and their entries by anchor), `topic-intro.md` (the Lời dẫn) and `compilers.md` (Vài nét về các soạn giả), all ready for the website. The website itself is a later piece of work.

## User Stories

1. As the developer, I want to run `vision_ocr.py --part-4-final-section` on the Mac, so that every printed line of PDF 547-674 has its line read and page read before the GPU job runs.
2. As the developer, I want `submit.sh --part-4-final-section` to reject a page with missing or stale Vision reads before the server starts, so that no GPU time is wasted, as with the Parts.
3. As the developer, I want `--pages` and `--dry-run` to work for the section as they do for a Part, so that I can try pages 547-556 first and check that prompts fit.
4. As the developer, I want each number line read by the VLM without seeing Vision's read, so that the two reads are independent and agreement means something.
5. As the developer, I want the VLM to see one printed line per request, so that it has no visible run of numbers to continue.
6. As the developer, I want a number accepted only when the VLM read and Vision agree on it, so that one reader's mistake never reaches the export.
7. As the developer, I want every line where the reads disagree to raise a Warning showing both reads, so that I can decide from the crop.
8. As the developer, I want a line with only one read (the VLM failed after its retries, or Vision has no read) always raised as a Warning, even if every check passes, so that no number goes out with a single read.
9. As the developer, I want every (letter, number) checked against the Proverb Entries of Parts 1-4, so that a number naming no entry is caught.
10. As the developer, I want numbers lost in the book or its scan (C 1856-1861, M 141-237) kept as unresolved rather than dropped or flagged as misreads, so that the index stays faithful to what is printed.
11. As the developer, I want a Warning when a number in a letter row is not greater than the one before, including across lines and pages, so that dropped, repeated or misread digits show up.
12. As the developer, I want a Warning when the count of comma-separated items in Vision's read differs from the count of integers the VLM read, so that a swallowed or invented item shows up even where the digits agree.
13. As the developer, I want a Warning when a letter row comes before the previous one in the alphabet, so that a misread row letter shows up.
14. As the developer, I want a Warning when a tiểu chủ đề number does not continue the sequence, or a chủ đề is not the next of I-IV, so that a misread or missed heading shows up.
15. As the developer, I want heading lines read by the VLM with Vision's reads as a hint, as Entry Spans are, so that their Vietnamese diacritics are copied well.
16. As the developer, I want a heading that wraps onto a second line joined into one heading, so that long titles come out whole.
17. As the developer, I want a letter row that runs onto the next page (page 600 opens mid-row) continued under the same letter and tiểu chủ đề, so that rows are not split or orphaned.
18. As the developer, I want a line the parser cannot classify raised as a Warning, so that an unexpected third heading level or stray text is never silently dropped.
19. As the developer, I want ink outside every found line raised as a Warning, as on proverb pages, so that a line the line finder missed is not lost.
20. As the developer, I want scan noise (stray dots, a comma read as a dash) to cost nothing when both reads still agree on the numbers, so that I only review real problems.
21. As the developer, I want the existence check to tell me when a Part had no answers.json at run time, once per Part and not once per number, so that I know which checks didn't run.
22. As the developer, I want answers saved with a stamp and only stale or failed requests redone, so that runs over different pages add up and reruns are cheap, as with the Parts.
23. As the developer, I want `python3 serve.py` in the section's store to open a review page that needs no PDF and nothing installed, so that I can review on any machine.
24. As the reviewer, I want each page's scan shown with its lines marked as agreed, warned or confirmed, so that I can see where the problems are at a glance.
25. As the reviewer, I want the assembled index shown beside the scan (chủ đề, tiểu chủ đề, letter rows and their numbers), so that I can check structure as well as digits.
26. As the reviewer, I want a list of every Warning across pages, grouped by kind, that takes me to its page and line, so that I can work through them in order.
27. As the reviewer, I want a line's crop shown with its Vision line read, page read and VLM read side by side, so that I can judge it without opening the PDF.
28. As the reviewer, I want to confirm a line as read, so that its Warning is cleared and its numbers count as checked.
29. As the reviewer, I want to correct a line's letter, numbers or heading text, and see the checks rerun on my correction before I save it, so that a fix doesn't break the ascending or existence checks.
30. As the reviewer, I want to undo a confirmed line, so that a mistaken confirmation can be taken back.
31. As the reviewer, I want my confirmations to survive reruns of the job, with nothing ever rewriting or deleting the review log, so that review work is never lost.
32. As the reviewer, I want a confirmed line to override the model's read wherever its band falls, even if line numbering changes on a rerun, so that my decision stays attached to the printed line.
33. As the reviewer, I want the page to be read-only and say so when the store can't be written, as the Parts' server does.
34. As the developer, I want to export `topics.json` with every chủ đề and tiểu chủ đề, their titles, and their entries as anchors in printed order, so that the website can filter by heading.
35. As the developer, I want each tiểu chủ đề in `topics.json` to list its unresolved names apart from its entries, so that the website never links to an entry that doesn't exist.
36. As the developer, I want the export to refuse, or clearly list, any line that still has an unreviewed Warning, so that I don't ship unchecked numbers by accident.
37. As the developer, I want `topic-intro.md` and `compilers.md` exported from the hand-transcribed `back-matter.md`, so that the website gets the Lời dẫn and the compilers' biographies as their own sections.
38. As a website reader (later), I want to pick one chủ đề or tiểu chủ đề from a tree with counts and a search box, so that I can browse proverbs by theme.
39. As a website reader (later), I want picking a topic to show entries from every letter, in book order, so that I see the whole theme and not one letter's slice.

## Implementation Decisions

**Terms** (to add to the GLOSSARY):

- **Topic Index**: the Hệ thống tra cứu theo chủ đề, PDF 547-674 of Part 4.
- **Chủ đề**: one of its four top headings, I-IV.
- **Tiểu chủ đề**: a numbered heading under a chủ đề ("17. Tiền bạc, của cải, vay mượn, nợ nần").
- **Topic Row**: one letter and its entry numbers under a tiểu chủ đề, possibly over several lines and pages.
- **Index Line**: one printed line of the Topic Index. It is the unit that is read, checked and confirmed.
- **Confirmed Line**: an Index Line the reviewer has confirmed or corrected.

**Scope and settings**

- The section is PDF 547-674 of Part 4's PDF, with Part 4's book page offset (2422).
- It gets its own key, `part-4-final-section`, in a settings map separate from `PARTS`, so that the Parts' export and their See-also lookups never take it for a Part.
- `cli.py`, `vision_ocr.py` and `submit.sh` accept the key as a flag alongside the Part flags. `cli.py` hands it to a new Topic Index module, not to the layout/Entry Span path.
- Its store is `store/part-4-final-section/`, separate from Part 4's store.
- PDF 543-546 (title, blank, Lời dẫn) and PDF 816 are in `back-matter.md`, transcribed by hand. The pipeline never reads them.

**Mac step**

- `vision_ocr.py` runs unchanged on the section's pages: line finding, line read, page read and stability crops. It writes `lines/` and `vision/` into the section's store.

**Classifying Index Lines** (code, from the Vision reads and the line's geometry):

- A centred roman numeral alone starts a chủ đề.
- The non-number lines that follow it are its title, joined.
- `N. words` at the left margin starts a tiểu chủ đề; following non-number lines continue its title.
- A single letter of the book's alphabet at the left margin followed by numbers starts a Topic Row.
- An indented line of numbers continues the current Topic Row, including at the top of a page.
- Anything else is an unclassified line and raises a Warning.
- If the VLM's read contradicts the classification (letters where numbers were expected, or the reverse), that raises a Warning too.

**The two reads**

- A number line's request sends only the line's crop, cut as Entry Span crops are at `PAGE_DPI`. The VLM answers in JSON: the row letter (if printed) and a list of integers. Structured output allows nothing else.
- A heading line's request sends its crop with its line read and page read as a hint, in the same way as the Entry Span prompt. The VLM answers in JSON with the heading text.
- The same retry, temperature, stamping and `token_usage.jsonl` conventions as the Parts apply. A request's answer is saved under the page and the line's Line Number.
- **Agreement:** for a number line, the integer list and the row letter from the VLM must equal the ones parsed from Vision. The line read is used, falling back to the page read where the line read can't be parsed. Agreed lines are accepted. A disagreeing line raises a Warning showing all three reads.
- **Single read (settled):** a line with only one read is always a Warning, whatever the checks say.

**Checks** (run in assembly, over accepted, warned and confirmed lines alike):

1. **Exists.** (letter, number) names a Proverb Entry of Parts 1-4. The run builds the set of entry names from every Part's store that has `answers.json`, with its review log laid over, and saves it in the section's store so that the review server needs no other store. A Part with no `answers.json` raises one Warning. Names inside a Part's `number_jumps` or `scan_gaps` are unresolved, not Warnings.
2. **Ascending.** Each number in a Topic Row is greater than the one before, across lines and pages.
3. **Count.** The number of comma-separated items in Vision's read equals the number of integers in the VLM's read.
4. **Letter order.** Topic Rows under one tiểu chủ đề follow the book's alphabet (the same `ALPHABET` the Parts use) and never go back. Skipping a letter is fine.
5. **Heading numbers.** Chủ đề run I-IV. A tiểu chủ đề number is the previous one plus 1, or 1 where a chủ đề starts, whichever the book turns out to do. Code accepts either, and nothing else.

Warnings use the same `warning(kind, place, reason, page)` shape and `warnings.json` file as the Parts. They also include ink outside every found line, and failed or missing pages.

**Store outputs** (by analogy with a Part's store):

- `lines/`, `vision/`: from the Mac.
- `pages/pNNN.png`: for the review server.
- `lines/pNNN-LMM.json`: one VLM answer per Index Line.
- `answers.json`: every page's Index Lines with their band, crop, classification, both reads and the VLM answer, so the review server needs no PDF.
- `entry_names.json`: the existence set and the unresolved ranges.
- `topics.json` (assembled): rebuilt from the answers with Confirmed Lines laid over.
- `warnings.json`.
- `review.jsonl`.
- The review server's code and web page, copied in on every run.

**Review log** (`review.jsonl`, append-only, written only by the server; same rules as the Parts' log):

- `{"type": "confirmed_line", "page", "pdf_sha1", "band", "kind", "letter", "numbers", "text", "model": {...}, "edited"}`: a Confirmed Line, whole, keyed by page and band like a Confirmed Span. `kind` is chủ đề, tiểu chủ đề, title continuation, Topic Row start or Topic Row continuation.
- `{"type": "unconfirmed_line", "page", "band"}`: that line undone. The latest of the two for a band wins.
- A Confirmed Line clears the Warnings raised on that line by disagreement or a single read. The structural checks still run on its values.

**Review server** (a new standard-library server for the section's store, following `serve.py`'s conventions):

- `GET /assembled`: the pages, Index Lines, assembled `topics.json` and Warnings, rebuilt with the log.
- `POST /preview`: one line's proposed values; returns the Warnings the page and its neighbouring rows would have with them.
- `POST /review`: appends `confirmed_line` or `unconfirmed_line`.
- **The web page:**
  - the scan, with lines tinted by state;
  - the assembled index for that page;
  - a Warning list across pages, grouped by kind, that jumps to the line;
  - a line panel with the crop, the three reads, and an editor for the letter, numbers or text, with confirm and undo.
- It is read-only when the store can't be written.

**Export** (run locally, no GPU, like `export.py`):

- `export/topics.json`: `{"topics": [{"id": "I", "title", "subtopics": [{"id": "I.1", "number", "title", "entries": ["A-8", …], "unresolved": ["C-1858"]}]}]}`. Anchors are the same as `letters/*.json` uses. Entries are in printed order.
- `export/topic-intro.md`: the Lời dẫn section of `back-matter.md`.
- `export/compilers.md`: the Vài nét về các soạn giả section of `back-matter.md`.
- HTML comments and ⚠ markers are stripped from both `.md` files, as `intro.md` is from the Front Matter.
- The export stops and lists every line that still has an open disagreement or single-read Warning.
- **Settled (Q1 b):** the Parts' `letters/*.json` gain no `topics` field. The link lives only in `topics.json`, and the website inverts it.

## Testing Decisions

- No automated tests are added in this project. Verification is by reasoning about the code and a trial run on PDF 547-556 that the developer runs and reviews in the new server.
- A good trial shows:
  - every line classified;
  - agreement on most number lines;
  - every planted problem caught: a page with a row crossing onto it (600), stray dots (547's `·605`), a dash for a comma (548's `138,-139`);
  - `topics.json` assembling chủ đề I's first tiểu chủ đề as printed.
- Prior art: the Parts' trial runs (`--pages 36-45,420-421`) and review in `serve.py`.

## Out of Scope

- The website's topic filter, topic chips and Lời dẫn and compiler sections (see Further Notes for what is already settled).
- PDF 675 onward (Bảng tra tên đất, other indexes, bibliography), except PDF 816, which is already in `back-matter.md`.
- The book's summary pages, PDF 815 (Vietnamese) and 817 (English). They can be added to `back-matter.md` if wanted.
- Changes to the Parts' layout/Entry Span pipeline or their review server.

## Further Notes

- **Settled for the website, when it is built:**
  - Picking a topic shows entries from every letter in book order; the letter grid becomes an optional narrowing (Q3).
  - The facet is a single-select tree of chủ đề → tiểu chủ đề, with entry counts and a search box over titles, kept in the URL as `t=II` or `t=II.17` (Q4).
  - The site loads `topics.json` once and builds anchor → topics itself (Q1 b).
- **ADR:** reading number lines without Vision's read in the prompt is the reverse of ADR 0005, where the reads are hints. It deserves its own ADR beside the GLOSSARY: independence is what makes agreement worth anything, and digits gain nothing from a hint.
- **Per-page structure:** chủ đề I opens on PDF 547. Lời dẫn says chủ đề I has nine tiểu chủ đề, which the heading-number check can confirm.
