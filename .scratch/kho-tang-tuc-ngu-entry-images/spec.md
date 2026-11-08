Status: ready-for-agent

# Kho tàng tục ngữ người Việt: Entry Images in the export

Vocabulary: `vsc-project/khoTangTucNguoiNguoiViet/GLOSSARY.md` (Entry Image, Entry Span, Leading Span, Confirmed Span).

## Problem Statement

The export's text is the model's reading, laid over with the Confirmed Spans, and may still be wrong where nobody confirmed it. The reader needs a way to check any Proverb Entry against the book itself.

## Solution

`python3 -m src.khotangtucngu.export` also writes, for each Part, the Entry Image of every Proverb Entry, zipped, and each record of `letters/<letter>.json` names its image. Nothing else about the export changes: no new Markdown, and `intro.md` stays as it is.

## Decisions

- **Which crops.** An entry's crops are the `box` of every span, model span or Confirmed Span (its `crop`), of the rebuilt page answers (`review.lay_confirmed`) whose `blocks` range overlaps the entry's `blocks` on that page, joined into one crop per page (their union: an entry's Blocks are contiguous, so its spans on a page are adjacent). No new data is needed.
- **Whole spans, never cut.** A span holding a letter heading, or two Proverb Entries because the model missed a start, gives its whole crop to each entry it holds: A-200.png and A-201.png may show the same lines. The text in the image is always the book's. Which lines it covers comes from the layout and the Blocks, and confirming spans in review fixes that.
- **One file per entry.** An entry running onto later pages (finished by a Leading Span) gets one image, its crops stacked top to bottom in page order with a thin rule between pages. A narrower crop is padded with white on its right to the widest crop's width.
- **Name.** `<anchor>.png`, the entry's existing anchor: `A-200.png`, `Đ-12.png`, `Ư-3.png`. The letter is as printed, in NFC, not ASCII-folded. A name repeated in a Part (assembly keeps a duplicate entry, with its Warning) gets `_2`, `_3`, ... on (`A-200_2.png`), so no image overwrites another in the zip; the first keeps the plain name.
- **Resolution.** Grayscale PNG at `ENTRY_IMAGE_DPI = 200`, a new setting in `settings.py`, with the gap and grey rule between stacked pages beside it: body lines are about 33 px tall, their tone marks and dots under letters still clear. Measured: a 3-line span is about 11 KB at 200 dpi, 18 KB at 300 dpi. Zipping PNGs saves only about 3%, so the dpi is what sets storage, about 100–150 MB per Part.
- **The zip.** `store/<part>/export/entry_images.zip`, files flat (the letter is in the name), written straight from memory with no image folder on disk, `ZIP_STORED` because PNGs don't deflate. It is rewritten with the rest of `export/` on every run.
- **The record.** Each record of `letters/<letter>.json` gets `"image"`, its file in the zip (`"<anchor>.png"`, or the `_2` name of a repeat).
- **Errors, not skips.** The export stops with a clear message if a Part with an `answers.json` has no PDF (`pages.part_pdf`), or if an entry's Blocks on a page lie in no span (which consistent data never gives). Every Part's crops are worked out before any `export/` is emptied, so either error leaves the last export untouched.
- **Website.** `.scratch/kho-tang-tuc-ngu-website/spec.md` now says each proverb can show its Entry Image; how is settled when that card is grilled.

## Also to change

- The export's module docstring and the README's "4. Export" output list: `entry_images.zip` and the `image` field.
- The export's summary line per Part: how many Entry Images it wrote.

## Out of scope

- Cutting a span between two Proverb Entries it holds.
- Any change to how spans are found, read or reviewed.
