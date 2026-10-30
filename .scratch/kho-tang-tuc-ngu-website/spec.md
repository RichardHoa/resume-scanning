Status: needs-triage

# Kho tàng tục ngữ người Việt: the website card

Not grilled yet. This records the developer's description of the card, and the decisions about it already settled while grilling `.scratch/kho-tang-tuc-ngu-proverbs/spec.md`. The data it reads is that spec's export. Vocabulary: `vsc-project/khoTangTucNguoiNguoiViet/GLOSSARY.md`.

## Problem Statement

The digitizing website (`digitizing-vietnam-website`) has the page `/vi/research/ca-dao-tuc-ngu`, whose cards lead to tools such as `/vi/research/ca-dao-tuc-ngu/tu-dien`. _Kho tàng tục ngữ người Việt_ gets a fifth card there, leading to its own page.

## What the developer described

- **Like `tu-dien`, without images.** The page is modelled on `tu-dien`, but has no image of the book page.
- **Front Matter first.** Before seeing any proverb, the reader sees the whole Front Matter as an introduction to the page, with clear subheadings.
- **Sources with hover.** Each proverb shows its Sources. Hovering a Source Abbreviation shows the Source's full name and its Source Note from the Front Matter.
- **General Abbreviations written out.** Every General Abbreviation (Bảng chữ tắt part II) is shown as its full words, not as the abbreviation.
- **Corrections explained.** "Sửa lại:" is shown in a way easy to understand. The book does not make its meaning clear; Phàm lệ II.3 explains it.
- **See-also as links.** The book names a See-also only by letter and number. The website shows the first few words of the proverb it names, and clicking it moves to that proverb.
- **Filtering beyond one row.** The book has many letters, and themes, so a single row of filters is not enough. The page needs an intuitive way to filter to what the reader wants.

## Already settled (while grilling the proverbs spec)

- The page reads only the export's files: the per-letter JSON, `sources.json` and `intro.md`.
- The intro is `intro.md`, with its headings kept so the page can show a table of contents.
- "BK" is shown as a "Bản khác" label on a Variant. The words that differ, italic in the book, are highlighted.
- A Correction is shown as a plain-language sentence. For example: _Sách CCM in sai thành "Nằm giữa mất…". Nhóm biên soạn cho đây là lỗi in, không phải dị bản, và sửa lại thành "Nằm giữa **không** mất…"._
- Source Abbreviations inside notes get the same hover as Citations.
- An Unresolved See-also shows its name alone, with no preview or link, until its PDF Part is transcribed.
- The filters are layered:
  - letter, then first syllable (tiếng đầu);
  - facets for Source, earliest attestation year, and has notes / Variants / Correction;
  - theme, as a facet added once the Hệ thống tra cứu theo chủ đề in the last PDF Part is transcribed.
- Each Proverb Entry's anchor is its name with a hyphen, e.g. `C-484`.

## Open (to grill when we come back)

- The layout of the filters (sidebar, drawer on phones, chips), and whether search is part of it, as in `tu-dien`.
- How the intro and the proverb list connect: one page or two, and whether the intro can be skipped on a return visit.
- What a Proverb Entry looks like on the page: the order of proverb, Variants, notes, Corrections, See-also and Sources.
- Hover on touch screens.
- The card's title and text in `messages/`, in each locale.
- How See-also behaves when the entry it names is filtered out of the current list.
