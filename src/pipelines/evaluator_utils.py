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
    """
    Validates that parsed JSON contains valid evaluation data.
    If criteria_evaluations list is present, computes score deterministically from atomic criteria coverage.
    Otherwise, validates the numeric score (0-100) and required output fields.
    """
    if not isinstance(parsed, dict) or not parsed:
        return None

    # 1. Process atomic criteria_evaluations if present for deterministic scoring
    cleaned_criteria = []
    deterministic_score: Optional[int] = None
    raw_criteria = parsed.get("criteria_evaluations")
    if isinstance(raw_criteria, list) and len(raw_criteria) > 0:
        total_score_acc = 0.0
        valid_count = 0
        for item in raw_criteria:
            if isinstance(item, dict):
                crit_text = str(item.get("criterion", "")).strip()
                verdict = str(item.get("verdict", "")).strip().upper()
                quote = item.get("evidence_quote")
                
                # Filter out null, none, n/a, or empty placeholders
                quote_str: Optional[str] = None
                if quote is not None:
                    raw_q = str(quote).strip()
                    if raw_q.lower() not in ("null", "none", "n/a", "na", "", "không có", "không", "none.", "nil"):
                        quote_str = raw_q

                # Strict discrete verdict scoring mapping based on prompt specification
                if verdict == "STRONG_EVIDENCE":
                    s = 1.0
                elif verdict == "PARTIAL_EVIDENCE":
                    s = 0.5
                else:
                    s = 0.0

                total_score_acc += s
                valid_count += 1
                cleaned_criteria.append({
                    "criterion": crit_text,
                    "verdict": verdict if verdict in ("STRONG_EVIDENCE", "PARTIAL_EVIDENCE", "NO_EVIDENCE") else ("STRONG_EVIDENCE" if s >= 0.9 else "PARTIAL_EVIDENCE" if s >= 0.4 else "NO_EVIDENCE"),
                    "score": round(s, 2),
                    "evidence_quote": quote_str
                })

        if valid_count > 0:
            deterministic_score = int(round((total_score_acc / valid_count) * 100.0))

    # 2. Determine final score (deterministic calculation preferred, fallback to explicit score)
    score: Optional[int] = None
    if deterministic_score is not None:
        score = deterministic_score
    else:
        score_val = parsed.get("score")
        if score_val is not None:
            try:
                score_str = str(score_val).strip()
                if not score_str.startswith("<") and any(c.isdigit() for c in score_str):
                    clean_num = re.sub(r'[^0-9.]', '', score_str)
                    if clean_num:
                        score = int(round(float(clean_num)))
            except (ValueError, TypeError):
                score = None

    if score is None or not (0 <= score <= 100):
        return None

    strengths = clean_and_deduplicate_list(parsed.get("strengths", []), max_items=10)
    gaps = clean_and_deduplicate_list(parsed.get("gaps", []), max_items=8)
    quotes = clean_and_deduplicate_list(parsed.get("evidence_quotes", []), max_items=6)
    if not quotes and cleaned_criteria:
        extracted_quotes = [c["evidence_quote"] for c in cleaned_criteria if c.get("evidence_quote")]
        quotes = clean_and_deduplicate_list(extracted_quotes, max_items=6)
    reasoning = str(parsed.get("reasoning_summary", "")).strip()

    result: Dict[str, Any] = {
        "score": score,
        "strengths": strengths,
        "gaps": gaps,
        "evidence_quotes": quotes,
        "reasoning_summary": reasoning
    }
    if cleaned_criteria:
        result["criteria_evaluations"] = cleaned_criteria

    return result


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
                pos = w.get("position", "")
                comp = w.get("company_name", "")
                dur = w.get("duration", "")
                resp = w.get("responsibilities") or w.get("responsabilities") or w.get("description") or ""
                if isinstance(resp, list):
                    resp_str = "\n".join(str(x) for x in resp if x)
                else:
                    resp_str = str(resp).strip() if resp else ""
                header = f"{pos} tại {comp} ({dur})".strip() if (pos or comp) else ""
                if header and resp_str:
                    summary_lines.append(f"{header}:\n{resp_str}")
                elif resp_str:
                    summary_lines.append(resp_str)
                elif header:
                    summary_lines.append(header)
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
            "position_applied": resume.get("position_applied", {}),
            "self_evaluation": resume.get("self_evaluation", ""),
            "basic_information": sanitized_basic_info,
            "skills_and_specialties": resume.get("skills_and_specialties", []),
            "projects": resume.get("projects", []),
            "work_experience_summary": summary_lines,
            "work_experience_details": work_exp_list
        }
