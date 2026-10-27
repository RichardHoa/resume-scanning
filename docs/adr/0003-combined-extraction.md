# Combined Extraction: page images show the layout, the text layer gives the words

Every extraction shows the model each text page's image next to the PyMuPDF markdown. This applies on the website, in the batch jobs, in the consistency checks and in the Bias Check. The images fix what the parser scrambles (ADR 0002): interleaved columns, moved sidebars, and table rows that lose their dates. The prompt tells the model to use the images only for layout and to copy every value from the text.

This does not reverse the no-OCR rule. The model looks at pixels, but we accept nothing it reads only from an image: the fidelity check (ADR 0001) still compares every extracted string against the PyMuPDF markdown. Scanned Resumes are still rejected, and pages without text are never shown, because nothing could check what the model read from them.

There is no text-only mode and no flag to choose one. With one mode, a resume is extracted the same way everywhere, so the website, a batch run and a check never disagree because they read different extractions, and a check always measures what HR actually gets.

## Considered Options

- **Opt-in `--combined` flag.** This was the first trial. Rejected as the end state: the website stayed text-only, so the extraction HR saw differed from the one the batch trial measured.
- **Combined by default, with a text-only flag.** Rejected: a second mode nobody runs in production only lets two runs of the same resumes differ.

## Consequences

- Extraction needs a model profile that can see images (`VLLM_VISION=1`). Every job and the web server refuse a profile that cannot, before anything is wiped. vLLM is always served with vision on (`serve_vision_on`), which costs GPU memory.
- At most `COMBINED_MAX_PAGES` (6) pages are shown, at 150 DPI. Longer resumes get a warning naming the pages read from text only.
- PyMuPDF sometimes splits a value that the model extracts whole from the image, which can trigger a false "not found" warning. So the fidelity match also accepts values found without spaces, bullet by bullet, word by word within a short stretch of text, and a language named from its certificate (`.scratch/fidelity-checker/spec.md`). Every value must still come from the text layer.
- The mock extractor sends no images, because it has no server to send them to.
