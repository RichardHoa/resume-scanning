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

- [ ] Each Region's box edges are moved onto the nearest column gap or printed rule found on the bilevel scan, so no crop cuts through a line of text. The drawn layout page shows the adjusted boxes.
- [ ] A Region taller than about a third of the page is cut into Strips at blank gaps between printed lines, with no overlap. Each Strip is its own transcription request, saved like any other, and listed under its Region in `inspect.html`.
- [ ] A paragraph cut by a Strip or Region boundary is joined back into one paragraph, using the `starts_mid_paragraph`/`ends_mid_paragraph` flags.
- [ ] A Footnotes Region is transcribed as a list of {number, text}. Each call "(n)" in an Article's text is paired with Footnote n of the same Article, with numbers running across its pages. Pairs are written as Markdown footnotes `[^n]`. An unpaired call or Footnote is marked ⚠.
- [ ] Printed text that falls inside no Region (ignoring specks and page edges) is found on the bilevel scan and flagged as ⚠ "text outside any Region" on the drawn layout page and in `inspect.html`.
- [ ] `articles.csv` has one row per Article, with the columns Chủ đề (left empty), Bài viết, Tác giả, Chuyên mục, Số báo, Ngày xuất bản and Nội dung.
- [ ] A dropped log lists every request with no successful answer, and every Footnote and text outside any Region left unresolved, with the reason.
- [ ] At the end of a run, a summary prints requests by status, Regions, Strips, unpaired Footnotes and text outside any Region.
