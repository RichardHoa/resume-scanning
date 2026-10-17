Status: implemented (uncommitted)

# Combined extraction: page images alongside the PyMuPDF text, behind `--combined`

## Problem Statement

PyMuPDF4LLM (ADR 0008) is the only parser, and it scrambles some resume layouts: multi-column pages interleave, sidebars land in the wrong place, and tabular work histories lose which date belongs to which company. The extractor LLM only sees that scrambled text, so it copies values into the wrong entries. Stronger parsers were ruled out: Docling failed on tables (ADR 0008), PaddleOCR-VL cannot share an environment with torch/vLLM (ADR 0009), and MinerU needs `tomlkit` and `openai` downgrades.

The default model profile, like six others, is a vision-language checkpoint served text-only (`--language-model-only`). Showing the extractor the page images lets it see the real layout, while the text it copies still comes from the PDF's text layer.

## Decisions so far

- **Opt-in flag `--combined`.** With it, the extraction call gets each page's image *and* the PyMuPDF4LLM markdown. Without it, extraction is exactly what it is today. The flag is for a side-by-side trial; making it the default is a later decision.
- **Images give layout, text gives the words.** The prompt tells the model to use the images only to see structure (columns, which entry a date or company belongs to, table rows, reading order), and to copy every value from the extracted text. Text that is visible in an image but missing from the extracted text is not extracted. ADR 0003 (copy, never infer) is unchanged.
- **The fidelity check is unchanged.** Every extracted string is still checked against the PyMuPDF4LLM markdown (`check_extracted_fields_in_markdown`), with the same matching. It is also the guard against the model reading text from pixels. It may give false "not found" warnings when PyMuPDF splits a value that the model, seeing the image, extracted whole. The trial counts these; loosening the match is a separate decision, made only if the numbers call for it.
- **Text-only profiles refuse.** `--combined` with a profile that cannot see images (`qwen2.5-32b`, `glm4.7-flash`), or with a raw HuggingFace model ID that has no profile, fails before vLLM starts, with an error naming the vision-capable profiles. Without `--combined`, every profile works as today.
  - Each profile records whether it can see images (new `VLLM_VISION=1|0` in `scripts/model_profiles.sh`, default 0). Checked against each model's HuggingFace `config.json` (`vision_config` present) on 2026-10-17: vision for `qwen3.5-35b-a3b`, `sea-lion-v4.5-27b`, `qwen3.6-35b-a3b`, `qwen3.8-27b`, `gemma4-26b-a4b`, `gemma4-31b`, `muse-glimmer-30b`; text-only for `qwen2.5-32b` and `glm4.7-flash`.
- **Vision is turned on per job, the way proofreading does it.** With `--combined`, the job script drops the profile's `--language-model-only` and `--limit-mm-per-prompt*` flags and adds `--limit-mm-per-prompt.image <COMBINED_MAX_PAGES> --limit-mm-per-prompt.video 0`, as `scripts/submit_correction.sh` already does. Without the flag, vLLM is served exactly as today. Turning the vision encoder on uses some GPU memory, so a profile's `CONCURRENCY` may need lowering for combined jobs; measure in the trial.
- **Scanned Resumes are still rejected** (ADR 0007). A combined run never extracts a PDF with no text layer, because nothing could check the result. For a PDF where only some pages have no text, those pages are not sent as images either, and the existing "Pages without text" warning stays.
- **Page images.** Rendered with PyMuPDF (`page.get_pixmap`, already installed; no new dependency) at 150 DPI as JPEG, sent as base64 `image_url` content parts in page order, each preceded by a "PDF page N:" label, then the markdown text. `vllm_client.chat` already accepts content-part lists. At most `COMBINED_MAX_PAGES = 6` pages are sent (about 2,000 image tokens per page, which fits in `VLLM_MAX_MODEL_LEN = 32768` next to the prompt and output). For longer resumes, the first 6 text pages are sent as images, all text is still sent, and a warning says which pages were not shown.
- **Logs don't hold image bytes.** The extraction log (`log_llm_call`, `log_broken_json`) records each image as a `[page image]` placeholder after its "PDF page N:" label, not base64.
- **Mock mode ignores `--combined`'s images** (no server to send them to) but still takes the flag.

## Where the flag goes

- `src/cli/extract.py` (reached through `src/step_1_extractor.py`): `--combined` argument, passed to `ResumeExtractor`.
- `scripts/submit_extract_vllm.sh` and `scripts/submit_extract_eval_vllm.sh`: accept `--combined` anywhere among the arguments (like `--tech`), refuse text-only profiles, serve vision on, and forward `--combined` to the extractor.
- `ResumeExtractor` / `extraction_messages` / `run_vllm_inference`: build the combined message when asked; the text-only message is unchanged.
- **Out of scope for now:** the web server (`scripts/server.sh`, `src/server.py`, `src/api/extraction.py`), the bias and consistency suites, DSPy. They keep text-only extraction.

## The trial (what the flag is for)

Run the resumes that fail today twice, without and with `--combined`, same model. Compare by hand: wrong-entry values (dates, companies, titles), fidelity warnings per resume, and wall time and tokens (`scripts/token_stats.py`). The two runs must not be mixed in one resume set (ADR 0003).

Testing is manual and done by the developer; no automated tests are added.

## To do when this is built

- New ADR: page images may be shown to the extractor for layout only, behind `--combined`; values must come from the text layer, and the fidelity check enforces it. It revisits ADR 0007's no-OCR rule (images are read by the model, but nothing read only from pixels is accepted) and leaves its Scanned Resume rejection unchanged. Note that it does not supersede ADR 0008: PyMuPDF4LLM is still the parser.
- `CONTEXT.md`: add **Combined Extraction** (extraction that sees page images and the PyMuPDF text; values only from the text).
- Update the usage comments of the two job scripts and the `model_profiles.sh` header (`VLLM_VISION`).
