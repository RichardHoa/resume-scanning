"""
Developer details of one evaluated resume: everything its run folder holds for it, for the website's developer
panel. Run-wide logs (job, step and vLLM logs) mix every resume together and are left out.
"""
import json
import os
import re
import sys
from typing import Any, Dict, List, Optional

from src.core.config import DIMENSION_WEIGHTS
from src.core.logger import EXTRACTION_LOG_CATEGORY, BROKEN_JSON_LOG_SUBDIR
from src.core.run_files import prompt_logs_dir, token_usage_path
from src.providers.vllm_client import read_resume_usage, EXTRACTION_STEP

# Pipeline steps the prompt logs are grouped by, in pipeline order
EXTRACTION_STEP_KEY = "extraction"
EVALUATION_STEP_KEY = "evaluation"
REVIEW_PANEL_STEP_KEY = "review_panel"
OTHER_STEP_KEY = "other"
_STEP_ORDER = (EXTRACTION_STEP_KEY, EVALUATION_STEP_KEY, REVIEW_PANEL_STEP_KEY, OTHER_STEP_KEY)
_CATEGORY_ORDER = list(DIMENSION_WEIGHTS)


def _step_of(category: str) -> str:
    if category == EXTRACTION_LOG_CATEGORY:
        return EXTRACTION_STEP_KEY
    if category in DIMENSION_WEIGHTS:
        return EVALUATION_STEP_KEY
    if category.startswith("review_panel"):
        return REVIEW_PANEL_STEP_KEY
    return OTHER_STEP_KEY


def _read_text(path: Optional[str]) -> Optional[str]:
    if not path or not os.path.isfile(path):
        return None
    try:
        with open(path, encoding="utf-8") as f:
            return f.read()
    except (OSError, UnicodeDecodeError) as e:
        print(f"[Dev Details] Could not read {path}: {e}", file=sys.stderr)
        return None


def _log_files(category_dir: str) -> List[Dict[str, str]]:
    """A category folder's prompt log files in the order they were written (1.txt, 2.txt, ... 10.txt)."""
    def order(name: str):
        return [int(part) if part.isdigit() else part for part in re.split(r'(\d+)', name)]
    names = sorted((f for f in os.listdir(category_dir) if f.endswith(".txt")), key=order)
    return [{"name": name, "content": _read_text(os.path.join(category_dir, name)) or ""} for name in names]


def _log_categories(logs_dir: str) -> List[Dict[str, Any]]:
    """Every prompt log category folder of one resume, broken JSON dumps as categories of their own."""
    categories: List[Dict[str, Any]] = []
    if os.path.isdir(logs_dir):
        for entry in sorted(os.listdir(logs_dir)):
            entry_dir = os.path.join(logs_dir, entry)
            if not os.path.isdir(entry_dir):
                continue
            if entry == BROKEN_JSON_LOG_SUBDIR:
                for category in sorted(os.listdir(entry_dir)):
                    if os.path.isdir(os.path.join(entry_dir, category)):
                        categories.append({"category": category, "broken": True, "files": _log_files(os.path.join(entry_dir, category))})
            else:
                categories.append({"category": entry, "broken": False, "files": _log_files(entry_dir)})
    return categories


def _prompt_log_groups(categories: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Prompt log categories grouped by pipeline step, then ordered by Category; broken JSON dumps sit beside theirs."""
    def category_order(c: Dict[str, Any]):
        known = _CATEGORY_ORDER.index(c["category"]) if c["category"] in _CATEGORY_ORDER else len(_CATEGORY_ORDER)
        return (known, c["category"], c["broken"])

    groups = []
    for step in _STEP_ORDER:
        step_categories = sorted((c for c in categories if _step_of(c["category"]) == step), key=category_order)
        if step_categories:
            groups.append({"step": step, "categories": step_categories})
    return groups


def resume_dev_details(
    run_dir: str,
    extraction_run_dir: str,
    resume_name: str,
    report: Dict[str, Any],
    resume_json_path: Optional[str],
    markdown_path: Optional[str]
) -> Dict[str, Any]:
    """
    Everything stored for one evaluated resume, for the website's developer panel: the evaluation's files from its
    run folder, the extraction's from the run folder that extracted it (the same one unless the website evaluated
    a resume a pipeline run extracted).
    """
    resume_json = None
    resume_json_text = _read_text(resume_json_path)
    if resume_json_text is not None:
        try:
            resume_json = json.loads(resume_json_text)
        except json.JSONDecodeError:
            resume_json = resume_json_text
    return {
        "run_folder": os.path.basename(run_dir),
        "resume_name": resume_name,
        "extraction_markdown": _read_text(markdown_path),
        "extraction_json": resume_json,
        "evaluation_json": report,
        "prompt_logs": _prompt_log_groups(
            [c for c in _log_categories(prompt_logs_dir(extraction_run_dir, resume_name)) if _step_of(c["category"]) == EXTRACTION_STEP_KEY]
            + [c for c in _log_categories(prompt_logs_dir(run_dir, resume_name)) if _step_of(c["category"]) != EXTRACTION_STEP_KEY]
        ),
        "token_usage": (
            [r for r in read_resume_usage(token_usage_path(extraction_run_dir), resume_name) if r.get("step") == EXTRACTION_STEP]
            + [r for r in read_resume_usage(token_usage_path(run_dir), resume_name) if r.get("step") != EXTRACTION_STEP]
        )
    }
