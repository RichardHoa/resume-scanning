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
from src.core.json_utils import load_schema_from_file
from src.core.language import is_english
from src.core.reference_date import current_date_prompt_line


def get_system_prompt(language: str = "vietnamese", combined: bool = False) -> str:
    """The extraction system prompt; `combined` adds the rule for Combined Extraction's page images."""
    qwen_schema = load_schema_from_file("qwen")
    schema_str = json.dumps(qwen_schema, ensure_ascii=False, indent=2)

    target_lang = "English" if is_english(language) else "Vietnamese"

    # Images give the layout, the extracted text gives the words: values read only from pixels fail the fidelity check
    page_images_directive = (
        "\n- Page Images: The resume's PDF pages are also shown as images. Use them only to see the layout: columns, "
        "reading order, table rows, and which job, school or project each date, company, title and description belongs to. "
        "Copy every value from the extracted text, never from the images. If text appears in an image but not in the "
        "extracted text, leave it out."
    ) if combined else ""

    return f"""{current_date_prompt_line()} You are an AI resume extraction specialist. Extract all structured details from the resume into valid raw JSON matching the schema below.

CORE DIRECTIVES:
- Format: Provide the raw JSON object directly as the primary response. Populate empty or unstated string/list fields using "" or [] while retaining every schema key in the output structure.
- Language Policy: The resume can be written in any language (e.g. Vietnamese, English, Japanese, Korean, Chinese, French), not only Vietnamese or English. If the resume contains a version in {target_lang}, extract from that version. Otherwise extract whatever the resume states, verbatim in its original language; never translate it.
- Copy Only: Never write, summarize, expand, explain or infer content. Leave a field empty rather than guess its value. The one exception is naming a language from its certificate, as the languages field allows.
- Fidelity: Maintain exact source text verbatim phrasing. Integrate adjacent achievement and KPI blocks directly within work responsibilities.
- Field Formatting: Follow the specific format and extraction guidelines detailed for each property inside the JSON SCHEMA below.{page_images_directive}

JSON SCHEMA:
{schema_str}
"""



