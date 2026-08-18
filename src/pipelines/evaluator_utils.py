"""
Utility functions for data extraction, list deduplication, PII sanitization, and output validation in Resume Evaluator pipeline.
"""
import re
from typing import Dict, List, Any, Optional


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


def validate_category_evaluation(parsed: Any) -> Optional[Dict[str, Any]]:
    """Validates that parsed JSON contains a valid numeric score (0-100) and required output fields."""
    if not isinstance(parsed, dict) or not parsed:
        return None

    score_val = parsed.get("score")
    if score_val is None:
        return None

    try:
        score_str = str(score_val).strip()
        # Reject string placeholders like '<integer>', '<integer 0-100>', or text containing no digits
        if score_str.startswith("<") or not any(c.isdigit() for c in score_str):
            return None
        # Extract digits
        clean_num = re.sub(r'[^0-9.]', '', score_str)
        if not clean_num:
            return None
        score = int(round(float(clean_num)))
    except (ValueError, TypeError):
        return None

    if not (0 <= score <= 100):
        return None

    strengths = clean_and_deduplicate_list(parsed.get("strengths", []), max_items=10)
    gaps = clean_and_deduplicate_list(parsed.get("gaps", []), max_items=8)
    quotes = clean_and_deduplicate_list(parsed.get("evidence_quotes", []), max_items=6)
    reasoning = str(parsed.get("reasoning_summary", "")).strip()

    return {
        "score": score,
        "strengths": strengths,
        "gaps": gaps,
        "evidence_quotes": quotes,
        "reasoning_summary": reasoning
    }


def extract_relevant_resume_field(category: str, resume: Dict[str, Any]) -> Dict[str, Any]:
    """Extracts and sanitizes relevant resume sections tailored for each evaluation dimension."""
    resume = resume if isinstance(resume, dict) else {}
    work_exp = resume.get("work_experience", [])
    work_exp_list = work_exp if isinstance(work_exp, list) else []

    if category == "seniority_title":
        work_exp_summary = []
        for w in work_exp_list:
            if isinstance(w, dict):
                pos = w.get("position", "")
                comp = w.get("company_name", "")
                dur = w.get("duration", "")
                comp_info = w.get("company_description") or w.get("company_size") or w.get("industry") or ""
                if comp_info:
                    work_exp_summary.append(f"{pos} tại {comp} ({comp_info}) ({dur})")
                else:
                    work_exp_summary.append(f"{pos} tại {comp} ({dur})")
            elif isinstance(w, str):
                work_exp_summary.append(w)
        return {
            "position_applied": resume.get("position_applied", {}),
            "self_evaluation": resume.get("self_evaluation", ""),
            "work_experience_history": work_exp_summary,
            "work_experience_details": work_exp_list
        }
    elif category == "technical_skills":
        return {
            "skills_and_specialties": resume.get("skills_and_specialties", []),
            "languages": resume.get("languages", [])
        }
    elif category == "work_experience":
        return {
            "work_experience": work_exp_list,
            "projects": resume.get("projects", []),
            "skills_and_specialties": resume.get("skills_and_specialties", [])
        }
    elif category == "education_certifications":
        return {
            "education_background": resume.get("education_background", []),
            "certifications": resume.get("certifications", []),
            "languages": resume.get("languages", [])
        }
    else:
        summary_lines = []
        for w in work_exp_list:
            if isinstance(w, dict):
                resp = w.get("responsibilities", "")
                if resp:
                    summary_lines.append(str(resp))
            elif isinstance(w, str):
                summary_lines.append(w)
        basic_info = resume.get("basic_information", {})
        sanitized_basic_info = {}
        if isinstance(basic_info, dict):
            # Programmatically filter out email and phone to prevent name/PII leakage in LLM evaluation
            sanitized_basic_info = {
                k: v for k, v in basic_info.items()
                if k not in ("email", "phone", "name", "full_name")
            }

        return {
            "self_evaluation": resume.get("self_evaluation", ""),
            "basic_information": sanitized_basic_info,
            "work_experience_summary": summary_lines
        }
