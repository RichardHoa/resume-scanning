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
from src.core.config import LOGGING_DIR


def log_llm_call(prompt_text: str, response_text: str, category: str, resume_name: str = "resume") -> str:
    """
    Dumps the full raw context prompt and model output to a .txt file in logging/
    """
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    safe_resume_name = re.sub(r'[^a-zA-Z0-9_-]', '_', resume_name or "resume")
    filename = f"prompt_{timestamp}_{safe_resume_name}_{category}.txt"
    filepath = os.path.join(LOGGING_DIR, filename)

    content = [
        "=" * 80,
        f"TIMESTAMP: {datetime.now().isoformat()}",
        f"RESUME: {resume_name}",
        f"CATEGORY: {category}",
        "=" * 80,
        "\n--- FULL LLM INPUT PROMPT CONTEXT ---\n",
        str(prompt_text or ""),
        "\n" + "=" * 80,
        "\n--- RAW MODEL RESPONSE ---\n",
        str(response_text or ""),
        "\n" + "=" * 80 + "\n"
    ]

    try:
        with open(filepath, "w", encoding="utf-8") as f:
            f.write("\n".join(content))
        print(f"[Logging] Saved model prompt context to {filepath}", file=sys.stderr)
    except Exception as e:
        print(f"[Logging Error] Failed to write log file {filepath}: {e}", file=sys.stderr)

    return filepath
