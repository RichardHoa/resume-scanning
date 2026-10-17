# Docling parses resumes; scanned resumes are rejected, not OCR'd

> **Parser decision superseded by [ADR 0008](0008-pymupdf4llm-parser-docling-rejected.md):** Docling could not detect tables at all, and resumes are parsed by PyMuPDF4LLM again. The Scanned Resume rejection and no-OCR decision below still stand.

Resumes are converted to Markdown by Docling, with PyMuPDF4LLM as the fallback when Docling throws, returns no text, or runs past a 120-second timeout. PyMuPDF4LLM was the primary parser before this, but it broke tables (dates and companies in tabular work histories), and Docling's table model reconstructs them; we accept Docling's slower parsing for that. The parser output is the source text the fidelity check (ADR 0003) compares extractions against, so switching parsers changes what counts as verbatim, and every resume set was re-extracted and re-evaluated in one clean run rather than mixed with older results.

A PDF in which no page has a text layer is a Scanned Resume and is rejected before any parser runs, by a cheap PyMuPDF text-layer check. We considered OCR (Docling with RapidOCR, Tesseract `vie`, or EasyOCR), but resumes can be in any language, and OCR models that drop diacritics or misread a script would produce text that looks like resume evidence but is not, which is exactly what ADR 0003 forbids. Asking the candidate for a text PDF is cheaper and safer than guessing. Do not add an OCR path back without revisiting this.

> **Revisited by [ADR 0013](0013-combined-extraction-page-images-for-layout.md):** behind `--combined`, the extractor may see page images for layout only; values must still come from the text layer, and Scanned Resumes are still rejected.

## Consequences

- The OCR fallback chain and the `ocr_applied` / `intensive_hr_review_required` fields are removed.
- A Scanned Resume still appears in the results list, unranked and marked as scanned, separate from a Failed Evaluation (a rerun cannot fix it).
- A PDF with only some text-less pages is parsed normally, with a warning naming the pages HR should check by hand.
- ~~Docling's OCR is turned off and its table mode is `ACCURATE`; one converter is reused across files.~~ (superseded by ADR 0008)
