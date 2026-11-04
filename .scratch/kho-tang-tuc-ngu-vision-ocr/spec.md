Status: ready-for-agent

# Kho tàng tục ngữ người Việt: Apple Vision reads every page on a Mac, and the model's edits to agreed words are marked

Written 2026-11-04. Replaces the VietOCR spec (`kho-tang-tuc-ngu-vietocr`) and puts ADR 0004's model choice into the pipeline. The Hint + Warnings design of ADR 0002 stands. Vocabulary: the book's GLOSSARY, plus the new terms under "Docs".

## Problem Statement

The OCR Readings come from VietOCR, which reads this book far worse than Apple Vision does. Vision runs only on macOS, and the model runs on the SLURM GPU, so the OCR can't stay a phase inside the CLI's process.

Neither reader can be trusted alone. On 9 pages (1,125 words of proverb and note text), a Vision read of each line and a Vision read of the whole page agreed against the model's answer on 22 words. The scan supports Vision on 18 (*cởi truồng*, not *cỏi trường*; *thi bơi*, not *thì bơi*; *cưỡng*, not *cuống*), the model on 3 (*tàn*, *phấn*, *hủi*), and neither on 1 (*Ă*). So the model must be free to overrule the OCR, but today the developer can't tell where it overruled two reads that agreed, and those are exactly the words worth checking. Nobody checks every Proverb Entry, so an unmarked wrong change stays in the book.

## Solution

Two machines, with the store as the hand-over, and a small batch first:

1. **On the Mac, one command:** `python3 -m src.khotangtucngu.vision_ocr --part-1 --pages 36-45,420-424`. With no `--pages` it reads every proverb page of the Part. From the Part's PDF it finds each page's printed lines, reads every line and the whole page with Vision, compares the two reads, and saves the results into the Part's store. About 18 minutes for all 830 pages.
2. **Copy across:** `rsync` the Mac's output to the cluster. The command prints the line to run and transfers nothing itself.
3. **On the cluster, the job as today**, with the same `--pages`. The model is the final judge: it makes the Blocks and may spell any word as the scan prints it, including words the two reads agree on.
4. **Marking:** where the model's Blocks differ from an Agreed Syllable, code keeps the model's text and raises a **Model Edit** Warning naming both spellings. The developer goes through these in the review server with its existing next-Warning button.

## User Stories

### Running the OCR on the Mac

1. As the developer, I want one command that reads a PDF Part with Vision, so that I don't crop pages or call Vision by hand.
2. As the developer, I want the command to take `--pages` in the CLI's form (`36-45,420-424`), so that I can test a small batch before the whole Part.
3. As the developer, I want no `--pages` to mean every proverb page of the Part, so that the full run is the same command with the flag left off.
4. As the developer, I want runs over different pages to add up in the store, so that a trial's reads count towards the full run.
5. As the developer, I want a rerun to skip pages that already have a current read, so that an interrupted run carries on.
6. As the developer, I want a page Vision fails on to be saved as failed while the run continues, so that one bad page doesn't stop the batch.
7. As the developer, I want a page named in `--pages` to be read again only if its read is missing, failed or out of date, so that a repeated trial costs nothing.
8. As the developer, I want a clear message if the command runs off macOS or the PDF is missing, so that I don't debug a confusing failure.
9. As the developer, I want a summary of pages read, pages failed and the share of Disputed Syllables, so that I can judge a batch at once.
10. As the developer, I want the command to print the `rsync` line for what it wrote, so that I don't work out the paths.
11. As the developer, I want the Mac's dependencies in their own requirements file at the repo's pinned versions, so that I don't install the GPU stack on a laptop.
12. As the developer, I want Vision's macOS version and revision in the stamp, so that a read from another OS isn't taken for the same read.

### Handing over to the cluster

13. As the developer, I want the cluster to use the Mac's printed lines, so that Line Numbers and crop boxes can't differ between machines.
14. As the developer, I want the job to stop before any request if a page in this run has no current read, naming those pages, so that no GPU time goes on a page that can't finish.
15. As the developer, I want a job over a small batch to need reads for that batch only, so that trials don't need the whole Part read.
16. As the developer, I want the transfer to leave the review log alone, so that a transfer can't lose my Fixes.
17. As the developer, I want VietOCR gone from the job and the requirements, so that the job has no dead OCR phase or weights download.

### The model as final judge

18. As the developer, I want the model to see each line's two reads with Disputed Syllables marked, so that it knows where to look hardest.
19. As the developer, I want the model free to change an Agreed Syllable when the scan clearly prints otherwise, so that an error both reads share can be fixed.
20. As the developer, I want the prompt to say a change must follow the scan and never what a word ought to be, so that the model corrects its way into fewer wrong words like *cuống*.
21. As the developer, I want the model's Blocks kept as it wrote them, so that its judgement decides the text until I fix it.
22. As the developer, I want garbled Source Abbreviations and numbers in the reads not to steer the model, so that Citations, See-alsos and proverb numbers still come from the scan.

