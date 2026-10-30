Status: ready-for-agent

# Kho tàng tục ngữ người Việt: transcribe the Proverb Entries

Vocabulary: the Kho tàng tục ngữ người Việt glossary (see `GLOSSARY-MAP.md`). The website card that will show this data is a separate spec, `.scratch/kho-tang-tuc-ngu-website/spec.md`.

## Problem Statement

The Front Matter of _Kho tàng tục ngữ người Việt_ is transcribed; the Proverb Entries are not. The first PDF Part holds its Proverb Entries on PDF pages 36–865 (book pp. 35–864): the letters A, Ă, Â, B and C, ending at C 2861. They are page images with no text layer. That is about 830 pages, far too many to transcribe by hand.

The developer wants the Proverb Entries on the digitizing website, as a reader-friendly dictionary. It needs three things the book doesn't give a reader directly:
- each Source's full name and Source Note on hover;
- General Abbreviations written out, and Corrections ("Sửa lại:") explained in plain words;
- each See-also shown as a preview of the proverb it names, rather than a bare name like "M 526".

The developer also needs a quick way to check, page by page, that the model transcribed the scan correctly before the data is trusted.

## Solution

A pipeline that transcribes the Proverb Entries of a PDF Part with the vLLM vision model on the GPU cluster. It is submitted with sbatch, for the whole Part or for chosen PDF pages.

- **Store.** Each page's answer is kept in one store per PDF Part, so runs over different page ranges add up. Code turns the stored answers into a verbatim, structured file of Proverb Entries, and flags anything that looks wrong as a Warning.
- **Review server.** A local review server shows each page's scan on the left and its transcribed Proverb Entries on the right, with the page's Warnings. The developer marks entries as checked and saves a Fix where the model got something wrong.
- **Export.** A local export command turns the verbatim entries, with Fixes applied, into website-ready data:
  - per-letter entries with Source hovers, Expansions, plain-language Corrections, See-also previews and filter fields;
  - the 63 Sources with their Source Notes;
  - the Front Matter cleaned up as the page's introduction.

  The developer copies the export into the website by hand.

## User Stories

