# 01: Transcribe a PDF Part's pages into verbatim Proverb Entries with Warnings

**What to build:** The developer submits one sbatch command for a PDF Part, for a chosen set of PDF pages or for all its proverb pages. The vision model transcribes each page, and the developer gets the Part's Proverb Entries exactly as printed, plus a list of Warnings about anything that looks wrong. Runs over different page ranges add up in one store per PDF Part. Spec: `../spec.md`.

- The command takes the PDF Part, an optional page set (PDF pages, ranges and single pages) and a dry-run flag. With no page set it scans every proverb page of the Part, skipping the Front Matter (36–865 for Part 1).
- The dry run counts each request's prompt tokens with the model's own processor, images included, and sends nothing, as in Nữ Giới Chung.
- The submit script follows Nữ Giới Chung's: the default model profile, served with vision on for this job only.
- Each page gets one request: its image at 300 dpi, answered as JSON under a schema. The answer holds the printed book page number and the page's Blocks in reading order.
  - The Running Head is left out.
  - Line wraps are joined, and each note paragraph and each "- …" Variant stays separate.
  - Variants and Corrections keep their italic words as `*…*`.
  - Citation lines come back as raw printed text.
- Page answers are saved in the Part's store as they arrive, stamped with the PDF's hash, the image settings and a hash of the prompts. A run redoes only pages whose answer is missing, failed or stamped differently. Token usage is logged per request.
- Code builds the verbatim Proverb Entries from **every** saved page answer, not only this run's:
  - Blocks are grouped into Proverb Entries named as the book names them ("C 484").
  - Leading Blocks are joined to the last entry of the page before.
  - Citations are split into `{abbreviation, pages}` by longest match against the 63 Source Abbreviations, with "VNP11"/"VNP2" normalised to "VNP₁₁"/"VNP₂".
  - Corrections are recorded as `{wrong, sources[], right}`.
  - Each entry carries its book and PDF pages.
  - Nothing is expanded.
- Warnings, each with its kind, reason and PDF page:
  - a gap or a duplicate in a letter's entry numbers;
  - a letter heading out of the book's order;
  - an unknown Source Abbreviation;
  - a Citation with no pages, or one that cannot be split;
  - a page number out of step with the PDF page;
  - a failed or missing page;
  - a Leading Block with no owner.
- The page images the review server will show are written to the store.

The Nữ Giới Chung shared request code, CLI and submit script are prior art: reuse them, don't copy them.

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

- [ ] `sbatch` with `--pages 36-45,420-421` on Part 1 transcribes exactly those pages into the Part's store
- [ ] `--dry-run` prints per-request token counts and sends nothing
- [ ] With no `--pages`, the page set is the Part's proverb pages (36–865 for Part 1)
- [ ] A rerun of the same pages sends no requests; changing the prompt redoes them
- [ ] A later run on other pages adds to the store, and the verbatim entries include both runs' pages
- [ ] An entry that runs over a page break (e.g. on 420–421) comes out as one Proverb Entry
- [ ] Running Heads appear nowhere in the entries
- [ ] "TNLG II 7, 25" splits as TNLG II with pages "7, 25"; "VNP11" comes out as "VNP₁₁"
- [ ] Variant and Correction text keeps its `*…*` italics; notes are plain
- [ ] Each Warning kind is raised by a case that produces it, with its reason and PDF page; a page with no Warnings reports none
