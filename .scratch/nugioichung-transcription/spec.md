Status: ready-for-agent

# Nữ Giới Chung: transcribe scanned Issues with the vLLM vision model

## Problem Statement

`vsc-project/NuGioiChung/So1_Feb1_1918.pdf` is Số 1 (1 February 1918) of _Nữ Giới Chung_, a Saigon weekly. It is 24 Letter-size pages, each a single bilevel (black-and-white, CCITT) scan at 2550×3300 px (300 dpi), with no text layer. More Issues will follow in the same folder, about 20 in all.

The pages are hard to read for a model:

- The print is old, faint and speckled, and handwritten Library Marks sit on top of it.
- Layouts vary from page to page:
  - page 1 is a masthead with price tables and a Table of Contents (Mục lục)
  - page 2 is mostly boxed Ads in mixed fonts, including French
  - page 6 has three dense columns and about 55 Footnotes in two columns at the foot
  - page 13 has Hán sayings, each with its phiên âm and translation
- Articles run on across columns and pages.
- The spelling is the 1918 one (Đờn-bà, sạch sẻ, hyphenated compounds), and it must be kept.

We want each Issue as readable, faithful text: every Item in reading order, each Article whole with its section, title, author and Footnotes. The developer must be able to check by eye what the model saw and what it answered. The existing book proofreader already sends page images to the vision model, but it is tied to the book pipeline in the vsc repo, which needs OCR drafts the newspaper doesn't have.

## Solution

A separate Nữ Giới Chung pipeline in this repo, with its own package and its own cluster job, reads an Issue PDF directly and runs the default model profile (sea-lion-v4.5-27b) with vision on, in two passes (ADR 0001 in the Nữ Giới Chung context):

1. **Layout pass.** The model sees each whole page, small, and returns its Regions in reading order. Each Region has a box, a kind, its Item's title and whether it continues the previous Region of that Item. Code moves the box edges onto the nearest column gap or printed rule.
2. **Transcription pass.** Each Region is cut from the full 300 dpi scan and transcribed as a Faithful Transcription. A Region taller than about a third of the page is cut into Strips at blank gaps between lines, with no overlap.

Code then joins the Regions into Items across columns and pages, pairs each Footnote with its call, and writes:

- the Issue as Markdown
- a datasheet-style CSV of its Articles
- each page with its Regions drawn, with a warning on any printed text outside every Region
- every request's exact image, prompt and answer
- one offline `inspect.html` that shows all of it side by side

The proofreader's general request code (retries, resumable runs, dry-run token counts, image messages) moves into a shared module that both pipelines use, and the proofreader works exactly as before.

## User Stories

