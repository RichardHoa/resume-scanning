"""
Utility functions for data extraction, list deduplication and PII sanitization in Resume Evaluator pipeline.
"""
from typing import Dict, List, Any


def clean_and_deduplicate_list(items: Any, max_items: int = 10) -> List[str]:
    """Cleans whitespace, removes duplicates while preserving order, and caps item count."""
    if isinstance(items, str):
        items = [items]
    elif not isinstance(items, list):
        items = []

    seen = set()
    cleaned = []
    for item in items:
        s = str(item).strip()
        if s and s not in seen:
            seen.add(s)
            cleaned.append(s)
            if len(cleaned) >= max_items:
                break
    return cleaned


# The raw resume keys each Category is judged on, passed through unchanged.
# None means the whole resume except basic_information (hidden_culture can draw on any section).
CATEGORY_RESUME_KEYS = {
    "seniority_title": ("position_applied", "self_evaluation", "work_experience"),
    "technical_skills": ("skills", "work_experience", "projects", "languages"),
    "work_experience": ("work_experience", "projects"),
    "education_certifications": ("education_background", "certifications", "languages"),
    "hidden_culture": None,
}


def strip_identity(resume: Dict[str, Any]) -> Dict[str, Any]:
    """
    The resume without basic_information. It only identifies the candidate (name, contacts, location,
    profile links), and the LLM can't follow a link, so no LLM call after extraction sees it.
    """
    return {k: v for k, v in resume.items() if k != "basic_information"}


def is_missing_position(resume: Dict[str, Any]) -> bool:
    """A Missing Position: the resume states no position the candidate is applying for."""
    position = resume.get("position_applied") if isinstance(resume, dict) else None
    title = position.get("title") if isinstance(position, dict) else None
    return not (isinstance(title, str) and title.strip())


# Set on the extraction JSON of a Scanned Resume (no page has text), which is never evaluated or ranked
SCANNED_RESUME_KEY = "scanned_resume"


def is_scanned_resume(resume: Dict[str, Any]) -> bool:
    """A Scanned Resume: rejected at extraction because no page of its PDF has text."""
    return isinstance(resume, dict) and resume.get(SCANNED_RESUME_KEY) is True


def extract_relevant_resume_field(category: str, resume: Dict[str, Any]) -> Dict[str, Any]:
    """The raw resume keys a Category is judged on, unchanged; basic_information is never one of them."""
    resume = resume if isinstance(resume, dict) else {}
    keys = CATEGORY_RESUME_KEYS.get(category, CATEGORY_RESUME_KEYS["hidden_culture"])
    if keys is None:
        return strip_identity(resume)
    return {key: resume[key] for key in keys if key in resume}
