# Combined Extraction is how every resume is extracted

ADR 0013 added Combined Extraction behind an opt-in `--combined` flag, as a trial against text-only extraction, and left making it the default for later. That decision is now made: every extraction shows the model the page images next to the PyMuPDF text, on the website, in both batch jobs (`extract.sh`, `extract_evaluate.sh`), in both consistency checks and in the Bias Check. There is no text-only extraction and no flag to choose one: `--combined` and the consistency checks' `--text` are gone, and `ResumeExtractor` has no `combined` switch.

One mode everywhere means a resume is extracted the same way wherever it is extracted, so the website, a batch run and a check never disagree because they read different extractions, and a check always measures what HR actually gets. ADR 0013's rule is unchanged: the images show only the layout, every value must still come from the text layer, the fidelity check still compares every string against the PyMuPDF markdown, and Scanned Resumes are still rejected.

## Considered Options

- Keep `--combined` opt-in. Rejected: the website, which HR uses, stayed text-only, so the extraction HR saw differed from the one the batch trial measured.
- Make it the default but keep a text-only flag. Rejected: a second mode nobody runs in production only lets two runs of the same resumes differ, which ADR 0013 already ruled out within a run.

## Consequences

- Every job and the web server need a profile that can see images (`VLLM_VISION=1`) and refuse one that cannot, before anything is wiped; `qwen2.5-32b` and `glm4.7-flash` can no longer extract. vLLM is always served with vision on (`serve_vision_on`), which costs GPU memory.
- The mock extractor still sends no images: it has no server to send them to.
- Reports that recorded the extraction mode now always say Combined Extraction.