### Marks on the model's edits

23. As the developer, I want each change to an Agreed Syllable marked as a Model Edit Warning, so that I can find them without reading every entry.
24. As the developer, I want the Warning to name the entry, the model's spelling and the reads' spelling, so that I can judge it against the scan.
25. As the developer, I want changed letters marked as well as changed tone marks, so that a swapped word can't pass unmarked.
26. As the developer, I want a word the model added or dropped marked too, so that a changed sentence can't pass unmarked.
27. As the developer, I want marks only on proverb, Variant, note and Correction text, so that Citations and See-alsos, which the reads garble, don't bury the real edits.
28. As the developer, I want a Model Edit and a Diacritic Disagreement never raised for the same syllable, so that one word gets one Warning.
29. As the developer, I want repeats of one edit in one entry shown once with a count, as Diacritic Disagreements are, so that the list stays short.
30. As the developer, I want a Fix that restores the reads' spelling to clear its mark, so that the Warnings show what's still open.
31. As the developer, I want the marks rebuilt whenever a page is shown or previewed, so that they stay true while I edit.
32. As the developer, I want Model Edits to have their own name in the review page, so that I can tell them from other Warnings.
33. As the developer, I want a count of Model Edits at the end of a run, so that I can see how often the model overrules the reads.

## Implementation Decisions

### The Mac command

