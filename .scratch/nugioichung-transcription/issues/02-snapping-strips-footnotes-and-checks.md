# 02: Box snapping, Strips, Footnote pairing and checks

**What to build:** Make the rough first version from ticket 01 accurate and complete:

- No crop cuts through a line of text.
- Dense Regions are read in Strips.
- Articles get their Footnotes.
- Text the layout pass missed is flagged.
- Each run writes the datasheet-style CSV of Articles and a summary of what needs looking at.

The new steps also appear in `inspect.html`.

See the spec (`.scratch/nugioichung-transcription/spec.md`), the Nữ Giới Chung glossary, and Nữ Giới Chung ADR 0001.

**Blocked by:** 01 (Shared request module and a rough first version of the full pipeline)

**Status:** ready-for-agent

- [x] Each Region's box edges are moved onto the nearest column gap or printed rule found on the bilevel scan, so no crop cuts through a line of text. The drawn layout page shows the adjusted boxes.
- [x] A Region taller than about a third of the page is cut into Strips at blank gaps between printed lines, with no overlap. Each Strip is its own transcription request, saved like any other, and listed under its Region in `inspect.html`.
- [x] A paragraph cut by a Strip or Region boundary is joined back into one paragraph, using the `starts_mid_paragraph`/`ends_mid_paragraph` flags.
- [x] A Footnotes Region is transcribed as a list of {number, text}. Each call "(n)" in an Article's text is paired with Footnote n of the same Article, with numbers running across its pages. Pairs are written as Markdown footnotes `[^n]`. An unpaired call or Footnote is marked ⚠.
- [x] Printed text that falls inside no Region (ignoring specks and page edges) is found on the bilevel scan and flagged as ⚠ "text outside any Region" on the drawn layout page and in `inspect.html`.
- [x] `articles.csv` has one row per Article, with the columns Chủ đề (left empty), Bài viết, Tác giả, Chuyên mục, Số báo, Ngày xuất bản and Nội dung.
- [x] A dropped log lists every request with no successful answer, and every Footnote and text outside any Region left unresolved, with the reason.
- [x] At the end of a run, a summary prints requests by status, Regions, Strips, unpaired Footnotes and text outside any Region.

## Comments

- 2026-10-27: Implemented (uncommitted). Choices made along the way:
  - Footnote labels are `[^<Item number>-<n>]`, not bare `[^n]`: Markdown footnote labels must be unique in a file, and every Article numbers its own from (1). Renderers number them in order anyway, so the label is not shown.
  - Footnote calls "(n)" are only looked for in an Item that has Footnotes, so an enumeration like "(1) … (2) …" in an Article with none isn't flagged. The flip side: if the layout pass misses an Article's Footnotes Region, its calls get no ⚠. That Region's text is still flagged as text outside any Region.
  - A Footnotes Region that begins partway through a Footnote gives that part with number 0, and it is joined onto the Footnote before it, across Strips and Regions.
  - `articles.csv` writes Ngày xuất bản as dd/mm/yyyy (01/02/1918) and is UTF-8 with a BOM so spreadsheets read the diacritics. Check the date against the old datasheet's format.
  - The text-outside check ignores ink within 2.5% of the page edges, solid dark patches touching them (scanner border, skew wedges), patches wholly in the top 6% (running header and page number) and patches under about 300 ink pixels. Library Marks below the header band will be flagged.
  - The bilevel thresholds (ink level, blank and rule shares, minimum gap runs of 5 px between lines and 10 px between columns, and so on) live in `pages.py`. Only the snap reach and Strip height are in `settings.py`.
