# Nữ Giới Chung is read by a two-pass VLM, with no OCR draft

Each Issue is transcribed by the default vision model in two passes. A layout pass sees the whole page small and returns its Regions. A transcription pass then reads each Region, or each Strip of a tall Region, cut from the full 300 dpi scan, in two requests: a Read request copies its printed lines exactly, and a Format request lays the same text out as Markdown. No OCR engine's text is given to the model as a draft. This differs from the book pipeline in the vsc repo, which gives the model Apple Vision and Tesseract lines.

## Considered Options

- **Whole page in one request**: rejected. The dense three-column pages, one with about 55 Footnotes, overrun the 4096-token page answer. Reports on historical newsprint show VLMs skipping text and looping on dense full pages.
- **Columns cut by code** (vertical rules and whitespace on the bilevel scan, with no layout model): rejected as the main method, because it breaks on mixed pages (masthead, boxed Ads) and cannot tell where one Item ends and the next begins. The same image analysis is kept only to snap the model's box edges to column gaps and rules, and to place Strip cuts at blank line gaps.
- **One transcription request that copies and formats at once**: replaced. With about fifteen copying and layout rules in one prompt, the model dropped some of them (it kept printed line breaks inside paragraphs, cutting sentences in the Issue). Split in two, each request has only its own rules, and code can check that the Format request changed no letter of the Read one, which a single request can't be checked against. The cost is about twice the transcription requests, each sending the crop.
- **OCR draft as a hint**: left out. Tesseract reads 1918 bilevel newsprint with mixed fonts poorly, Apple Vision runs only on macOS, and a draft would need the column crops first anyway. It can be added later and measured the way the book pipeline's OCR-hint comparison was.

## Consequences

- Text the layout pass misses is never transcribed, so code flags printed text that falls outside every Region.
- Every request's exact image, prompt and answer is kept, so the layout and the crops can be checked by eye.
- A Format answer whose letters differ from its Read lines is not used: the Read lines are joined into one paragraph by code and logged, so formatting never silently alters the text but can be lost for that Region or Strip.