1. As the developer, I want to submit one sbatch command for a PDF Part, so that every Proverb Entry page of it is transcribed on the GPU node.
2. As the developer, I want to pass a set of PDF pages (ranges and single pages), so that I can transcribe a trial or a section instead of the whole Part.
3. As the developer, I want the whole Part's proverb pages (skipping the Front Matter) scanned when I give no pages, so that the full run needs no page arithmetic.
4. As the developer, I want a dry run that counts each request's prompt tokens, images included, without sending anything, so that I know the requests fit the model's context before using GPU time.
5. As the developer, I want the default model profile served with vision on for this job only, so that the pipeline uses the same serving setup as Nữ Giới Chung.
6. As the developer, I want each page's answer saved as soon as it arrives, so that a job that dies part way keeps the work done.
7. As the developer, I want a rerun to redo only pages that failed, never ran, or were made under a different prompt, image setting or PDF, so that I don't pay twice for good answers.
8. As the developer, I want runs over different page ranges of a Part to add to one store, so that a trial on pages 36–45 and a later run on 46–865 together make the whole Part.
9. As the developer, I want the outputs always rebuilt from every saved page answer, so that a partial run never hides pages transcribed earlier.
10. As the developer, I want the text transcribed exactly as printed, never modernised or corrected, so that the data is faithful to the book.
11. As the developer, I want the Running Head left out, so that "Cha bòn ..." never leaks into a proverb or note.
12. As the developer, I want the printed book page number read from each page and checked against the PDF page, so that a misread or missing page shows up.
13. As the developer, I want printed line wraps inside a proverb, Variant or note joined into one line, so that the text reads as the sentence it is.
14. As the developer, I want each note paragraph kept as a separate note, so that distinct explanations stay distinct.
15. As the developer, I want each "- …" item of a BK list kept as its own Variant with its own Citations, so that each Variant's Sources stay attached to it.
16. As the developer, I want the italic words of a Variant or Correction kept as italic spans, so that the website can highlight what differs or what was corrected.
17. As the developer, I want a Leading Block joined to the last Proverb Entry of the page before, so that an entry running over a page break stays whole.
18. As the developer, I want a Leading Block with no Proverb Entry before it flagged, so that I know a partial run cut an entry in two.
19. As the developer, I want each Proverb Entry named as the book names it ("C 484", "Ă 12"), so that the name matches the book and the See-alsos.
20. As the developer, I want each Citation split into its Source Abbreviation and its pages, matching the longest known abbreviation first, so that "TNLG II 7, 25" is TNLG II with pages "7, 25", not TNLG with pages "II 7, 25".
21. As the developer, I want "VNP11"/"VNP2" normalised to "VNP₁₁"/"VNP₂", so that Citations match the Bảng chữ tắt.
22. As the developer, I want pages kept in their printed form ("20b", "7, 25"), so that leaf sides and page lists are not lost.
23. As the developer, I want each Correction recorded as its wrong wording, the Sources that printed it, and the right wording, so that it can be shown in plain language later.
24. As the developer, I want each Proverb Entry to carry the book and PDF pages it was printed on, so that I can find it on the scan.
25. As the developer, I want a Warning for a gap or a duplicate in the entry numbers of a letter, so that a skipped or doubled entry shows up.
26. As the developer, I want a Warning for a letter heading out of the book's alphabetical order, so that a misread heading shows up.
27. As the developer, I want a Warning for a Source Abbreviation not among the 63, so that a misread abbreviation shows up.
28. As the developer, I want a Warning for a Citation with no pages, or a Citation line that cannot be split, so that a misread Citation shows up.
29. As the developer, I want a Warning for a printed page number that doesn't follow the PDF page, so that a misread page shows up.
30. As the developer, I want a Warning for a page request that failed or has no answer, so that I know which pages to rerun.
31. As the developer, I want every Warning to carry its reason and its PDF page, so that I can go straight to it.
32. As the developer, I want to start the review server with one command in the store, with nothing to install, so that I can review on any machine.
33. As the developer, I want each page's scan on the left and its Proverb Entries on the right, so that I can compare the print with the transcription line by line.
34. As the developer, I want the right side to show the verbatim transcription with its italics, so that I check what the model read, not what the export derived.
35. As the developer, I want the page's Warnings shown beside it, so that I look first where something is likely wrong.
36. As the developer, I want to move between pages and jump to pages with Warnings, so that the review goes quickly.
37. As the developer, I want to mark a Proverb Entry as checked, so that I know how much of the Part I have reviewed.
38. As the developer, I want to save a Fix to a Proverb Entry, so that the model's mistake is corrected in what readers see.
39. As the developer, I want checks and Fixes appended to a review log that no run rebuilds or deletes, so that my review survives reruns.
40. As the developer, I want a Fix flagged stale when the model's transcription of its page changes, and not applied until I look again, so that an old Fix never overwrites a newer, different answer.
41. As the developer, I want to run the export on my laptop with one command, so that making website data needs no GPU.
42. As the developer, I want the export written only into the store's export folder, so that I decide when it goes into the website.
43. As the developer, I want Fixes that are not stale to replace the model's entries in the export, so that readers see the reviewed text.
44. As the developer, I want the export split into one file per letter, so that the website loads a letter at a time, as `tu-dien` does.
45. As a reader, I want each Citation's Source to show its full title, author and Source Note on hover, so that I know what book attests the proverb.
46. As a reader, I want Source Abbreviations inside notes ("Theo VD, …", "VD: …", "(theo CNGN)") to have the same hover, so that I know whose explanation I am reading.
47. As a reader, I want General Abbreviations shown as their full words, so that I never need the Bảng chữ tắt.
48. As the developer, I want General Abbreviations expanded only on whole-word, case-sensitive matches, so that "H" or "tr" inside ordinary words is never replaced.
49. As the developer, I want "VD" always treated as the Source Vũ Dung, never as "ví dụ", so that its hover is right.
50. As a reader, I want each Variant labelled "Bản khác" with its differing words highlighted, so that I see at once how it differs.
51. As a reader, I want a Correction explained in a plain sentence (which Source misprinted it, that the compilers judged it a misprint, not a Variant, and the corrected wording), so that "Sửa lại:" makes sense to me.
52. As a reader, I want each See-also shown as the first few words of the proverb it names, linking to it, so that I know where it leads before I click.
53. As a reader, I want a See-also to a PDF Part not yet transcribed shown by its name alone, so that I am never sent to a missing entry.
54. As the developer, I want Unresolved See-alsos to become previews and links automatically once their Part is exported, so that nothing needs patching by hand.
55. As the developer, I want a list of every Expansion made, with its entry and the text around it, so that I can spot a wrong one.
56. As the developer, I want a list of Unresolved See-alsos, for information and not as Warnings, so that I know what later Parts will resolve.
57. As a reader, I want to narrow the proverbs by letter and then by first syllable, so that I can find a proverb among thousands under one letter.
58. As a reader, I want to filter by Source, so that I can see what one book attests.
59. As a reader, I want to filter to proverbs with notes, Variants or a Correction, so that I can find the richly documented ones.
60. As a reader, I want to filter by earliest attestation year, so that I can find the proverbs recorded earliest.
61. As the developer, I want the earliest attestation year left empty when none of an entry's Sources is dated, so that the data never invents a year.
62. As the developer, I want each entry to carry an anchor (e.g. "C-484", keeping Ă and Â), so that See-also links and shared links land on it.
63. As the developer, I want the 63 Sources exported with title, author, kind, year where known and full Source Note, parsed from the transcribed Front Matter, so that the hover has one source of truth.
64. As the developer, I want multi-volume Sources to share their one Source Note, so that NASL I–IV all show the note about Nam âm sự loại.
65. As a reader, I want to read the Front Matter as an introduction with clear subheadings before the proverbs, so that I understand the book and its conventions.
66. As the developer, I want the Front Matter exported clean (no HTML comments, no ⚠ markers, no derived table) with its headings kept, so that the website can render it and build a table of contents.
67. As the developer, I want the pipeline to take any PDF Part, so that Parts 2–4 run the same way later.