1. As the developer, I want to run one cluster job per Issue PDF, so that a whole Issue is transcribed without any preparation step in another repo.
2. As the developer, I want the Issue number and date taken from the file name (e.g. `So1_Feb1_1918`), so that every Issue is labelled without me typing it.
3. As the developer, I want the pipeline to work for any Issue in the folder, with no code written specially for Số 1, so that the other Issues need no code changes.
4. As the developer, I want to pass a page range for a trial run, so that I can try a few hard pages (1, 2, 6, 13) before a whole Issue.
5. As the developer, I want a dry run that counts every request's prompt tokens with the model's own processor, images included, so that I know every request fits the context window before using the GPU.
6. As the developer, I want a run to continue in its own run folder and redo only the requests that failed or never ran, so that a timeout or crash doesn't waste finished work.
7. As the developer, I want the outputs rebuilt from all saved answers on every run, so that a continued run gives the same files as an uninterrupted one.
8. As the developer, I want saved answers reused only if they were made from the same input (same PDF, same page image settings, same prompts), so that changing a setting never mixes old and new answers.
9. As the developer, I want the code clearly separated as the Nữ Giới Chung project, so that it is never confused with resume scanning or the book proofreader.
10. As the developer, I want the default model profile used with vision turned on only for this job, so that the server setup is the same as the proofreader's.
11. As the developer, I want the layout pass to see the whole page in grayscale at about 1600 px on its long side, so that it sees the layout without spending tokens on detail it doesn't need.
12. As the developer, I want the layout pass run with thinking off, so that the model places its boxes on the scan instead of working them out in words as round figures that cut the text.
13. As the developer, I want each Region to come back with a box in thousandths of the page, a kind, its Item's title and a continuation flag, so that code can crop it and join Items.
14. As the developer, I want each Region's box edges moved onto the nearest column gap or printed rule (or, failing those, a gap speckled by the scan), then out by a small margin of blank paper that never crosses a rule, so that no crop cuts through a line of text or crops its outermost letters tight.
15. As the developer, I want the Footnotes printed under an Article returned as a Footnotes Region of that Article, so that they can be paired with their calls.
16. As the developer, I want printed text outside every Region found by code and flagged as ⚠ "text outside any Region", ignoring specks and page edges, so that a Region the layout pass missed doesn't silently disappear.
17. As the developer, I want each Region transcribed from the full 300 dpi scan, so that every diacritic is readable.
18. As the developer, I want a tall Region cut into Strips at blank gaps between lines, with no overlap, so that no request is too dense and no line is split or duplicated.
19. As the developer, I want each Strip to say whether it starts or ends mid-paragraph, so that code joins a paragraph cut by a Strip or Region boundary back into one.
20. As the developer, I want the transcription pass run with thinking off, so that plain copying doesn't spend tokens on reasoning.
21. As a reader, I want the 1918 spelling, hyphens, Hán characters and the paper's own typos copied exactly, so that the text is a faithful record of what was printed.
22. As a reader, I want handwritten Library Marks left out, so that the text holds only what the newspaper printed.
23. As a reader, I want every printed picture shown as a bare `[Hình]` placeholder with no description, so that I know a picture was there without reading the model's own words.
24. As a reader, I want price tables written as Markdown tables, so that their rows and prices stay lined up.
25. As a reader, I want the Table of Contents written as a nested list, so that its sections and their entries are clear.
26. As a reader, I want Hán sayings with their phiên âm and translation and poems to keep their printed line breaks, so that text that only makes sense line by line keeps its form; Ads are joined into sentences and paragraphs like Articles, a heading set over several lines joined into one.
27. As a reader, I want all other text joined into paragraphs, however many printed lines it takes, so that it reads as prose.
28. As a reader, I want every Item (Article, Ad, Notice, Table of Contents) transcribed and tagged by kind, so that I have the whole Issue and can filter out what I don't need.
29. As a reader, I want an Article that runs over several columns and pages joined into one Item in reading order, so that I read it whole.
30. As a reader, I want an Article that continues into the next Issue ("Còn tiếp" / "Tiếp theo") kept as a separate Article in each Issue, so that each Issue stands alone.
31. As a reader, I want each Footnote call "(n)" in an Article paired with Footnote n of the same Article and written as a Markdown footnote, so that notes sit with the text they explain.
32. As a reader, I want a Footnote call or Footnote that couldn't be paired marked ⚠, so that I can fix it by hand.
33. As a reader, I want the Issue as one Markdown file with a title line naming the newspaper, issue number and date, so that I can read it from top to bottom.
34. As a reader, I want each Item headed by its printed title, with a line under it giving kind, section, author and pages, so that I know what I'm reading and where it was printed.
35. As a reader, I want an Item with no printed title headed by its kind and page, so that untitled Ads and the price box still have a heading.
36. As the developer, I want each run to write a CSV with one row per Article, in the old datasheet's columns (Bài viết, Tác giả, Chuyên mục, Số báo, Ngày xuất bản, Nội dung) with Chủ đề left empty, so that new Issues line up with the 50 rows already typed.
37. As the developer, I want each page drawn with its Regions outlined and numbered, so that I can see at a glance whether the layout pass split it correctly.
38. As the developer, I want every request to save the image exactly as sent, its system and user prompt, its JSON answer and any reasoning, so that I can see precisely what the model saw and said.
39. As the developer, I want one `inspect.html` per run that opens offline and goes page → Regions → Strips, showing each request's image, prompt and answer side by side under the drawn page, so that I can check the whole Issue in a browser.
40. As the developer, I want a request that still fails after its retries to leave a visible ⚠ gap in its Item and an entry in a dropped log, so that missing text is never silent.
41. As the developer, I want a summary printed at the end of the run (requests by status, Regions, Strips, unpaired Footnotes, text outside any Region), so that I know where to look first.
42. As the developer, I want the book proofreader to keep working exactly as before after its request code moves to the shared module, so that the book pipeline is not affected.

## Implementation Decisions

