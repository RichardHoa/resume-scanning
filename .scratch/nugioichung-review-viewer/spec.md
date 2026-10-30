Status: ready-for-agent

# Nữ Giới Chung: paragraphs from line geometry, and a review viewer

## Problem Statement

Checking a transcribed Issue is slow. `inspect.html` shows each request's crop, prompt and answer, but not the Issue's text next to the place on the page it came from, so the developer can't read the transcription and check it against the print at the same time. Warnings (text outside any Region, unpaired Footnotes, unused Format answers...) are scattered between the drawn pages and `dropped.jsonl`, with no way to record what each one turned out to be. A wrong letter or a wrong paragraph break found by eye is fixed nowhere: there is no record the engine can be improved from.

Paragraphs are also still wrong. An Ad from Số 1 came out with every printed line kept:

```
Bởi vậy cho nên trong Lục-
Châu chư quân-tử nếu muốn đi
cho mau, về cho chóng thì nên
sắm xe máy đạp mà dùng.
```

The model's Read lines carry no position, so nothing in the pipeline knows where a printed line starts or stops, which is what shows a paragraph break on the page (an indent, a line that stops short, a centred line).

## Solution

1. **Printed lines from the scan** (Nữ Giới Chung ADR 0002). Code finds each printed line of a Region or Strip on the bilevel scan and matches them in order to the Read lines. Each line then has a box.
2. **Paragraphs joined by code, refined by the model.** Code joins the matched lines into paragraphs from their geometry, also across Strip and Region boundaries. The Format request stays as it is (whole text as Markdown, letters checked by code), but is given these paragraphs instead of the raw lines.
3. **A review viewer in every run folder.** A stdlib-only `serve.py` shows the Issue's text on the left and the page on the right, each line of text highlighted on the page, with every Warning boxed and explained. The developer resolves Warnings and corrects text there, and each Resolution and Correction is appended to `review.jsonl`, which is read later to improve the engine.

The viewer replaces `inspect.html` and the drawn pages.

## User Stories

