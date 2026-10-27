# PyMuPDF4LLM is the only parser, and Scanned Resumes are rejected rather than OCR'd

PyMuPDF4LLM converts resumes to Markdown, and there is no fallback parser. Its known weakness is layout: tables, columns and sidebars come out scrambled, so a tabular work history can lose which date belongs to which company. We accept that weakness, and Combined Extraction (ADR 0003) handles layout instead. If PyMuPDF4LLM fails or returns no text, the resume errors out.

A PDF in which no page has a text layer is a Scanned Resume. A cheap PyMuPDF text-layer check rejects it before parsing. Resumes can be in any language, and an OCR model that drops diacritics or misreads a script produces text that looks like resume evidence but is not, which ADR 0001 forbids. Asking the candidate for a text PDF is cheaper and safer than guessing. Do not add an OCR path, or switch parsers for table handling, without revisiting this ADR.

## Considered Options

- **Docling**, as primary parser with PyMuPDF4LLM as fallback. We tried it and rejected it: even in `ACCURATE` TableFormer mode with OCR off, it did not detect tables as tables, so rows came out as loose text from a slower, heavier parser. Do not switch to it again, as primary or fallback.
- **PaddleOCR-VL**. We dropped it before trying it, because `paddlepaddle-gpu` cannot be installed next to our pinned stack. vLLM requires a specific torch, which pins its own CUDA packages, and every Paddle GPU build pins different ones (`cuda-toolkit`, `nvidia-nccl-cu13`, `nvidia-cublas`, `cuda-bindings`), so pip fails with `ResolutionImpossible` (checked 2026-10-15). It also reads page images, so its text is OCR. A separate venv, or the CPU `paddlepaddle` build with the VL model served by vLLM, might work, but we tried neither.
- **MinerU**. Rejected: it needs `tomlkit` and `openai` downgrades.
- **OCR for Scanned Resumes** (RapidOCR, Tesseract `vie`, EasyOCR). Rejected for the reason above.

## Consequences

- A Scanned Resume still appears in the results list, unranked and marked as scanned, separate from a Failed Evaluation, because a rerun cannot fix it.
- A PDF in which only some pages lack text is parsed normally, with a warning naming the pages HR should check by hand.
