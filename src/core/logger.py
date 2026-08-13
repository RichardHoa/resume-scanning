"""
Prompt & LLM Context Logging Utility
Dumps raw prompt contexts and model responses to logging/*.txt files.
"""
import os
import sys

# Ensure repository root is in sys.path for 'src' package imports
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import re
from datetime import datetime
from src.core.config import LOGGING_DIR, BROKEN_JSON_DIR


from typing import Optional


def log_llm_call(
    prompt_text: str,
    response_text: str,
    category: str,
    resume_name: str = "resume",
    run_index: Optional[int] = None
) -> str:
    """
    Dumps the full raw context prompt and model output to a .txt file in logging/<resume_name>/<category>/
    """
    if os.getenv("DISABLE_PROMPT_LOGGING", "0").lower() in ("1", "true", "yes"):
        return ""

    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    safe_resume_name = re.sub(r'[^a-zA-Z0-9_-]', '_', resume_name or "resume")
    safe_category = re.sub(r'[^a-zA-Z0-9_-]', '_', category or "general")

    candidate_cat_dir = os.path.join(LOGGING_DIR, safe_resume_name, safe_category)
    os.makedirs(candidate_cat_dir, exist_ok=True)

    if run_index is not None:
        filename = f"{run_index}.txt"
    else:
        existing_files = [f for f in os.listdir(candidate_cat_dir) if f.endswith('.txt')]
        filename = f"{len(existing_files) + 1}.txt"

    filepath = os.path.join(candidate_cat_dir, filename)

    content = [
        "=" * 80,
        f"TIMESTAMP: {datetime.now().isoformat()}",
        f"RESUME: {resume_name}",
        f"CATEGORY: {category}",
    ]
    if run_index is not None:
        content.append(f"RUN INDEX: {run_index}")
    content.extend([
        "=" * 80,
        "\n--- FULL LLM INPUT PROMPT CONTEXT ---\n",
        str(prompt_text or ""),
        "\n" + "=" * 80,
        "\n--- RAW MODEL RESPONSE ---\n",
        str(response_text or ""),
        "\n" + "=" * 80 + "\n"
    ])

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(content))
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
    run_index: Optional[int] = None
) -> str:
    """
    Specifically dumps raw prompt contexts and unparsable model responses to broken-json/<resume_name>/<category>/
    for error tracking and dataset improvement.
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    safe_resume_name = re.sub(r'[^a-zA-Z0-9_-]', '_', resume_name or "resume")
    safe_category = re.sub(r'[^a-zA-Z0-9_-]', '_', category or "general")

    candidate_cat_dir = os.path.join(BROKEN_JSON_DIR, safe_resume_name, safe_category)
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


