# Nữ Giới Chung

Vocabulary for transcribing scanned issues of _Nữ Giới Chung_ (Femina Annamite), a weekly Saigon newspaper from 1918, into text.

## Language

**Issue**:
One numbered weekly edition of the newspaper, scanned as one PDF of page images with no text layer (e.g. Số 1, 1 February 1918). Its number and date come from the file name.
_Avoid_: volume, số (alone), edition

**Item**:
One self-contained piece of an Issue, of one kind: Article, Ad, Notice (masthead, prices, editorial office) or Table of Contents. An Issue is transcribed as its Items in reading order.
_Avoid_: block, section, piece

**Article**:
An Item of editorial text, with its section (e.g. Xã thuyết, Gia chánh), title and author as printed. It may run over several columns and pages.
_Avoid_: bài (alone), story, post

**Ad**:
An Item that advertises a product, shop or business. It is transcribed like any other Item.
_Avoid_: advertisement block, quảng cáo (alone)

**Region**:
A rectangle of one page holding one part of one Item: a column of an Article, a boxed Ad, the footnotes printed under an Article. An Item is made of one or more Regions.
_Avoid_: block, zone, box (alone)

**Strip**:
A horizontal slice of a tall Region, cut at a blank gap between printed lines so no line is split or repeated. A Region is transcribed whole, or Strip by Strip if it is tall.
_Avoid_: tile, chunk, slice

**Read**:
The first request for a Region or Strip: the model copies its printed lines exactly, one per line, as a Faithful Transcription with no formatting.
_Avoid_: OCR, transcription (alone), draft

**Format**:
The second request for a Region or Strip: the model sees the crop again with the lines it Read and writes the same text as Markdown (headings, paragraphs, tables, lists, verse), changing no letter. Code checks the letters match and falls back to the Read lines when they don't. A Footnotes Region has no Format request: code splits its Read lines into Footnotes.
_Avoid_: cleanup, post-processing, rewrite

**Footnote**:
A numbered note printed under an Article, called in its text by the same number in parentheses, e.g. "(7)". Numbers run on across the Article's pages, and a Footnote belongs to the Article it is printed under.
_Avoid_: note (alone), chú thích (alone)

**Library Mark**:
Handwriting added to the scan after printing, such as a library's shelf number or date. It is not part of the Issue and is never transcribed.
_Avoid_: annotation, note

**Faithful Transcription**:
Copying exactly what the page prints: the 1918 spelling, hyphens, Hán characters and the newspaper's own typos, never modernised or corrected. The one exception is a run of dots (leader dots or a long ellipsis), written as three dots `...` and left out of a table.
_Avoid_: cleaned text, normalised text

**Warning**:
Something code flags in a transcribed Issue for the developer to look at, always with its reason and the place on a page it concerns: printed text outside every Region, a Region the layout pass left out, a Region or Strip with no transcription, a Footnote or call left unpaired, printed lines that could not be matched to the lines Read, or a Format answer that was not used. A Warning with no narrower place concerns its whole page.
_Avoid_: flag, error, dropped (alone)

**Resolution**:
The developer's verdict on one Warning, with an optional note. Printed text outside every Region is resolved as not printed text (a speck, the scan's border, a Library Mark), a picture, or missed text, with what it says; any other Warning as a false alarm or a real problem.
_Avoid_: dismissal, ack

**Correction**:
The developer's fix to the transcribed text of one place in an Issue: the text before, the text after, and an optional note on why. It is feedback for improving the transcription, not an edit of the Issue's output.
_Avoid_: edit (alone), fix, patch
