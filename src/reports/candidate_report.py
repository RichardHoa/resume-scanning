"""
Candidate evaluation report as a PDF for the HR user: the same view as the /candidates modal (header, Candidate
Feedback without Panelist views, Category cards with each strength next to its resume quote), followed by the
candidate's original resume PDF when one was kept.

The evaluation pages are rendered from candidate_report_template.html with WeasyPrint; the resume pages are
appended unchanged with pypdf.
"""
import io
import os
from datetime import datetime
from typing import Any, Dict, List, Optional

from jinja2 import Environment, FileSystemLoader, select_autoescape
from pypdf import PdfWriter

from src.core.config import MUST_HAVE, NICE_TO_HAVE

TEMPLATE_DIR = os.path.dirname(os.path.abspath(__file__))
TEMPLATE_NAME = "candidate_report_template.html"

# Display order and Vietnamese names, matching CATEGORY_NAMES in src/static/js/modules/criteria-editor.js
CATEGORY_NAMES = {
    "seniority_title": "Vị trí & Số năm kinh nghiệm",
    "technical_skills": "Kỹ năng, Công cụ & Chuyên môn",
    "work_experience": "Kinh nghiệm làm việc, Dự án & Trách nhiệm",
    "education_certifications": "Bằng cấp & Chứng chỉ",
    "hidden_culture": "Yêu cầu ẩn & Văn hóa"
}

FAILED_EVALUATION_LABEL = "Lỗi – cần chạy lại"
SCANNED_RESUME_LABEL = "CV bản scan – không đọc được"
MUST_HAVE_REJECTION_LABEL = "Bị loại – thiếu tiêu chí bắt buộc"

_env = Environment(loader=FileSystemLoader(TEMPLATE_DIR), autoescape=select_autoescape(["html"]))


def _score_color(score: float) -> str:
    if score >= 85:
        return "#059669"
    if score >= 70:
        return "#0284C7"
    if score >= 55:
        return "#D97706"
    return "#DC2626"


def _fill_class(score: float) -> str:
    if score >= 85:
        return "fill-high"
    if score >= 70:
        return "fill-mid"
    if score >= 55:
        return "fill-low"
    return "fill-reject"


def _match(report: Dict[str, Any], score: float) -> Dict[str, str]:
    """The match pill, with the same rules as the /candidates page."""
    if report.get("status") == "error":
        return {"cls": "match-error", "text": FAILED_EVALUATION_LABEL}
    if report.get("status") == "scanned":
        return {"cls": "match-error", "text": SCANNED_RESUME_LABEL}
    if report.get("match_recommendation") == "MUST_HAVE_REJECTED":
        return {"cls": "match-reject", "text": MUST_HAVE_REJECTION_LABEL}
    rec = report.get("match_recommendation") or "POTENTIAL_MATCH"
    if rec == "STRONG_MATCH" or score >= 85:
        return {"cls": "match-strong", "text": "PHÙ HỢP CAO"}
    if rec == "POTENTIAL_MATCH" or score >= 70:
        return {"cls": "match-potential", "text": "CÓ TIỀM NĂNG"}
    if rec == "LOW_MATCH" or score >= 55:
        return {"cls": "match-low", "text": "PHÙ HỢP THẤP"}
    return {"cls": "match-reject", "text": "LOẠI"}


def _evaluated_at(value: Optional[str]) -> str:
    """'HH:MM:SS D/M/YYYY', like the page's vi-VN timestamp."""
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return "Không có"
    return f"{dt:%H:%M:%S} {dt.day}/{dt.month}/{dt.year}"


def _points(value: Any) -> str:
    """Criterion Points as HR reads them: one decimal, without a trailing ".0", like the website's formatPoints."""
    return f"{float(value or 0):.1f}".removesuffix(".0")


def points_label(c: Dict[str, Any]) -> str:
    """
    A Criterion's Criterion Points: earned / max out of its Category's 100, or the bonus a Nice-to-have added, which
    never costs points when missing. Same wording as earnedPointsLabel in src/static/js/modules/criterion-points.js.
    """
    if c.get("importance") != NICE_TO_HAVE:
        return f"{_points(c.get('earned_points'))} / {_points(c.get('max_points'))}"
    if (c.get("earned_points") or 0) > 0:
        return f"+{_points(c.get('earned_points'))}"
    return "+0 · không trừ điểm"


def _criterion_view(c: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "text": c.get("criterion", ""),
        "partial": c.get("verdict") == "PARTIAL_EVIDENCE",
        "must_have": c.get("importance") == MUST_HAVE,
        "points": points_label(c),
        "quotes": c.get("evidence_quotes") or []
    }


