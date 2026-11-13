# 01: Scan, check and export the Topic Index (PDF 547-674)

**What to build:** Make the developer's route from the scan to the website's data work for the Topic Index (Hệ thống tra cứu theo chủ đề) in Part 4's PDF:

1. Run Apple Vision on the Mac with `--part-4-final-section`.
2. Run `submit.sh --part-4-final-section` on the cluster. Each Index Line is read by the VLM independently of Vision. Numbers are accepted only where the two reads agree, and the five checks run over everything.
3. Read the results in the store's `warnings.json` and assembled `topics.json`.
4. Export `topics.json`, `topic-intro.md` and `compilers.md`.

Confirmed Lines from `review.jsonl` are laid over the reads by the rebuild this ticket owns. The review server that writes them is ticket 02.

Full design: `.scratch/kho-tang-tuc-ngu-topics/spec.md`. Vocabulary: the book's GLOSSARY plus the terms the spec defines (Topic Index, Chủ đề, Tiểu chủ đề, Topic Row, Index Line, Confirmed Line). The website is out of scope.

**Blocked by:** None (can start immediately).

**Status:** done

**Settings and flags**

- [x] A `part-4-final-section` key is defined apart from the Parts: Part 4's PDF, PDF pages 547-674, book page offset 2422. The Parts' export and See-also never see it.
- [x] `vision_ocr.py`, `cli.py` and `submit.sh` accept the key as a flag. `--pages`, `--dry-run` and `--check-reads` behave as for a Part.
- [x] Its store is `store/part-4-final-section/`.

**Classifying lines**

- [x] Each Index Line is classified from its Vision reads and position as one of:
  - chủ đề numeral;
  - title continuation;
  - tiểu chủ đề;
  - Topic Row start (letter + numbers);
  - Topic Row continuation;
  - unclassified, which raises a Warning.
- [x] Wrapped headings are joined. A Topic Row carries on across lines and pages.

**The two reads**

- [x] A number line's request sends only its crop, with no Vision read. The JSON answer is the row letter, if printed, and a list of integers.
- [x] A heading line's request sends its crop with both Vision reads as a hint.
- [x] Answers are stamped, retried, and logged in `token_usage.jsonl` as the Parts' are.

**Agreement and Warnings**

- [x] A number line is accepted only when the VLM's letter and integers equal those parsed from Vision. The line read is used, falling back to the page read.
- [x] A disagreement is a Warning showing all three reads.
- [x] A line with a single read is always a Warning.

**Checks**

- [x] Exists: every (letter, number) names a Proverb Entry of Parts 1-4. The set of entry names comes from every Part store with `answers.json`, with its review log laid over, and is saved as `entry_names.json`.
- [x] A Part with no `answers.json` raises one Warning.
- [x] Names inside `number_jumps` or `scan_gaps` are unresolved, not Warnings.
- [x] Ascending: numbers go up within a Topic Row, across lines and pages.
- [x] Count: the comma-separated items in Vision's read match the number of integers the VLM read.
- [x] Letter order: Topic Rows follow the book's alphabet.
- [x] Heading numbers: chủ đề run I-IV; a tiểu chủ đề is the previous one plus 1, or 1 at a new chủ đề.
- [x] Ink outside every found line, and failed or missing pages, raise Warnings as on proverb pages.

**The contract with ticket 02**

- [x] The rebuild is standard-library only and copied into the store on every run, as `assembly.py` and `review.py` are.
- [x] Given `answers.json`, the review log and `entry_names.json`, it returns:
  - the assembled topics;
  - every Warning;
  - each page's Index Lines with their final values and state (agreed, warned or confirmed).
- [x] It also answers "the Warnings this page and its neighbouring rows would have, were this line's values these", for the server's preview.
- [x] `answers.json` holds each page's size, book page and Index Lines: Line Number, band, crop, classification, line read, page read, the values parsed from Vision, the VLM answer, and the agreement state. The server needs no PDF.
- [x] `review.jsonl` is read with the formats in the spec:
  - `confirmed_line` and `unconfirmed_line` records keyed by page and band, the latest record for a band winning;
  - a Confirmed Line overrides the model's read and clears its disagreement and single-read Warnings;
  - the checks still run on its values.
- [x] No run writes `review.jsonl`.
- [x] The run also writes `pages/` for the server.

**Export**

- [x] The export writes:
  - `topics.json`: `{"topics": [{"id": "I", "title", "subtopics": [{"id": "I.1", "number", "title", "entries": ["A-8", …], "unresolved": [...]}]}]}`, with entries as `letters/*.json` anchors in printed order;
  - `topic-intro.md` and `compilers.md`, taken from `back-matter.md` with HTML comments and ⚠ markers stripped.
- [x] The export stops and lists every line with an open disagreement or single-read Warning.
- [x] The Parts' `letters/*.json` are unchanged.

**Docs and verification**

- [x] The new terms are added to the book's GLOSSARY.
- [x] An ADR records that number lines are read without the Vision hint, and why, since it reverses ADR 0005's use of the reads as hints.
- [ ] No automated tests. Verified by reasoning, then by a developer trial on `--pages 547-556,595-600` checking that:
  - every line is classified;
  - the stray dots on 547 and the `138,-139` on 548 cost nothing when the reads agree;
  - the row carried over onto 600 continues under its letter;
  - chủ đề I.1 assembles as printed in `topics.json`.

## Comments

- 2026-11-13: Implemented (uncommitted): `src/khotangtucngu/topics.py`, `topic_index.py`, `topic_export.py`, with edits to settings, pages, prompts, cli, export, vision_ocr and `submit.sh`; GLOSSARY terms and ADR 0007 added. Verified by reasoning only. The developer trial is still to run, and the last box stays open until it has: use `--pages 547-556,595-600`. Page 600 opens mid-row (the T row from 599), and 599 opens mid tiểu chủ đề 16, whose heading is at the foot of 595. Without 595-599 the lines continued onto 600 have no owner. Expect one no-owner Warning on tiểu chủ đề 16's heading, whose chủ đề lies on pages the trial skips.
