# 02: Review server for the Topic Index

**What to build:** The developer runs `python3 serve.py` in the section's store (`store/part-4-final-section/`), on any machine, with nothing installed and no PDF.

They work through the Warnings of the Topic Index scan, seeing each Index Line's crop with its three reads. They confirm or correct only the lines that need it, and the export then accepts those lines.

The server writes `review.jsonl` and nothing else, and rebuilds everything it shows with the rebuild ticket 01 copies into the store.

Full design: `.scratch/kho-tang-tuc-ngu-topics/spec.md`. It follows the conventions of the Parts' review server (`serve.py`), which it sits beside, not inside.

**Blocked by:** 01 (Scan, check and export the Topic Index). This server only shows and edits what 01's run writes: `answers.json`, `entry_names.json`, `pages/` and the rebuild with its preview, as pinned in 01's "contract with ticket 02". It can't be built or tried without them.

**Status:** done

**Server**

- [x] The server uses the standard library only. `cli.py` copies it and its web page into the section's store on every run, as it does `serve.py` and `web/` into a Part's store.
- [x] `GET /assembled`: the pages, each page's Index Lines with their final values and state, the assembled topics, and every Warning, rebuilt from `answers.json` with the review log.
- [x] `POST /preview` with `{"page", "band", values}`: the Warnings that page and its neighbouring rows would have with those values, raised whether or not the line is already confirmed.
- [x] `POST /review`:
  - `{"type": "confirmed_line", "page", "band", values}`: values may be null to confirm the line as it stands. It appends the whole Confirmed Line with its time, PDF hash, the model's values and `edited`.
  - `{"type": "unconfirmed_line", "page", "band"}`: undoes it.
  - Bad input is refused with a reason, as `serve.py` refuses a bad band or bad Blocks.
- [x] Nothing in the store but `review.jsonl` is ever written. It is never rewritten.
- [x] The page is read-only, and says so, when the store can't be written.

**The page**

- [x] The page's scan, with each Index Line tinted agreed, warned or confirmed.
- [x] Beside it, that page's assembled index: chủ đề, tiểu chủ đề, Topic Rows and their numbers. A row carried over from the page before shows its letter.
- [x] A Warning list across all pages, grouped by kind. Disagreements and single reads come first. Each one jumps to its page and line.
- [x] A line panel with:
  - the line's crop, its line read and page read, and the VLM's read, with the numbers they differ on marked;
  - an editor for its letter, numbers or heading text, whose Warnings update from `/preview` before saving;
  - confirm, and undo for a Confirmed Line.
- [x] Moving between pages and to the next open Warning by keyboard, so long stretches of numbers can be reviewed quickly.

**Verification**

- [ ] No automated tests. Verified by reasoning, then by the developer on 01's trial store (`--pages 547-556,595-600`), checking that:
  - a disagreeing line can be corrected, its Warning clears, and the change shows in `topics.json` after the next run or export;
  - undoing a Confirmed Line puts the model's read back;
  - a correction that breaks the ascending order or names no Proverb Entry shows that Warning in the preview.

## Comments

- 2026-11-13: Implemented (uncommitted): `src/khotangtucngu/topic_serve.py` and `topic_web/` (index.html, style.css, app.js), which `topic_index.py` copies into the section's store as `serve.py` and `web/` on every run. `topics._values` is now public as `normal_values` for the server. Values travel in requests as `"values": {"kind", "letter", "numbers", "text"}`. Keys: ←/→ page, ↑/↓ (j/k) line, n/N next/previous open Warning, w the Warning list, c confirm and go on, e edit, u undo, Enter save, Esc cancel. Verified by reasoning only. The developer trial is still to run on 01's trial store (`--pages 547-556,595-600`, as 01's comment says), and the Verification box stays open until it has.
