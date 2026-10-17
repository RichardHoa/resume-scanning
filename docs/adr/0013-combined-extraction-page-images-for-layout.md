# Combined Extraction: page images show the layout, the text layer gives the words

PyMuPDF4LLM (ADR 0008) scrambles some resume layouts: columns interleave, sidebars move, and tabular work histories lose which date belongs to which company, so the extractor copies values into the wrong entries. Better parsers were ruled out (Docling in ADR 0008, PaddleOCR-VL in ADR 0009, and MinerU needs `tomlkit` and `openai` downgrades). Most of our model profiles are vision-language checkpoints served text-only, so `--combined` shows the extractor each text page's image next to the PyMuPDF markdown. The prompt tells it to use the images only for layout and to copy every value from the text.

This revisits ADR 0007's no-OCR rule without reversing it: the model does look at pixels, but nothing it reads only from an image is accepted, because the fidelity check (ADR 0003) still compares every extracted string against the PyMuPDF markdown, unchanged. Scanned Resumes are still rejected, and pages without text are never shown, since nothing could check what the model read from them. PyMuPDF4LLM stays the only parser; ADR 0008 is not superseded.

`--combined` is opt-in for a side-by-side trial against text-only extraction on the resumes it fails. Making it the default is a later decision. A run is either combined or not, never mixed, because the two produce different extractions of the same resumes.

## Consequences

- Each model profile records `VLLM_VISION`; `--combined` refuses a text-only profile (`qwen2.5-32b`, `glm4.7-flash`) or a raw model ID before the run folder is wiped. Without the flag, every profile works as before.
- A combined job serves vLLM with vision on (`serve_vision_on`, shared with the proofreading job), which costs GPU memory; a profile's `CONCURRENCY` may need lowering for combined runs.
- At most `COMBINED_MAX_PAGES` (6) pages are shown, at 150 DPI; longer resumes get a warning naming the pages read from text only.
- The fidelity check can give false "not found" warnings when PyMuPDF splits a value the model extracted whole from the image. The trial counts them; loosening the match is a separate decision.
- Only the batch extraction CLI and its two job scripts take `--combined`; the web server, bias and consistency suites and DSPy stay text-only.
