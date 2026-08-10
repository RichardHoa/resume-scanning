"""
Prompt templates for Step 2 Evaluator (RAG requirement decomposition & 5-dimension evaluation)
"""
import json
from datetime import datetime


def get_requirements_decomposition_prompt(standard_req: str, hidden_req: str, model_name: str) -> str:
    current_date_str = datetime.now().strftime("%Y-%m-%d")
    return f"""
Current Date: {current_date_str}
You are an expert HR requirement analyzer. Analyze the raw HR job requirement text below and decompose it into atomic criteria items categorized accurately into 5 dimensions using model '{model_name}':

1. seniority_title: Position titles, career levels, overall years of experience required, management/leadership expectations, AND field-specific experience requirements (e.g., "Ưu tiên có kinh nghiệm C&B từ 1-2 năm trở lên", "3+ năm kinh nghiệm Backend").
2. technical_skills: Programming languages, technical stacks, tools, frameworks, databases, cloud platforms, domain architecture skills.
3. work_experience: Domain experience, project backgrounds, specific industry exposure, role responsibilities, key achievements.
4. education_certifications: Academic degrees, majors, GPA requirements, professional certifications, foreign language certificates (TOEIC, IELTS, TOEFL, HSK, JLPT, etc.).
5. hidden_culture: Soft skills, workplace attitudes, corporate culture fit, stress tolerance, communication abilities, passion/mindset.

### RAW STANDARD REQUIREMENTS:
{standard_req or "None provided."}

### RAW HIDDEN REQUIREMENTS:
{hidden_req or "None provided."}

### INSTRUCTIONS:
Decompose and classify each requirement statement. Output strictly a single JSON object with this exact format:
```json
{{
  "seniority_title": ["<requirement 1>", "<requirement 2>"],
  "technical_skills": ["<requirement 1>", "<requirement 2>"],
  "work_experience": ["<requirement 1>", "<requirement 2>"],
  "education_certifications": ["<requirement 1>", "<requirement 2>"],
  "hidden_culture": ["<requirement 1>", "<requirement 2>"]
}}
```
Do not include any extra text outside the JSON block.
""".strip()


def get_category_evaluation_prompt(
    category_name: str,
    model_name: str,
    retrieved_criteria: list,
    resume_snippet: dict
) -> str:
    current_date_str = datetime.now().strftime("%Y-%m-%d")
    criteria_str = "\n".join([f"- {c}" for c in retrieved_criteria])
    snippet_str = json.dumps(resume_snippet, ensure_ascii=False, indent=2)

    return f"""
Current Date: {current_date_str}
You are an expert HR Hiring Manager evaluating using model '{model_name}'. Evaluate the following candidate's resume for dimension: '{category_name}'.
ANCHOR DATE: Use Current Date ({current_date_str}) as the temporal reference point for all time calculations (e.g. candidate work experience durations up to present, gap calculations, and recency of experience or education).

### HR REQUIREMENT CRITERIA (Retrieved via RAG):
{criteria_str}

### CANDIDATE RESUME SECTION:
{snippet_str}

### EVALUATION INSTRUCTIONS:
Analyze the candidate against the HR criteria.
MANDATORY LANGUAGE REQUIREMENT:
- All bullet points in "strengths" MUST be written in Vietnamese (Tiếng Việt).
- All bullet points in "gaps" MUST be written in Vietnamese (Tiếng Việt).
- Do NOT write strengths or gaps in English.

Output strictly a JSON object with this exact format:
```json
{{
  "score": <integer 0 to 100>,
  "strengths": ["<điểm mạnh 1 bằng Tiếng Việt>", "<điểm mạnh 2 bằng Tiếng Việt>"],
  "gaps": ["<hạn chế/điểm cần lưu ý 1 bằng Tiếng Việt>", "<hạn chế/điểm cần lưu ý 2 bằng Tiếng Việt>"],
  "evidence_quotes": ["<trích dẫn từ hồ sơ ứng viên>"]
}}
```
Do not include any extra introductory text outside the JSON.
""".strip()