- **New `vision_ocr` module:** the command, with the CLI's `--part-<n>` and `--pages` flags, the same page parsing and the same default. It imports nothing GPU-bound or from vLLM: only the page finder, the settings and the JSON and hash helpers. If the shared helpers' module drags in more than the standard library and the core config, move what it needs.
- **New Swift Vision reader,** compiled with `swiftc -O` into a temporary folder at the start of a run. One process lives for the whole run, so Vision's model loads once (about 30 s). It takes an image path per line on stdin and answers one JSON line per image: each observation's text, box and confidence, or an error. A failed read never crashes it.
- **Vision settings:** `VNRecognizeTextRequest`, accurate level, revision 3 set explicitly, language `vi-VT`, language correction off (the book's own spelling is what we copy, and correction made no difference in the trial), and the default compute device. That device can fail under the Claude Code sandbox (ADR 0004), so the developer runs the command in their own terminal.
- **The two reads of a page:**
  - **OCR Reading (each line):** the existing line crop at the 300 dpi `PAGE_DPI`, on white with 45 px of padding on every side. Every line is read, because the Mac doesn't know the layout yet. A line's reading is its observations joined left to right.
  - **Page Reading (whole page):** the page in grayscale at 400 dpi. Each observation goes to the line whose band holds the centre of its box, scaled to 300 dpi. Observations on one line are joined left to right. One matching no line, or spanning two, is saved as unmatched and otherwise unused.
- **What it saves,** per page, in the Part's store:
  - the printed lines, as the CLI saves them now;
  - a Vision record: the PDF's hash, the stamp (macOS version, Vision revision, language, correction flag, both DPIs, the pad), status, error, each Line Number's box and two reads, and the unmatched observations.
- **Reruns:** a page with a current record is skipped. A newer macOS changes the stamp and rereads every page, and any Entry Span whose readings change is requested again. That is intended.
- **Dependencies:** a new macOS requirements file beside the audio one, with `pymupdf`, `numpy`, `scipy` and `pillow` at the versions the main file pins. The developer installs it; no script installs anything.

### Comparing the two reads

- **Per line:** the two reads are cut into syllables as the diacritics module does (lowercase, NFC) and lined up exactly with `difflib`.
  - **Agreed Syllable:** in an `equal` stretch, and made only of letters of the Vietnamese alphabet. So no digits, and nothing like *хó* with a Cyrillic letter (seen in the trial).
  - **Disputed Syllable:** every other syllable of a line with both reads.
  - A line with no Page Reading has neither, and is treated as one read.
- **What the model gets:** the user text still gives readings by Line Number, with each Disputed Syllable showing both reads, line read first: `L12: Ai chết trước thì được [mồ|mô] mả.` A stretch where the reads have different numbers of syllables is marked whole: `[VC I 10|VC110]`. A line with one read is written `L12 (one read):`.
- **Span prompt:** the paragraph on OCR Readings becomes: two reads of each line are given, and they are a hint; for each `[a|b]`, look at the scan and spell what it prints, which may be neither; unmarked words were read the same both times and are usually right, but both reads can be wrong, so change one only where the scan clearly prints otherwise, never for what a word ought to be; every such change is shown to the developer; the reads know nothing of Blocks or italics and garble Source Abbreviations and numbers, so those come from the scan.

### Marking Model Edits

- **Where:** in the diacritics module, beside `disagreements`, using the same lining up by bare letters of a page's Blocks (text, then Citations) with its joined OCR Readings. `assemble` raises the Warnings, so the CLI's run and the review server's rebuild and preview all get them, and a Fix is checked like any other Blocks.
- **New input:** `assemble`, `rebuild` and the review server also take each page's readings with their Agreed Syllables flagged, from a new store file beside `readings.json`, which keeps its form. Like `readings.json`, it's rebuilt each run from the saved reads. The modules stay standard-library only, as they are copied into the store.
- **The rule,** for syllables of a `proverb`, `variant`, `note` or `correction` Block's text only:
  - lined up with an Agreed Syllable, same bare letters, different marks: Model Edit;
  - paired one-to-one with an Agreed Syllable in a `replace` stretch of equal length: Model Edit;
  - an Agreed Syllable the Blocks dropped, or a syllable the Blocks added with no read behind it: Model Edit, worded as dropped or added. The labels the Blocks never hold (`BK`, `bk`, `Xem thêm`, `Sửa lại`, entry numbers) don't count as dropped.
- **Warning kind** `model_edit`, with the place and counts of `_diacritic_warnings`. Reason: `A 7: the model wrote "cuống" where both reads have "cưỡng"`. The review page gets a name for the kind.
- **Diacritic Disagreements** remain for syllables that are not Agreed, so one syllable never raises both.
- **Text is never changed by this step:** the answers hold the model's Blocks exactly.

### The cluster

- **CLI:** it stops finding lines and reads the Mac's. Before any request, it exits naming any page of this run that is missing, failed or made from another PDF. `--dry-run` needs the lines too. Pages outside this run are treated as now, so a small batch runs alone. OCR Readings come from the Vision records, each line's box checked against its crop.
- **Removed:** the VietOCR module, its requirement, its settings, the store's OCR folder and its debug images. `line_box`'s settings stay. The settings, prompts, CLI docstring and job script stop naming VietOCR. GPU memory utilisation stays 0.85.
- **Transfer:** only the lines and the Vision records, never the review log.
- **End of a run:** the existing Warning counts by kind show the Model Edits.

### Docs

- **New ADR 0005:** two reads, and Model Edits marked rather than locked, with the hard lock as a rejected option because both reads can be wrong together. It answers ADR 0002's "until the two are compared on fixed pages": the comparison shows neither side can be trusted to replace the other.
- **GLOSSARY:** add **Page Reading**, **Agreed Syllable**, **Disputed Syllable** and **Model Edit**; update **OCR Reading** for the Mac and the two reads.
- **README:** the book's section gets the Mac step, `--pages` for a first batch, the transfer and the new store files, and loses its stale store rows.

## Testing Decisions

- **No tests or browser checks are added,** per the project's rule; the code is verified by reasoning.
- **The developer's check is the whole pipeline on a small batch,** the highest seam there is:
  1. Run the Mac command with `--pages 36-45,420-424`, then the job with the same pages.
  2. See that every page passes the job's early check.
  3. Compare the disputed share with the trial's figure of about 2.5%.
  4. Read every Model Edit on those pages against the scan: how many are right, and how many are false marks from lining up?
- **Prior art:** the same check was used for ADR 0004's trial, and these pages hold the known hard words above.

## Out of Scope

- Having the command transfer anything or submit the job.
- Overwriting or rejecting the model's text: no lock of any kind.
- Showing marks inside the proverb's text, or carrying them into the export or the website. The mark is a Warning.
- Dismissing a Model Edit: a Fix that keeps the model's spelling keeps its mark, as with Diacritic Disagreements.
- Fixing Citations from OCR: reading volume numbers (*VC I 9*→*VC19*) stays open as in ADR 0004.
- Taking entry numbers from OCR: Vision found only about 70% (36 of 50 on the page, 35 of 50 cropped alone). The layout request and the number Warnings keep them.
- A third reader, or using Vision's confidence, which has three values and scores clear errors at 1.0.
- Other model profiles.

## Further Notes

Scratch trial, 2026-11-04, on PDF pages 36-41 and 43-45 of Part 1 (page 42 has no answer). Reference: the stored answers, corrected where the 22 disputed words and two hand-transcribed pages were checked against the scan. Other reference errors may remain, so small differences are ties.

| Vision reads | Wrong words at 300 dpi | Wrong words at 400 dpi |
|---|---|---|
| Whole page | 28 (2.5%) | 16 (1.4%) |
| Each Entry Span | 13 (1.2%) | 19 (1.7%) |
| Each line, padded with white | 12 (1.1%) | 11 (1.0%) |

- **The two reads fail on different words.** Whole page at 400 dpi and lines at 300 dpi share only 2 errors of 1,125 words (0.2%): *tàn→tùn* and *đu→du*. These are what the model can now put right, and they would show as Model Edits.
- **Expected volume.** The model changed agreed words about 2.4 times a page (22 on 9 pages) with VietOCR hints, which would be about 2,000 Model Edits over 830 pages. The trial on real output shows the true rate. If it stays high, the prompt is the first thing to change.
- **Limits of the trial.** The 400 dpi pages were the 300 dpi PNGs scaled up 4/3 with LANCZOS, apart from two true 400 dpi pages. Line crops came from a scratch line finder, not the project's. With the page at 400 dpi, the disputed share hasn't been measured.
