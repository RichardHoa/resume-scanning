"""
Prompt & LLM Context Logging Utility
Dumps raw prompt contexts and model responses to the run folder's prompt_logs/<resume>/<category>/N.txt files.
"""
import os
import sys

# Ensure repository root is in sys.path for 'src' package imports
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import re
from datetime import datetime
from typing import Optional
from src.core.config import PROMPT_LOGS_DIR

# Log category of the extraction LLM call; every other category of a resume belongs to its evaluation
EXTRACTION_LOG_CATEGORY = "step_1_extraction"
# Log folder of the LLM calls made once per HR RAG (scrutiny, decomposition), which belong to no resume
HR_RAG_LOG_NAME = "_hr_rag"
BROKEN_JSON_LOG_SUBDIR = "broken_json"


def safe_log_name(name: Optional[str], default: str = "resume") -> str:
    """A resume name or log category as used in prompt log folder names (and evaluation report file names)."""
    return re.sub(r'[^a-zA-Z0-9_-]', '_', name or default)


def log_llm_call(
    prompt_text: str,
    response_text: str,
    category: str,
    resume_name: str = "resume",
    run_index: Optional[int] = None,
    log_dir: Optional[str] = None
) -> str:
    """
    Dumps the full raw context prompt and model output to a .txt file in prompt_logs/<resume_name>/<category>/,
    or under a custom log directory instead.
    """
    if os.getenv("DISABLE_PROMPT_LOGGING", "0").lower() in ("1", "true", "yes"):
        return ""

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    safe_resume_name = safe_log_name(resume_name)
    safe_category = safe_log_name(category, "general")

    if not log_dir:
        candidate_cat_dir = os.path.join(PROMPT_LOGS_DIR, safe_resume_name, safe_category)
    elif os.path.basename(os.path.normpath(log_dir)) == safe_resume_name:
        candidate_cat_dir = os.path.join(log_dir, safe_category)
    else:
        candidate_cat_dir = os.path.join(log_dir, safe_resume_name, safe_category)

    log_content = "\n".join([
        "=" * 80,
        f"TIMESTAMP: {datetime.now().isoformat()}",
        f"RESUME: {resume_name}",
        f"CATEGORY: {category}",
        *( [f"RUN INDEX: {run_index}"] if run_index is not None else [] ),
        "=" * 80,
        "\n--- FULL LLM INPUT PROMPT CONTEXT ---\n",
        str(prompt_text or ""),
        "\n" + "=" * 80,
        "\n--- RAW MODEL RESPONSE ---\n",
        str(response_text or ""),
        "\n" + "=" * 80 + "\n"
    ])

    os.makedirs(candidate_cat_dir, exist_ok=True)
    if run_index is not None:
        filename = f"{run_index}.txt"
    else:
        existing_files = [f for f in os.listdir(candidate_cat_dir) if f.endswith('.txt')]
        filename = f"{len(existing_files) + 1}.txt"

    filepath = os.path.join(candidate_cat_dir, filename)
    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(log_content)
        print(f"[Logging] Saved model prompt context to {filepath}", file=sys.stderr)
    except Exception as e:
        print(f"[Logging Error] Failed to write log file {filepath}: {e}", file=sys.stderr)

    return filepath


def log_broken_json(
    prompt_text: str,
    response_text: str,
    category: str,
    resume_name: str = "resume",
    attempt: int = 1,
    error_reason: str = "",
    run_index: Optional[int] = None,
    finish_reason: Optional[str] = None,
    completion_tokens: Optional[int] = None,
    log_dir: Optional[str] = None
) -> str:
    """
    Specifically dumps raw prompt contexts and unparsable model responses to prompt_logs/<resume_name>/broken_json/<category>/
    (or under a custom log directory instead) for error tracking and dataset improvement.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    safe_resume_name = safe_log_name(resume_name)
    safe_category = safe_log_name(category, "general")

    if not log_dir:
        candidate_cat_dir = os.path.join(PROMPT_LOGS_DIR, safe_resume_name, BROKEN_JSON_LOG_SUBDIR, safe_category)
    elif os.path.basename(os.path.normpath(log_dir)) == safe_resume_name:
        candidate_cat_dir = os.path.join(log_dir, BROKEN_JSON_LOG_SUBDIR, safe_category)
    else:
        candidate_cat_dir = os.path.join(log_dir, safe_resume_name, BROKEN_JSON_LOG_SUBDIR, safe_category)

    os.makedirs(candidate_cat_dir, exist_ok=True)

    if run_index is not None:
        filename = f"{run_index}_attempt_{attempt}.txt"
    else:
        existing_files = [f for f in os.listdir(candidate_cat_dir) if f.endswith('.txt')]
        filename = f"{len(existing_files) + 1}.txt"

    filepath = os.path.join(candidate_cat_dir, filename)

    content = [
        "=" * 80,
        "BROKEN JSON FAILURE REPORT",
        f"TIMESTAMP: {datetime.now().isoformat()}",
        f"RESUME: {resume_name}",
        f"CATEGORY: {category}",
        f"ATTEMPT: {attempt}",
    ]
    if run_index is not None:
        content.append(f"RUN INDEX: {run_index}")
    content.extend([
        f"ERROR REASON: {error_reason or 'JSON parse failed or returned empty object'}",
        # "length" means the response hit the max_tokens limit and was cut off
        f"FINISH REASON: {finish_reason or 'unknown'}",
        f"COMPLETION TOKENS: {completion_tokens if completion_tokens is not None else 'unknown'}",
        "=" * 80,
        "\n--- FULL LLM INPUT PROMPT CONTEXT ---\n",
        str(prompt_text or ""),
        "\n" + "=" * 80,
        "\n--- RAW INVALID MODEL RESPONSE ---\n",
        str(response_text or ""),
        "\n" + "=" * 80 + "\n"
    ])

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(content))
        print(f"[Broken JSON Logged] Saved invalid model output and prompt to {filepath}", file=sys.stderr)
    except Exception as e:
        print(f"[Logging Error] Failed to write broken JSON file {filepath}: {e}", file=sys.stderr)

    return filepath