- **Two contexts.** `GLOSSARY-MAP.md` at the root now lists Resume Scanning (root `GLOSSARY.md`) and Nữ Giới Chung (the Nữ Giới Chung package's own `GLOSSARY.md` and `docs/adr/`). Use its terms: Issue, Item (Article, Ad, Notice, Table of Contents), Region, Strip, Footnote, Library Mark, Faithful Transcription.
- **ADR.** Nữ Giới Chung ADR 0001: two-pass VLM with no OCR draft, and why whole-page requests and code-cut columns were rejected.
- **Shared request module (new, in providers).** The general parts of the proofreader's command-line script move here, unchanged in behaviour:
  - one request with retries (the first try at temperature 0, then the retry temperature; a context-length error stops retrying)
  - running a phase concurrently, which skips tasks whose saved result is ok and carries the same stamp
  - loading saved results by stamp
  - building image-plus-text chat messages
  - JSON writing
  - dry-run token counting with the model's processor

  It takes the phase settings (step name, max tokens, thinking) as arguments, not from a proofreader table. The proofreader imports it and keeps its own book logic.
- **Request saving.** The shared module saves each request's exact images and prompts as well as its result. The proofreader may keep its current result format, but Nữ Giới Chung needs, per task, the image(s) as sent (PNG), the system and user prompt text, and the answer and reasoning.
- **Nữ Giới Chung package (new), split by concern:**
  - **Command line:** arguments are the Issue PDF, `--run-dir`, `--pages`, `--pass layout|transcribe|all`, `--model-name`, `--vllm-url` and `--dry-run`. It wires the passes together and writes the outputs.
  - **Page images:** renders pages with PyMuPDF. The layout image is the whole page in grayscale at about 1600 px on its long side, antialiased by rendering. Crops are at full 300 dpi in grayscale. This module also has the bilevel image analysis: snapping box edges to column gaps and printed rules (or speckled gaps) with a blank margin, cutting Strips at blank line gaps, and finding ink outside every Region.
  - **Layout pass:** builds the prompt and JSON schema and checks the answer. Per page the answer is a list of Regions, each with a box `[left, top, right, bottom]` in thousandths, a kind (article text, Footnotes, Ad, Notice, Table of Contents), its Item's title as printed ("" if none), section and author when printed, and whether it continues the previous Region of the same Item. The order of the list is the reading order. The answer also gives the printed page number. Thinking off.
  - **Transcription pass:** builds the prompt and schema per Region or Strip, with the Faithful Transcription rules, `[Hình]` for pictures, Library Marks left out, tables and lists formatted, and printed line breaks kept for sayings and poems. The answer includes `starts_mid_paragraph` and `ends_mid_paragraph`. A Footnotes Region answers as a list of {number, text}. Thinking off. The schema forbids a run of more than three dots in any text, so a row of leader dots can't loop until the answer runs out of tokens.
  - **Assembly:** joins Strips into Regions and Regions into Items (by title and continuation flag, in reading order, across pages, never across Issues). It joins paragraphs broken at boundaries, pairs Footnote calls "(n)" with Footnote n within an Article, marks unpaired ones ⚠, and leaves ⚠ gaps for failed requests. It writes the Issue Markdown and the Article CSV.
  - **Inspection:** draws each page with numbered Regions and ⚠ for text outside any Region, and builds the offline `inspect.html` from the saved request files.
  - **Prompts:** the Nữ Giới Chung prompts and schemas, kept separate from the proofreader's.
- **Settings.** The Nữ Giới Chung constants (layout image size, crop dpi, Strip height threshold, max tokens per pass, retry temperature) live in the package, not the resume config.
- **Cluster job (new).** A Nữ Giới Chung submit script copied from the proofreader's: default profile, `serve_vision_on 1` (one image per request), its own concurrency, a dry-run mode on the login node, and token stats at the end.
- **Run folder.** `vsc-project/NuGioiChung/runs/<issue>/<time>/` holds:
  - the layout and transcription request folders (image, prompt, answer per task)
  - the drawn layout pages
  - the Issue Markdown and the Article CSV
  - the dropped log
  - `inspect.html`

  Saved answers are stamped with the PDF's hash, the image settings and a hash of the prompts.
- **Issue Markdown shape:**

  ```markdown
  # Nữ-Giới-Chung — Số 1, 1er Février 1918

  ## Thế-lực người đờn-bà
  *Article · Xã-thuyết · Lê-ái-Kiều · pages 4–6*

  … [^1] …

  [^1]: …

  ## Tủ sắt hiệu Werstaen
  *Ad · page 2*
  ```

- **Running headers and page numbers** are not transcribed. The printed page number is kept only to label the pages an Item is on.

## Testing Decisions

- No tests and no measurement script. The developer checks results by hand with `inspect.html`, the drawn layout pages and the Issue Markdown, starting with a `--pages` trial on pages 1, 2, 6 and 13 of Số 1.
- The implementer verifies by reasoning: the proofreader's behaviour is unchanged after the shared module is extracted, and every output is rebuilt from saved answers alone.
- The old datasheet's two Số 1 Articles ("Thế lực người đờn bà", "Cách ngôn") are a handy reference for the developer's own eye check, not a scored comparison.

## Out of Scope

- An OCR draft (Tesseract or Apple Vision) as a hint.
- Joining Articles across Issues.
- Describing pictures.
- Any OCR or parsing model other than the default profile, including PaddleOCR-VL (resume ADR 0009) and other dedicated OCR models.
- Assigning Chủ đề (topic).
- Feeding the output into the old chatbot or any RAG.
- A review or editing tool like the vsc repo's; the developer edits the Markdown directly if needed.
- Changing the book proofreader's behaviour.

## Further Notes

- Footnotes in this newspaper are numbered across an Article's pages (page 6 starts at (7) because page 5 holds (1)–(6)), and the calls are printed at normal size in parentheses. That's why pairing is done by code and the proofreader's note phase isn't needed.
- At 300 dpi a full page is roughly 8k image tokens for a Qwen3.x vision encoder, and a dense page's text would overrun the 4096-token page answer. Both point to per-Region requests.
- Research behind the two-pass approach: reports on VLM OCR of historical newsprint find uneven accuracy and repetition loops on dense full pages, and the best results come from segmenting into columns or regions first (Institutional Newspapers Pipeline, arXiv 2608.18972; BPL newspaper pipeline; Urdu newspaper OCR, arXiv 2505.13943).
- The private Issue PDFs stay in `vsc-project/`, as with the book and audio projects.
