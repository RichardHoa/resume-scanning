# 01: Shared request module and a rough first version of the full pipeline

**What to build:** Move the book proofreader's request code into a shared module, then build a rough version of the whole Nữ Giới Chung pipeline on top of it, so the developer can run a `--pages` trial on the cluster and check by eye what the model saw and answered.

Every pass runs, but in a simple form:

- The layout pass returns the Regions of each page.
- Each Region is cropped from the full 300 dpi scan and transcribed whole, with no Strips yet.
- Code joins the Regions into Items in reading order and writes the Issue Markdown.
- Every request is saved, and each run writes the drawn layout pages and an offline `inspect.html`.

Box snapping, Strips, Footnote pairing, the outside-text check and the CSV come in ticket 02.

See the spec (`.scratch/nugioichung-transcription/spec.md`), the Nữ Giới Chung glossary, and Nữ Giới Chung ADR 0001.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [x] The proofreader's general request code moves, unchanged in behaviour, to a shared module in providers: one request with retries, a concurrent phase that skips saved ok results with the same stamp, loading results by stamp, image-plus-text messages, JSON writing, and dry-run token counting. Phase settings (step, max tokens, thinking) come in as arguments. The proofreader imports it and behaves exactly as before: same files, same resume, same dry run.
- [x] The shared module can also save each request's exact image(s) (PNG, as sent), system and user prompt, and answer and reasoning, per task.
- [x] A separate Nữ Giới Chung package exists, split by concern: command line, page images, layout pass, transcription pass, assembly, inspection, prompts. It has its own settings (layout image size, crop dpi, max tokens per pass, retry temperature) and imports nothing from the proofreader or the resume pipeline.
- [x] A Nữ Giới Chung cluster job, copied from the proofreader's, runs the default profile with `serve_vision_on 1`, has a login-node dry run, and prints token stats at the end.
- [x] The command line takes the Issue PDF, `--run-dir`, `--pages`, `--pass layout|transcribe|all`, `--model-name`, `--vllm-url` and `--dry-run`. The Issue number and date come from the file name (e.g. `So1_Feb1_1918`).
- [x] The run folder is `vsc-project/NuGioiChung/runs/<issue>/<time>/`, unless `--run-dir` names another. A continued run redoes only failed or missing requests. Saved answers are stamped with the PDF's hash, the image settings and a hash of the prompts. All outputs are rebuilt from the saved answers on every run.
- [x] Layout pass:
  - Input: the whole page rendered in grayscale at about 1600 px on its long side, with thinking on.
  - Output per Region: a box in thousandths, a kind (article text, Footnotes, Ad, Notice, Table of Contents), its Item's title ("" if none), section and author when printed, and a "continues the previous Region of this Item" flag. The order of the list is the reading order.
  - Output per page: the printed page number.
  - Library Marks are never Regions.
- [x] Transcription pass:
  - Input: each Region cropped from the 300 dpi render in grayscale and sent whole, with thinking off.
  - The prompt enforces Faithful Transcription: 1918 spelling, hyphens, Hán characters and typos exactly as printed, Library Marks left out, a bare `[Hình]` for a picture, price tables as Markdown tables, the Table of Contents as a nested list, and printed line breaks kept for Hán sayings with phiên âm and translation, poems and Ad lines. All other text is joined into paragraphs.
  - The answer includes `starts_mid_paragraph` and `ends_mid_paragraph`.
- [x] Assembly joins Regions into Items across columns and pages by title and continuation flag in reading order, never across Issues. It writes `issue.md`:
  - a title line naming the newspaper, Issue number and date
  - one `##` heading per Item with its printed title, or its kind and page if it has none
  - under each heading, a line giving kind, section, author and pages
  - running headers and page numbers are not transcribed
  - a Region whose request failed leaves a visible ⚠ gap in its Item.
- [x] Each page is drawn as `layout/pNN.png` with its Regions outlined and numbered.
- [x] `inspect.html` opens offline with no server. It goes page → Regions, showing the drawn page, then each request's image as sent, its prompt and its answer side by side.
- [ ] `--dry-run` counts every layout and transcription request's prompt tokens with the model's processor and reports any that would not fit the context window.

## Comments

- 2026-10-27: `--dry-run` counts every layout request, but transcription requests only for pages that already have a saved layout answer, since the Regions come from the layout pass. A fresh dry run therefore counts no transcription requests; point `--run-dir` at a run with layouts to count them.