def met_criteria(dim: Dict[str, Any]) -> List[Dict[str, Any]]:
    """A Category's criteria judged STRONG or PARTIAL, each with its points and resume quotes."""
    return [
        _criterion_view(c) for c in dim.get("criteria_evaluations") or []
        if c.get("verdict") in ("STRONG_EVIDENCE", "PARTIAL_EVIDENCE")
    ]


def unmet_criteria(dim: Dict[str, Any]) -> List[Dict[str, Any]]:
    """A Category's criteria judged NO_EVIDENCE, each with its points (a Nice-to-have's say it cost nothing)."""
    return [_criterion_view(c) for c in dim.get("criteria_evaluations") or [] if c.get("verdict") == "NO_EVIDENCE"]


def _view(report: Dict[str, Any]) -> Dict[str, Any]:
    """Everything the template shows, already formatted."""
    failed = report.get("status") == "error"
    # A Scanned Resume was never evaluated: no score, no Categories, no feedback
    scanned = report.get("status") == "scanned"
    unscored = failed or scanned
    score = float(report.get("overall_score") or 0)
    basic_name = (report.get("candidate_name") or "").strip()
    email = (report.get("candidate_email") or "").strip()
    if not email and "@" in (report.get("candidate_identifier") or ""):
        email = report["candidate_identifier"]

    categories = []
    if not unscored:
        dims = report.get("dimension_scores") or {}
        for key in CATEGORY_NAMES:
            dim = dims.get(key)
            # A Not Applicable Category got no Criterion from HR's requirements and is never judged
            if not dim or dim.get("not_applicable"):
                continue
            dim_score = float(dim.get("score") or 0)
            categories.append({
                "name": CATEGORY_NAMES[key],
                "weight": f"{(dim.get('weight') or 0.2) * 100:.0f}",
                "score": f"{dim_score:.1f}",
                "fill_class": _fill_class(dim_score),
                "fill_width": min(100, max(5, dim_score)),
                # Shown whenever the evaluator wrote any, whatever the Verdicts
                "strengths": dim.get("strengths") or [],
                "met_criteria": met_criteria(dim),
                "unmet_criteria": unmet_criteria(dim),
                # The Nice-to-haves met pushed the Category past 100, so its rows add up to more than the gauge
                "bonus_capped": bool(dim.get("bonus_capped")),
                "gaps": dim.get("gaps") or []
            })

    # A Must-have Rejection keeps its scores for HR, but the candidate is out; reports from before the gate have none
    rejected = not unscored and report.get("match_recommendation") == "MUST_HAVE_REJECTED"
    must_have_rejection = [] if not rejected else [
        {"criterion": m.get("criterion", ""), "category": CATEGORY_NAMES.get(m.get("category"), "")}
        for m in report.get("must_have_rejection") or [] if isinstance(m, dict)
    ]

    feedback = report.get("candidate_feedback") or {}
    return {
        "name": basic_name or email or report.get("candidate_identifier") or report.get("resume_name") or "Ứng viên",
        "email": email if basic_name else "",
        "failed": failed,
        "failed_categories": [CATEGORY_NAMES.get(k, k) for k in report.get("failed_categories") or []],
        "must_have_rejection": must_have_rejection,
        "scanned": scanned,
        "score": "—" if unscored else f"{score:.1f}",
        # A rejected candidate's score is greyed out: it is shown, but not ranked
        "score_color": "#64748B" if unscored or rejected else _score_color(score),
        "match": _match(report, score),
        "evaluated_at": _evaluated_at(report.get("evaluated_at")),
        "feedback": feedback if not unscored and feedback.get("status") in ("ok", "failed") else None,
        "categories": categories
    }


def build_candidate_report_pdf(report: Dict[str, Any], resume_pdf_path: Optional[str]) -> bytes:
    """The evaluation report PDF, with the resume PDF's pages appended when a path is given."""
    # Imported here so the server still starts on a machine where WeasyPrint's system libraries are missing
    from weasyprint import HTML

    html = _env.get_template(TEMPLATE_NAME).render(**_view(report))
    evaluation_pdf = HTML(string=html, base_url=TEMPLATE_DIR).write_pdf()

    writer = PdfWriter()
    writer.append(io.BytesIO(evaluation_pdf))
    if resume_pdf_path:
        writer.append(resume_pdf_path)
    out = io.BytesIO()
    writer.write(out)
    return out.getvalue()
