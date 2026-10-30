# 02: Review server: scan beside the transcription, checks and Fixes

**What to build:** In a PDF Part's store, the developer runs `python3 serve.py`, on any machine with nothing to install, and reviews the transcription page by page. Each page's scan is on the left and its Proverb Entries on the right, as transcribed, with the page's Warnings beside them. The developer marks entries as checked and saves a Fix where the model got something wrong, and the review survives reruns. Spec: `../spec.md`. The Nữ Giới Chung review viewer is prior art.

- The right side shows the verbatim layer: proverb, Citations, Variants with their italics, notes, Corrections and See-also names, laid out so each lines up by eye with the print.
- The developer can move between pages and jump to the next page with Warnings, or with entries not yet checked.
- A check or a Fix is appended to the store's review log. No run rebuilds or deletes the log.
- A Fix is a full replacement Proverb Entry, edited in the page, with the hash of the page answer it was made against.
- When that page's answer changes after a rerun, the Fix is shown as stale and is not counted as applied until the developer saves it again or drops it.
- The server is copied into the store with the other outputs, as Nữ Giới Chung's is.

**Blocked by:** 01

**Status:** ready-for-agent

- [ ] `python3 serve.py` in the store serves the review page with only the standard library
- [ ] Each page shows its scan on the left and its Proverb Entries on the right, with italics shown
- [ ] An entry running over a page break appears whole, and can be reached from both of its pages
- [ ] Each page's Warnings are shown beside it, and "next page with Warnings" jumps there
- [ ] Marking an entry as checked appends to the review log and survives a server restart
- [ ] Saving a Fix appends it to the review log; reloading shows the Fix in place of the model's entry
- [ ] After a rerun that changes the page's answer, its Fix is shown as stale
- [ ] A new run does not touch the review log

## Comments

- From 03 (export): `review_fixes` in `src/khotangtucngu/export.py` reads the Fixes of `<store>/review.jsonl` in the shape `serve.py`'s docstring defines (`{"type": "fix", "name", "answer_sha1": {PDF page: hash}, "entry"}`, `"entry": null` to drop; a later record on the same name replaces an earlier one). It ignores checks. Note: `web/app.js` currently writes a different shape (`entry`/`fixed`/`answers` and `type: "drop"`), which `serve.py`'s validator would reject; it needs to match the docstring.
