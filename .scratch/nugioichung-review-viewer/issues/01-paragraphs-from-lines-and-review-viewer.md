# 01: Paragraphs from line geometry, and a review viewer

**What to build:** The whole spec (`.scratch/nugioichung-review-viewer/spec.md`) in one slice. Code finds each printed line of a Region or Strip on the scan and joins the lines into paragraphs from their geometry, and the unchanged Format request refines those paragraphs (Nữ Giới Chung ADR 0002). Every run folder then holds a stdlib-only `serve.py`. It shows the Issue's text on the left, each stretch highlighted on its page on the right, with every Warning boxed and explained. The developer resolves Warnings and makes Corrections there, and each one is appended to `review.jsonl` for later engine work. The viewer replaces `inspect.html` and the drawn pages.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

## Printed lines and paragraphs

- [x] Each Region or Strip's printed lines are found on the bilevel scan, each with a box. A band of tone marks much thinner than the Cut's median line is merged into its line. Thresholds are tuned on Số 1 and kept in the package's settings.
- [x] Printed lines are matched to Read lines in order only when the counts are equal. Otherwise there is a Warning "N printed lines found, M read" with the Cut's box, and the Cut falls back to today's joining: the hyphen rule, the model's `starts_mid_paragraph`/`ends_mid_paragraph`, and the Format request deciding the breaks.
- [x] On matched lines, code joins the paragraphs:
  - a new paragraph at an indented line, or after a line that stops short of the Cut's usual right edge
  - a centred line is a line of its own
  - every other line carries on, with a space, or with none after an end hyphen (the hyphen is kept)
  - the usual edges are the Cut's most common left and right ends
- [x] Across a Strip or Region boundary of one Item, a paragraph runs on when both Cuts are matched, this Cut's last line is not short and the next Cut's first line is not indented. When either Cut is unmatched, the model's flags decide, as today.
- [x] The Format request keeps its prompt rules, its letter check and its fallback. Its user text now gives the code-joined paragraphs, and says code joined them from the scan and they may be re-broken where the scan shows otherwise. When the Format answer isn't used, the fallback text is the code-joined paragraphs.
- [x] The formatted text is mapped back to printed lines by walking its letters (as the letter check counts them) against the Read lines' letters. Each stretch of text gets its page and line box, or the Cut's box when it is unmatched.

## Run folder outputs

- [x] `pages/pNN.png`: each page laid out, about 2000 px on its long side.
- [x] `viewer.json`:
  - the Issue's title
  - its Items in reading order (kind, title, section, author, pages, heading as in `issue.md`), each with its paragraphs and paired Footnotes, every stretch of text with its page and box
  - per page, its Regions (kind, box) and Strip cuts, and each Cut's request folders
  - every Warning, with a stable id (its kind and place), kind, reason, page, and box or none
- [x] The Warnings are everything `dropped.jsonl` holds today, plus line-count mismatches. `dropped.jsonl`, `inspect.html` and `layout/` are no longer written. `issue.md`, `articles.csv`, the request folders and `token_usage.jsonl` are written as before.
- [x] `serve.py` is copied into the run folder from a single master copy in the package. Everything above is rebuilt from saved answers on every run, and a run continued with `--run-dir` keeps its `review.jsonl`.
- [x] The CLI docstring and end-of-run summary describe the new outputs and point at `python3 serve.py`.

## Viewer

- [x] `python3 serve.py [--port 8000]` uses only the Python standard library. It serves its own folder and opens a browser tab with one HTML page (its HTML, CSS and JS in `web/`, copied with `serve.py`; no CDN) that loads `viewer.json`, `review.jsonl` and `pages/`.
- [x] Left: the Items in reading order, each Article's Footnotes under it. Right: the page, with each Region outlined faintly in its kind's colour and Strip cuts dashed.
- [x] Hovering a stretch of text highlights its line, and hovering a paragraph outlines all its lines. Clicking text brings its page into view, and clicking a box scrolls the text to it. Clicking a Footnote call jumps to its Footnote and highlights both.
- [x] Clicking a Region or Strip opens a drawer with its crop as sent, its prompts, its raw Read answer and its Format answer.
- [x] Every Warning is boxed in red on its page, with a card on the left giving its reason. A Warning with no box points at its whole page. A filter shows only unresolved Warnings.
- [x] Resolving a Warning takes a verdict and an optional note:
  - text outside any Region: not printed text, picture, or missed text with what it says
  - any other Warning: false alarm or real problem
- [x] A Correction is made in place on one paragraph, Footnote or table, as plain Markdown, with an optional note.
- [x] `POST /review` appends one timestamped JSON line per Resolution or Correction to `review.jsonl`:
  - a Resolution has the Warning's id, kind, reason, page, box, verdict, note, and what missed text says
  - a Correction has its Item, the paragraph, Footnote or table index, its pages, Cut keys and line boxes, the text before and after, and its note
- [x] When the viewer loads, `review.jsonl` is applied on top of `viewer.json`. A later line on the same Warning or paragraph replaces an earlier one. Corrections never change `issue.md` or `articles.csv`.
- [x] If the folder can't be written, the viewer is read-only and says so.

## Verification

- [x] No tests are added and nothing is opened in a browser. The implementer verifies by reasoning. The developer checks by hand on a Số 1 `--pages` trial (pages 1, 2, 6, 13 and the "XE MÁY HIỆU LA SEMEUSE ET LE DRAGON" Ad page).
