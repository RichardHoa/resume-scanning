# 01: Apple Vision reads pages on the Mac, the cluster job uses its reads, and Model Edits are marked

**What to build:** the whole pipeline in the spec (`.scratch/kho-tang-tuc-ngu-vision-ocr/spec.md`), which holds the details and evidence. The developer runs one command on the Mac for a Part, with or without `--pages`. It finds each page's printed lines, reads every line and the whole page with Apple Vision, and saves the results in the Part's store. They copy that output to the cluster and run the existing job, which no longer uses VietOCR. The Entry Span model sees each line's two reads with Disputed Syllables marked, and stays free to spell any word as the scan prints it. Wherever its Blocks differ from an Agreed Syllable, its text is kept and a Model Edit Warning appears in `warnings.json` and in the review server.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

Verify by reasoning: add no tests or browser checks, make no commits, and leave the changes uncommitted for the developer. Criteria marked "first batch" can only be seen on the developer's run, so leave them unticked.

## The Mac command

- [x] `python3 -m src.khotangtucngu.vision_ocr --part-1` reads every proverb page of the Part, and `--pages 36-45,420-424` reads only those, with the same page parsing as the CLI
- [x] Runs over different pages add up in the store, and a page with a current read is skipped
- [x] A page Vision fails on is saved as failed and the run carries on; rerunning reads it again
- [x] Running off macOS, or with the PDF missing, exits with a clear message
- [x] The Vision reader compiles at the start of a run and stays one process for the whole run, with revision 3, the accurate level, `vi-VT` and language correction off
- [x] Each line's OCR Reading comes from the existing line crop at 300 dpi with 45 px of white padding; each Page Reading comes from the page at 400 dpi, matched to lines by box centre
- [x] An observation matching no line, or spanning two, is saved as unmatched and otherwise unused
- [x] The saved stamp holds the macOS version, Vision revision, language, correction flag, both DPIs and the pad, and a different stamp or PDF means the page is read again
- [x] The run ends by printing pages read, pages failed, the share of Disputed Syllables, and the `rsync` line for what it wrote; it transfers nothing itself
- [x] The command imports nothing GPU-bound or from vLLM, and a new macOS requirements file holds its four dependencies at the main file's pinned versions

## The cluster job

- [x] The CLI reads the Mac's printed lines and no longer finds lines itself; `--dry-run` needs them too
- [x] Before any request, the job exits naming any page of this run whose read is missing, failed or made from another PDF
- [x] A job with `--pages` needs reads for those pages only
- [x] The transfer covers only the lines and Vision records, never the review log
- [x] VietOCR's module, requirement, settings, the store's OCR folder and its debug images are gone, and nothing in the settings, prompts, CLI docstring or job script still names it

## The two reads and the model

- [x] Agreed Syllables are those the two reads share exactly on a line, made only of letters of the Vietnamese alphabet; every other syllable of a line with both reads is Disputed, and a line with one read has neither
- [x] The Entry Span user text marks each Disputed Syllable as `[line read|page read]`, marks a stretch of unequal length whole, and labels a line with one read
- [x] The Span prompt tells the model to settle each marked word from the scan, and to change an unmarked word only where the scan clearly prints otherwise, never for what a word ought to be

## Model Edits

- [x] The model's Blocks stay exactly as it wrote them; nothing overwrites or rejects them
- [x] A `model_edit` Warning names the entry and both spellings for an Agreed Syllable with changed marks or changed letters, and says so for one dropped or a syllable added, in `proverb`, `variant`, `note` and `correction` text only
- [x] `BK`, `bk`, `Xem thêm`, `Sửa lại` and entry numbers never count as dropped, and Citations and See-alsos never raise one
- [x] A syllable never raises both a Model Edit and a Diacritic Disagreement, and repeats of one edit in an entry show once with a count
- [x] The Warnings are rebuilt in the CLI's run and in the review server's rebuild and preview, so a Fix that restores the reads' spelling clears its mark; the store's copied modules stay standard-library only
- [x] The review page shows the kind under its own name, and the run's Warning counts include it

## Docs

- [x] New ADR 0005 records the two reads and Model Edits, with the hard lock as a rejected option
- [x] The GLOSSARY adds Page Reading, Agreed Syllable, Disputed Syllable and Model Edit, and updates OCR Reading
- [x] The README's book section gets the Mac step, `--pages` for a first batch, the transfer and the new store files, and loses its stale store rows

## First batch (the developer's run on `--pages 36-45,420-424`)

- [ ] Every page passes the job's early check
- [ ] The disputed share is compared with the trial's figure of about 2.5%
- [ ] Every Model Edit on those pages is read against the scan, counting right edits, wrong edits and false marks
