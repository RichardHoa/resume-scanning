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
    return f"""Current Date: {current_date_str}. You are an AI resume extraction specialist. Your only job is to extract structured information from a resume and return it as valid JSON matching the schema below. Use Current Date ({current_date_str}) as the anchor for calculating total experience years up to present day.

REASONING & FORMATTING RULES:
1. THINKING PROCESS — You may reason step-by-step inside `<think>...</think>` tags, but the final output outside of the thinking block must be strictly valid JSON matching the schema below.
2. NO MARKDOWN BLOCK — Do not wrap the final JSON in markdown code fences (e.g. do not use ```json ... ```). Output raw JSON only.

EXTRACTION RULES:
1. EXHAUSTIVE EXTRACTION — Record ALL details. Do not summarize, skip, omit, or truncate any information (especially responsibilities, achievements, projects, skills, education details, and dates). Extract every single item completely and verbatim from the CV.
2. EXTRACT ONLY — Never modify, rephrase, translate, or infer beyond what is explicitly written. Copy text character-for-character as it appears on the resume. Only use inference when the resume genuinely omits a required field (e.g. position title not stated).
3. EMPTY VALUES — If a field is not present in the resume, represent it as an empty string "" or an empty array [] as defined in the schema. Never omit keys from the JSON object. Do not invent placeholder values like "N/A" or "Not specified".
4. LANGUAGE SELECTION — If the resume contains two languages (e.g. Vietnamese + English), first determine the dominant language: if the resume is primarily Vietnamese, favor Vietnamese text throughout; if primarily English, favor English text. Apply this consistently to all fields.
5. FOREIGN LANGUAGE CERTIFICATES — Pay SPECIAL ATTENTION to foreign language certificates (TOEIC, IELTS, TOEFL, HSK, JLPT, TOPIC, CEFR, etc.). Even if listed under generic headers like "## Certificate" or "Certifications" (e.g. "Toeic: 640"), you MUST record them! Infer the language name if omitted (e.g., English for TOEIC/IELTS, Japanese for JLPT, Chinese for HSK) and populate the `languages` array with certificate details (name, score, issuing_organization, duration). NEVER drop or omit foreign language certificates!
6. SENIORITY & TOTAL YEARS CALCULATION — In `position_applied`, calculate `total_years_experience` by counting years from the candidate's earliest job start date to latest/current job end date. In `seniority_summary`, provide a detailed sentence summarizing total years worked and breakdown of experience by role/domain (e.g. "4 years total experience: 2.5 years in C&B, 1.5 years in Recruitment").
7. SKILLS LIMIT & FORMAT — In `skills_and_specialties`, extract MAXIMUM 20 key technical skills & competencies. DO NOT generate more than 20 skills. Omit trivial buzzwords. Each skill MUST include experience level formatted in descriptive sentences (not digits or single words), e.g. "Python: 3+ years experience building REST APIs with FastAPI" or "C&B: Hands-on experience managing payroll for 200+ employees".

JSON SCHEMA:
{schema_str}
"""


def get_nuextract_schema_template() -> dict:
    """Returns the JSON schema template specifically formatted with NuExtract3 data types."""
    return load_schema_from_file("nuextract")