1. As the developer, I want each printed line of a Region or Strip found on the scan, with its top, bottom, left and right, so that the text can be laid out and highlighted by where it is printed.
2. As the developer, I want the printed lines matched in order to the Read lines, and a Warning when their counts differ, so that a mismatch never silently puts a box on the wrong text.
3. As a reader, I want a new paragraph where a line is indented or the line before stops short, so that paragraphs follow the print.
4. As a reader, I want a centred line (an Ad's shop name, a slogan, a heading) kept on a line of its own, so that it isn't run into the sentence after it.
5. As a reader, I want every other printed line joined to the one before with a space, or with no space after an end hyphen, so that sentences read whole.
6. As the developer, I want whether a paragraph runs on across a Strip or Region boundary decided from the scan (the next Cut's first line not indented, and this Cut's last line reaching its right edge), with the model's `starts_mid_paragraph`/`ends_mid_paragraph` used only when the lines could not be matched, so that boundaries join correctly.
7. As the developer, I want the Format request given the code-joined paragraphs instead of the raw lines, so that it only corrects the breaks it disagrees with and adds the Markdown.
8. As the developer, I want a Region or Strip whose lines couldn't be matched to fall back to today's joining (hyphen rule, model flags, Format deciding the breaks), so that it is still transcribed.
9. As the developer, I want to start the viewer with `python3 serve.py` inside a run folder copied to any machine, with nothing to install, so that I can check a run off the cluster.
10. As the developer, I want the Issue's Items on the left in reading order, each headed as in `issue.md`, and the page on the right, so that I read the text against the print.
11. As the developer, I want hovering a stretch of a paragraph to highlight its printed line on the page, and hovering the paragraph to outline all its lines, so that I see exactly where each part came from.
12. As the developer, I want clicking a box on the page to scroll the text to it, and clicking text to bring its page into view, so that I can go either way.
13. As the developer, I want a Region or Strip whose lines couldn't be matched highlighted as a whole, so that it still links to its text.
14. As the developer, I want each Region outlined faintly in its kind's colour and its Strip cuts dashed, so that I still see the layout pass's split.
15. As the developer, I want clicking a Region or Strip to open a drawer with its crop as sent, its prompts, its raw Read answer and its Format answer, so that I see what the model saw and said without `inspect.html`.
16. As the developer, I want each Article's Footnotes under it, and clicking a call to jump to its Footnote and highlight both on the page, so that I can check the pairing.
17. As the developer, I want every Warning boxed in red on its page with a card on the left giving its reason, so that I know what to look at and why. A Warning with no narrower place points at its whole page.
18. As the developer, I want to resolve a Warning with a verdict and an optional note (text outside any Region: not printed text, picture, or missed text with what it says; any other: false alarm or real problem), so that what each one turned out to be is recorded.
19. As the developer, I want to correct one paragraph (or one Footnote, or one table) in place as plain Markdown, with an optional note on why, so that wrong letters and wrong breaks are recorded where they are.
20. As the developer, I want each Resolution and Correction appended to `review.jsonl` in the run folder, so that it can be read later to improve the engine.
21. As the developer, I want the viewer to show my earlier Resolutions and Corrections when it opens, a later one on the same place replacing the earlier, so that I can stop and pick up a review.
22. As the developer, I want to filter to unresolved Warnings, so that I can work through them.

## Implementation Decisions

- **Glossary.** New terms in the Nữ Giới Chung `GLOSSARY.md`: Warning, Resolution, Correction. "Cut" stays the code's name for a Region whole or one of its Strips.
- **ADR.** Nữ Giới Chung ADR 0002: paragraph breaks from the scan's line geometry, refined by the unchanged Format request; the Format edit-list alternative rejected for now.
- **Finding printed lines (page images module).** Inside a Cut's box, the row ink profile's runs of ink between blank gaps are its printed lines. A run much thinner than the Cut's median line (a row of tone marks above capitals) is merged into the line it sits on. Each line's box is its rows and the leftmost and rightmost ink in them. Thresholds tuned on Số 1.
- **Matching.** Printed lines are matched to Read lines in order only when their counts are equal; otherwise the Cut gets a Warning "N printed lines found, M read" and the fallback. `[Hình]` lines take part in the count as one line each only if the scan analysis can tell a picture (else the count is expected to differ and falls back).
- **Joining rules** (on matched lines; thresholds tuned on Số 1, in the package's settings):
  - new paragraph: the line's left end is more than about 1.5 letter-widths (median line height as the letter-width measure) right of the Cut's usual left edge;
  - new paragraph after a line whose right end is more than about 15% of the Cut's width short of its usual right edge;
  - a centred line (both margins large) is a line of its own;
  - otherwise carried on, with a space, or none after an end hyphen (the hyphen kept).
  The usual edges are the Cut's most common left and right ends, so an indented first line doesn't move them.
- **Boundaries.** Across Strips and Regions of one Item, a paragraph runs on when this Cut's last line is not short and the next Cut's first line is not indented, both matched; otherwise the model's flags, as today.
- **Format request.** Same prompt rules and letter check; its user text gives the code-joined paragraphs, one per line with blank lines between, and says code joined them from the scan and they may be re-broken where the scan shows otherwise. Its stamp already covers the user text, so changed paragraphs are formatted again. The fallback text when the Format answer is not used is the code-joined paragraphs.
- **Text to line mapping.** Walk the formatted text's letters (as the letter check counts them) against the Read lines' letters: each stretch of formatted text gets the Read line, and so the printed line box, its letters came from. Text from the fallback maps directly.
- **Outputs (run folder).**
  - `pages/pNN.png`: each page at about 2000 px on its long side, rendered by the CLI.
  - `viewer.json`: the Issue (title), its Items in reading order (kind, title, section, author, pages, heading as in `issue.md`), each Item's paragraphs and Footnotes with, per stretch of text, its page and line box (or Cut box), the Regions and Strip cuts per page with their kinds, each Cut's request folders, and every Warning (id, kind, reason, page, box or none).
  - `serve.py`: copied from the package's single master file at output time.
  - `issue.md`, `articles.csv`, the request folders and `token_usage.jsonl` as today. `inspect.html` and `layout/` are no longer written. `dropped.jsonl` is replaced by the Warnings in `viewer.json`.
- **Warnings.** Everything `dropped.jsonl` holds today (pages with no layout, Regions left out, requests with no transcription, Format answers not used, unpaired Footnotes and calls, text outside any Region), plus line-count mismatches. Each has a stable id within the run (its kind and place), so a Resolution names it.
- **Server (`serve.py`).** Python standard library only (`http.server`, `json`, `webbrowser`). `python3 serve.py [--port 8000]` serves its own folder, opens a browser tab, and serves one HTML page (its HTML, CSS and JS in `web/`, copied with `serve.py`; no CDN) that loads `viewer.json`, `review.jsonl` and `pages/`. `POST /review` appends one JSON line to `review.jsonl`. If the folder can't be written it serves read-only and the page says so.
- **`review.jsonl`.** One line per action, with a timestamp:
  - Resolution: Warning id, kind, reason, page, box, verdict, note, and for missed text what it says.
  - Correction: Item, paragraph (or Footnote/table) index, page(s), Cut keys, line boxes, the text before, the text after, note.
  A later line on the same Warning or paragraph replaces an earlier one when the viewer loads. Corrections never change `issue.md` or `articles.csv`. A rerun makes a new run folder with no `review.jsonl`.

## Testing Decisions

- No tests and no new test seams, by the developer's standing instruction for this repo. The developer checks by hand with the viewer on a `--pages` trial of Số 1 (pages 1, 2, 6, 13, and the Ad page with "XE MÁY HIỆU LA SEMEUSE ET LE DRAGON"). The implementer verifies by reasoning, and does not open the viewer in a browser.
- If tests are ever wanted, the one seam is the CLI's output: given a run folder's saved answers, the `viewer.json` it rebuilds (line boxes, paragraphs, Warnings). Everything else follows from it.

## Out of Scope

- A Format request that returns an edit list (ADR 0002).
- Writing Corrections back into `issue.md`/`articles.csv` or a corrected export.
- Carrying a review over to a new run.
- Drawing a missing Region in the viewer or rerunning a request from it.
- Any dependency beyond the Python standard library for `serve.py`.

## Further Notes

- The Ad sample in the Problem Statement came from a run made before the Read/Format split, whose code joining already joins most printed line breaks. This spec is about making paragraph breaks follow the print, not about lines left unjoined.
- Two defaults were set without the developer's ruling and may be revisited on the Số 1 trial: a band of tone marks thinner than a line is merged into its line, and a `[Hình]` counts as a printed line only if the scan analysis can tell a picture (otherwise the Region or Strip takes the fallback, with no line highlighting).
- Old runs need no migration: they keep `inspect.html` and are never opened by the viewer.
- Everything the viewer shows is rebuilt from saved answers on every run, as the original spec requires, so continuing a run with `--run-dir` refreshes `viewer.json` and the page images but keeps `review.jsonl`.
