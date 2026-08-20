"""
Prompt templates for Step 1 Extractor (Qwen & NuExtract models)
"""
import os
import sys

# Ensure repository root is in sys.path for 'src' package imports
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import json
from datetime import datetime
from src.core.json_utils import load_schema_from_file


def get_system_prompt() -> str:
    current_date_str = datetime.now().strftime("%Y-%m-%d")
    qwen_schema = load_schema_from_file("qwen")
    schema_str = json.dumps(qwen_schema, ensure_ascii=False, indent=2)
    return f"""Current Date: {current_date_str}. You are an AI resume extraction specialist. Extract all structured details from the resume into valid raw JSON matching the schema below.

CORE DIRECTIVES:
- Format: Output ONLY raw valid JSON (no markdown fences like ```json, no thinking/reasoning tags). Use "" or [] for missing fields; never omit schema keys or use "N/A".
- Fidelity: Extract verbatim without summarizing, translating, or rephrasing. Retain dominant language for bilingual CVs. Include adjacent achievement/KPI blocks directly inside work responsibilities.
- Special Fields:
  * languages: Always record foreign language certs (TOEIC, IELTS, HSK, JLPT, etc.) into `languages`, inferring language name if omitted.
  * position_applied: Extract job title as written on the resume (or inferred from context if not explicitly stated).

JSON SCHEMA:
{schema_str}
"""

