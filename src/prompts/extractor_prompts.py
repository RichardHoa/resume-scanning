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


def get_system_prompt(language: str = "vietnamese") -> str:
    current_date_str = datetime.now().strftime("%Y-%m-%d")
    qwen_schema = load_schema_from_file("qwen")
    schema_str = json.dumps(qwen_schema, ensure_ascii=False, indent=2)
    
    target_lang = "English" if language.lower() in ("english", "en") else "Vietnamese"

    return f"""Current Date: {current_date_str}. You are an AI resume extraction specialist. Extract all structured details from the resume into valid raw JSON matching the schema below.

CORE DIRECTIVES:
- Format: Provide the raw JSON object directly as the primary response. Populate empty or unstated string/list fields using "" or [] while retaining every schema key in the output structure.
- Language Policy: Preserve source content verbatim in its original language, prioritizing {target_lang} when processing bilingual resumes.
- Fidelity: Maintain exact source text verbatim phrasing. Integrate adjacent achievement and KPI blocks directly within work responsibilities.
- Field Formatting: Follow the specific format and extraction guidelines detailed for each property inside the JSON SCHEMA below.

JSON SCHEMA:
{schema_str}
"""