## Implementation Decisions

- **New module family for this book**, parallel to the Nữ Giới Chung transcription and sharing only the infrastructure that serves and calls the model. Its settings are kept apart from the resume pipeline's config.
- **Command-line entry** for extraction. It takes a PDF Part, an optional page set and a dry-run flag. An sbatch submit script, modelled on Nữ Giới Chung's, wraps it. Pages are PDF pages. With no page set, the Part's proverb pages are used (36–865 for Part 1).
- **One request per PDF page.** The page image is sent at 300 dpi, and the model answers JSON under a schema. There is no layout pass and no separate Read and Format passes: the pages are one regular column. Retries on failure follow Nữ Giới Chung (sampled retries, a timeout per request). The answer holds:
  - the printed book page number;
  - the page's Blocks, in reading order.
- **Block kinds:**
  - letter heading;
  - proverb, with its number;
  - Citation line, as raw printed text;
  - Variant, with italic spans;
  - note;
  - Correction, as printed, with italic spans;
  - See-also, as printed names.
- **Store per PDF Part.** One folder per Part holds:
  - every page answer and the page images for review;
  - the verbatim entries and the Warnings;
  - the review log;
  - the export folder.

  Each answer is stamped with the PDF's hash, the image settings and a hash of the prompts. A run redoes only pages whose answer is missing, failed or stamped differently. A token-usage log is appended per request, as in Nữ Giới Chung.
- **Assembly**, done by code from all saved answers, builds the verbatim entries. It groups Blocks into Proverb Entries across pages and joins Leading Blocks to the previous page's last entry. The verbatim Proverb Entry shape is:
  - name, letter, number;
  - proverb;
  - Citations, as `{abbreviation, pages}`;
  - Variants, as `{text with italic spans, Citations}`;
  - notes, as plain strings;
  - Corrections, as `{wrong, sources[], right}`, with italic spans kept in `right`;
  - See-also names;
  - book pages and PDF pages.

  Nothing in this layer is expanded.
- **Citation splitting:** a longest-match tokenizer over the 63 Source Abbreviations, with subscript normalisation. What follows an abbreviation, up to the next abbreviation, is its pages, kept as printed.
- **Warnings** are kept as a list, each with its kind, its reason and its PDF page. The kinds are:
  - a number gap or duplicate within a letter;
  - a letter out of order (Phàm lệ II.1: A Ă Â B C D Đ E Ê G H I K L M N O Ô Ơ P Q R S T U Ư V X Y);
  - an unknown abbreviation;
  - a Citation with no pages, or a Citation line that cannot be split;
  - a page number out of step with the PDF page;
  - a failed or missing page;
  - a Leading Block with no owner.
