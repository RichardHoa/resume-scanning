# PyMuPDF4LLM parses resumes; Docling was tried and rejected

Resumes are converted to Markdown by PyMuPDF4LLM alone, with no fallback parser. We switched to Docling (ADR 0007) because PyMuPDF4LLM breaks tables (dates and companies in tabular work histories), hoping Docling's table model would rebuild them. It did worse: even with the `ACCURATE` TableFormer mode and OCR off, Docling could not detect that a table was a table at all, so the rows came out as loose text and the slower, heavier parser bought nothing. PyMuPDF4LLM's table breakage is accepted as a known limitation. Do not switch to Docling again, as primary or fallback, for its table handling.

## Consequences

- Supersedes the parser half of ADR 0007; its Scanned Resume rejection and no-OCR decision still stand.
- If PyMuPDF4LLM fails or returns no text, the resume errors out; there is no second parser.
- The Docling packages (and RapidOCR, which only Docling used) are removed from `requirements.txt`.
- The parser output is the source text the fidelity check (ADR 0003) compares extractions against, so every resume set is re-extracted and re-evaluated in one clean run; Docling-era results are not mixed in.
