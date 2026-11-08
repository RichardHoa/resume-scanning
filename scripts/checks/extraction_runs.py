"""
Extraction helpers shared by the checks in scripts/checks: the Extractor Accuracy Check, the evaluator consistency
check and the Bias Check. Imported after the check has put the repository root on sys.path.
"""
import os
import json

from src.core.config import PROMPT_LOGS_DIR
from src.pipelines.extractor import ResumeExtractor, find_textless_pages, REPAIRED_EXTRACTION_WARNING
from src.pipelines.evaluator_utils import SCANNED_RESUME_KEY


def is_scanned_pdf(pdf_path: str) -> bool:
    """A Scanned Resume: no page has text. An unreadable PDF is left to the extraction runs to report as failed."""
    try:
        textless, page_count = find_textless_pages(pdf_path)
    except Exception:
        return False
    return len(textless) == page_count


def run_extraction(extractor: ResumeExtractor, pdf_path: str, out_dir: str, run: int) -> dict:
    """
    One extraction run, saved to out_dir, its prompt logs under prompt_logs/run-<n>/ so the runs never overwrite
    each other's. Returns {"run", "data"} or {"run", "error"} for a failed run; "raised" marks a run whose request
    failed (server down, timeout, or rejected, e.g. a prompt over the context length), which says nothing about the
    model's answers.
    """
    try:
        text = extractor.extract(pdf_path, log_dir=os.path.join(PROMPT_LOGS_DIR, f"run-{run}"))
    except Exception as e:
        return {"run": run, "error": f"extraction raised: {e}", "raised": True}
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        with open(os.path.join(out_dir, f"run-{run}.txt"), "w", encoding="utf-8") as f:
            f.write(text or "")
        return {"run": run, "error": "invalid JSON after all retries"}

    with open(os.path.join(out_dir, f"run-{run}.json"), "w", encoding="utf-8") as f:
        f.write(text)
    error = extraction_error(data)
    return {"run": run, "error": error} if error else {"run": run, "data": data}


def extraction_error(data) -> str | None:
    """Why a parsed extraction cannot be used, or None when it can."""
    if not isinstance(data, dict):
        return "extraction is not a JSON object"
    if data.get(SCANNED_RESUME_KEY):
        return "rejected as a Scanned Resume"
    if "error" in data:
        return str(data["error"])
    # A Repaired Extraction is cut off: using it would only show the fields it lost
    if REPAIRED_EXTRACTION_WARNING in (data.get("warning") or []):
        return "invalid JSON after all retries; the last answer was patched (Repaired Extraction)"
    return None