- **Review server:** a small standard-library HTTP server copied into the store, plus a static page, as the Nữ Giới Chung viewer is.
  - It serves page images, the verbatim entries and the Warnings, and appends to the review log.
  - A review record is either a "checked" mark or a Fix: a full replacement Proverb Entry, with the hash of the page answer it was made against.
  - A Fix whose hash no longer matches is stale.
- **Export command**, run locally, reads the verbatim entries, the review log and the transcribed Front Matter, and writes into the store's export folder:
  - **per-letter entry files.** Each entry has:
    - its anchor;
    - Citations keyed to Sources;
    - Source mentions found in notes;
    - text with Expansions;
    - Variants labelled "Bản khác";
    - Corrections with their plain-language sentence;
    - See-also previews (first few words plus anchor), or the name alone when unresolved;
    - the filter fields: letter, first syllable, Sources cited, has notes / Variants / Correction, and earliest attestation year.
  - **The Sources file:** the 63 abbreviations, each with its title, author, kind, year where known and Source Note text.
  - **The cleaned introduction**, as Markdown.
  - **The Expansion list.**
  - **The Unresolved See-also list.**
- **Expansion rule:** only the 15 forms of Bảng chữ tắt part II, on whole-word, case-sensitive matches. "BK"/"bk" become the Variant's "Bản khác" label instead. Source mentions in notes are found the same way against the 63 abbreviations.
- **Correction sentence template:** _Sách {sources} in sai thành "{wrong}". Nhóm biên soạn cho đây là lỗi in, không phải dị bản, và sửa lại thành "{right}"._ The italic words of `right` are shown in bold.
- **Attestation year:** the earliest year of the entry's Sources in the dated list of Phàm lệ II.2 (CNGN 1896, ĐNQT 1908, NQPN 1914, NNCC 1918, NASL 1925, TNPD 1928, VNNN 1931, TNCD 1932, ANTN 1933, NNPD 1936). It is empty otherwise. KSK ("before 1945") is treated as undated.
- **See-also resolution** looks up names across every Part exported so far, so later Parts resolve earlier Unresolved See-alsos.

## Testing Decisions

- No automated tests are written for this pipeline (the repo's standing rule). Correctness is verified by reasoning over the code and by review of a real run.
- A good check exercises external behaviour only: what a page's scan shows against the Proverb Entries the pipeline produces. The internals are not checked.
- The verification path is:
  1. a trial run on a small page set that includes entries running over a page break (e.g. PDF pages 36–45 and 420–421);
  2. a look at every Warning in the review server;
  3. a spot check of entries against the scan.

  Then come the full run of Part 1 and its review.
- The Warnings are the pipeline's built-in checks: number continuity, letter order, known abbreviations, Citation splitting, page-number continuity and missing pages.
- The Expansion list and the Unresolved See-also list let the export be checked by eye.
- Prior art: the Nữ Giới Chung run folders, Warnings and review viewer, which were verified the same way.

## Out of Scope

- The website card (its page, filters and intro view) is its own spec. This spec only makes sure the data supports it.
- Running PDF Parts 2–4. The pipeline accepts them, but only Part 1 is run now.
- The Hệ thống tra cứu theo chủ đề (themes), the indexes (Bảng tra tên đất, tên người) and the Thư mục. Theme is a filter facet added later from the last PDF Part.
- Any command that copies the export into the website repository.
- Re-transcribing the Front Matter. It is already done, and the export reads it as it is.

## Further Notes

- Front Matter conventions the pipeline relies on are all in the transcribed Front Matter:
  - Phàm lệ II.1, the alphabet and naming of entries;
  - Phàm lệ II.2, the dated Sources;
  - Phàm lệ II.3, the meaning of Corrections, "VD:" quoting versus "theo", and See-also;
  - the Bảng chữ tắt, parts I and II.
- Suggested order of work:
  1. extraction and assembly on a trial page set;
  2. the review server;
  3. the full Part 1 run and its review;
  4. the export, which can be built alongside the review server once the verbatim entry shape is fixed by the trial run.
- The Block schema may need to change after the trial run. Building the review server and the export only after the trial keeps that change cheap.
