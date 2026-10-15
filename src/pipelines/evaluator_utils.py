"""
Utility functions for data extraction, list deduplication, PII sanitization, and output validation in Resume Evaluator pipeline.
"""
import re
import difflib
from typing import Dict, List, Any, Optional

from src.core.config import IMPORTANCE_WEIGHTS, DEFAULT_IMPORTANCE, MUST_HAVE
from src.core.importance import normalize_importance


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


EMPTY_QUOTE_PLACEHOLDERS = ("null", "none", "n/a", "na", "", "không có", "không", "none.", "nil")

# How close the LLM's echoed criterion text must be to a stored Criterion to take its Importance
IMPORTANCE_MATCH_MIN_RATIO = 0.85


def _normalize_criterion_text(text: str) -> str:
    return " ".join(str(text).split()).casefold()


def match_criterion_importance(criterion: str, importance_map: Dict[str, str]) -> str:
    """
    The Importance of the stored Criterion the LLM's echoed criterion text refers to: an exact match ignoring
    whitespace and case, else the closest text at IMPORTANCE_MATCH_MIN_RATIO or above, else Standard.
    Never by position, since the Criteria Permutation bias test reorders the Criteria.
    """
    target = _normalize_criterion_text(criterion)
    if not target or not importance_map:
        return DEFAULT_IMPORTANCE
    normalized_map = {_normalize_criterion_text(k): v for k, v in importance_map.items()}
    if target in normalized_map:
        return normalize_importance(normalized_map[target])
    best_ratio, best_importance = 0.0, DEFAULT_IMPORTANCE
    for key, importance in normalized_map.items():
        ratio = difflib.SequenceMatcher(None, target, key).ratio()
        if ratio > best_ratio:
            best_ratio, best_importance = ratio, importance
    return normalize_importance(best_importance) if best_ratio >= IMPORTANCE_MATCH_MIN_RATIO else DEFAULT_IMPORTANCE


def validate_category_evaluation(parsed: Any, importance_map: Optional[Dict[str, str]] = None) -> Optional[Dict[str, Any]]:
    """
    Validates that parsed JSON contains valid evaluation data.
    If criteria_evaluations list is present, computes score deterministically from atomic criteria coverage:
    the mean of the Verdicts weighted by each Criterion's Importance from importance_map ({criterion_text:
    importance}). Without a map every Criterion is Standard, i.e. a plain mean.
    Otherwise, validates the numeric score (0-100) and required output fields.
    """
    if not isinstance(parsed, dict) or not parsed:
        return None

    # 1. Process atomic criteria_evaluations if present for deterministic scoring
    cleaned_criteria = []
    all_criteria_quotes: List[str] = []
    deterministic_score: Optional[int] = None
    raw_criteria = parsed.get("criteria_evaluations")
    if isinstance(raw_criteria, list) and len(raw_criteria) > 0:
        total_score_acc = 0.0
        total_weight = 0.0
        for item in raw_criteria:
            if isinstance(item, dict):
                crit_text = str(item.get("criterion", "")).strip()
                verdict = str(item.get("verdict", "")).strip().upper()
                # Current format lists quotes under "evidence_quotes"; older outputs hold one string in "evidence_quote"
                raw_quotes = item.get("evidence_quotes", item.get("evidence_quote"))
                if not isinstance(raw_quotes, list):
                    raw_quotes = [] if raw_quotes is None else [raw_quotes]

                # Filter out null, none, n/a, or empty placeholders
                item_quotes = clean_and_deduplicate_list(
                    [q for q in raw_quotes if q is not None and str(q).strip().lower() not in EMPTY_QUOTE_PLACEHOLDERS],
                    max_items=6
                )
                all_criteria_quotes.extend(item_quotes)
                quote_str: Optional[str] = " | ".join(item_quotes) or None

                # Strict discrete verdict scoring mapping based on prompt specification
                if verdict == "STRONG_EVIDENCE":
                    s = 1.0
                elif verdict == "PARTIAL_EVIDENCE":
                    s = 0.5
                else:
                    s = 0.0

                importance = match_criterion_importance(crit_text, importance_map) if importance_map else DEFAULT_IMPORTANCE
                weight = IMPORTANCE_WEIGHTS[importance]
                total_score_acc += weight * s
                total_weight += weight
                cleaned_criteria.append({
                    "criterion": crit_text,
                    "importance": importance,
                    "verdict": verdict if verdict in ("STRONG_EVIDENCE", "PARTIAL_EVIDENCE", "NO_EVIDENCE") else ("STRONG_EVIDENCE" if s >= 0.9 else "PARTIAL_EVIDENCE" if s >= 0.4 else "NO_EVIDENCE"),
                    "score": round(s, 2),
                    "evidence_quote": quote_str,
                    "evidence_quotes": item_quotes,
                    # The model's reasoning written before the verdict; absent from outputs older than that format
                    "reasoning": str(item.get("reasoning", "")).strip()
                })

        if total_weight > 0:
            deterministic_score = int(round((total_score_acc / total_weight) * 100.0))

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
        quotes = clean_and_deduplicate_list(all_criteria_quotes, max_items=6)
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


def collect_missing_must_haves(dimension_results: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Every must-have Criterion that got NO_EVIDENCE in the reported (median-run) criteria_evaluations, as
    [{"category", "criterion"}]. A Missing Must-Have only informs HR; it never rejects or caps the candidate.
    """
    missing: List[Dict[str, str]] = []
    for cat_key, dim in (dimension_results or {}).items():
        if not isinstance(dim, dict) or dim.get("not_applicable"):
            continue
        for crit in dim.get("criteria_evaluations") or []:
            if (isinstance(crit, dict) and crit.get("importance") == MUST_HAVE
                    and str(crit.get("verdict", "")).upper() == "NO_EVIDENCE"):
                missing.append({"category": cat_key, "criterion": str(crit.get("criterion", "")).strip()})
    return missing


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
