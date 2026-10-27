"""
The files one resume has in a run folder (docs/adr/0004-run-folders.md), and clearing them when that resume's
work is redone, so a run folder always holds one consistent pass per resume.

Run as a module to clear every evaluation in the active run folder, keeping the extractions it reads:
    python -m src.core.run_files --clear-evaluations
"""
import os
import sys

# Ensure repository root is in sys.path for 'src' package imports
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import argparse
import shutil
from typing import List, Optional

from src.core.config import (
    RUN_DIR, EXTRACTION_JSON_SUBDIR, EXTRACTION_MARKDOWN_SUBDIR, EVALUATION_JSON_SUBDIR, RESUME_PDF_SUBDIR,
    PROMPT_LOGS_SUBDIR, LOGS_SUBDIR, TOKEN_USAGE_FILENAME, RUN_FOLDER_NAMES
)
from src.core.logger import safe_log_name, EXTRACTION_LOG_CATEGORY, BROKEN_JSON_LOG_SUBDIR, HR_RAG_LOG_NAME
from src.providers.vllm_client import forget_resume_usage, EXTRACTION_STEP


_RESUME_FILE_EXTENSIONS = (".pdf", ".json", ".md")


def base_name(name: str) -> str:
    """
    A resume name or any of its file names (CV.pdf, CV.json, ...) as the base name its files share. Only those
    extensions are dropped, since a resume name itself may contain dots.
    """
    name = os.path.basename(name or "")
    stem, ext = os.path.splitext(name)
    return stem if ext.lower() in _RESUME_FILE_EXTENSIONS else name


def extraction_json_path(run_dir: str, name: str) -> str:
    return os.path.join(run_dir, EXTRACTION_JSON_SUBDIR, base_name(name) + ".json")


def extraction_markdown_path(run_dir: str, name: str) -> str:
    return os.path.join(run_dir, EXTRACTION_MARKDOWN_SUBDIR, base_name(name) + ".md")


def resume_pdf_path(run_dir: str, name: str) -> str:
    return os.path.join(run_dir, RESUME_PDF_SUBDIR, base_name(name) + ".pdf")


def evaluation_json_path(run_dir: str, name: str) -> str:
    return os.path.join(run_dir, EVALUATION_JSON_SUBDIR, safe_log_name(base_name(name)) + "_evaluation.json")


def prompt_logs_dir(run_dir: str, name: str) -> str:
    return os.path.join(run_dir, PROMPT_LOGS_SUBDIR, safe_log_name(base_name(name)))


def token_usage_path(run_dir: str) -> str:
    return os.path.join(run_dir, LOGS_SUBDIR, TOKEN_USAGE_FILENAME)


def run_dir_of_evaluation(evaluation_path: str) -> str:
    """The run folder an evaluation JSON file sits in."""
    return os.path.dirname(os.path.dirname(os.path.abspath(evaluation_path)))


def run_dir_of_extraction(resume_json_path: Optional[str], default: str) -> str:
    """
    The run folder an extraction JSON file sits in, or `default` for one outside the run folders (e.g. HR's ground
    truth in approved_jsons/): the website may evaluate a resume a pipeline run extracted.
    """
    if resume_json_path:
        extraction_dir = os.path.dirname(os.path.abspath(resume_json_path))
        run_dir = os.path.dirname(extraction_dir)
        if os.path.basename(extraction_dir) == EXTRACTION_JSON_SUBDIR and os.path.basename(run_dir) in RUN_FOLDER_NAMES:
            return run_dir
    return default


def _remove(path: str) -> None:
    if os.path.isdir(path):
        shutil.rmtree(path, ignore_errors=True)
    elif os.path.isfile(path):
        os.remove(path)


def clear_resume_evaluation(name: str) -> None:
    """
    Removes one resume's evaluation from the active run folder: its evaluation JSON, every prompt log but the
    extraction's (Category evaluation, Review Panel, their broken JSON) and its token usage but the extraction's.
    """
    _remove(evaluation_json_path(RUN_DIR, name))
    logs_dir = prompt_logs_dir(RUN_DIR, name)
    if os.path.isdir(logs_dir):
        for entry in os.listdir(logs_dir):
            if entry not in (EXTRACTION_LOG_CATEGORY, BROKEN_JSON_LOG_SUBDIR):
                _remove(os.path.join(logs_dir, entry))
        broken_dir = os.path.join(logs_dir, BROKEN_JSON_LOG_SUBDIR)
        if os.path.isdir(broken_dir):
            for entry in os.listdir(broken_dir):
                if entry != EXTRACTION_LOG_CATEGORY:
                    _remove(os.path.join(broken_dir, entry))
    forget_resume_usage(base_name(name), keep_steps=(EXTRACTION_STEP,))


def clear_resume(name: str) -> None:
    """Removes everything one resume has in the active run folder, before it is extracted again."""
    for path in (
        extraction_json_path(RUN_DIR, name), extraction_markdown_path(RUN_DIR, name), resume_pdf_path(RUN_DIR, name),
        evaluation_json_path(RUN_DIR, name), prompt_logs_dir(RUN_DIR, name)
    ):
        _remove(path)
    forget_resume_usage(base_name(name))


def evaluated_resume_names() -> List[str]:
    """Base names of the resumes the active run folder has an evaluation, or evaluation prompt logs, for."""
    names = set()
    eval_dir = os.path.join(RUN_DIR, EVALUATION_JSON_SUBDIR)
    if os.path.isdir(eval_dir):
        names.update(f[:-len("_evaluation.json")] for f in os.listdir(eval_dir) if f.endswith("_evaluation.json"))
    logs_root = os.path.join(RUN_DIR, PROMPT_LOGS_SUBDIR)
    if os.path.isdir(logs_root):
        names.update(d for d in os.listdir(logs_root) if os.path.isdir(os.path.join(logs_root, d)))
    names.discard(HR_RAG_LOG_NAME)
    return sorted(names)


def main():
    parser = argparse.ArgumentParser(description="Clear outputs in the active run folder (RUN_DIR).")
    parser.add_argument("--clear-evaluations", action="store_true",
                        help="Remove every evaluation, its prompt logs and token usage, keeping the extractions")
    args = parser.parse_args()
    if not args.clear_evaluations:
        parser.error("nothing to do: pass --clear-evaluations")
    for name in evaluated_resume_names():
        clear_resume_evaluation(name)
    print(f"[Run Files] Cleared every evaluation in {RUN_DIR}", file=sys.stderr)


if __name__ == "__main__":
    main()
