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

from src.core.config import MUST_HAVE

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


def met_criteria(dim: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    A Category's criteria judged STRONG or PARTIAL, each with its resume quotes. Reports made before per-criterion
    results were saved have none.
    """
    return [
        {
            "text": c.get("criterion", ""),
            "partial": c.get("verdict") == "PARTIAL_EVIDENCE",
            # Reports made before Criterion Importance have none, and show no tag
            "must_have": c.get("importance") == MUST_HAVE,
            "quotes": c.get("evidence_quotes") or []
        }
        for c in dim.get("criteria_evaluations") or []
        if c.get("verdict") in ("STRONG_EVIDENCE", "PARTIAL_EVIDENCE")
    ]


def _view(report: Dict[str, Any]) -> Dict[str, Any]:
    """Everything the template shows, already formatted."""
    failed = report.get("status") == "error"
    score = float(report.get("overall_score") or 0)
    basic_name = (report.get("candidate_name") or "").strip()
    email = (report.get("candidate_email") or "").strip()
    if not email and "@" in (report.get("candidate_identifier") or ""):
        email = report["candidate_identifier"]

    categories = []
    if not failed:
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
                "gaps": dim.get("gaps") or []
            })

    # Missing Must-Haves inform HR only; older reports have none
    missing_must_haves = [] if failed else [
        {"criterion": m.get("criterion", ""), "category": CATEGORY_NAMES.get(m.get("category"), "")}
        for m in report.get("missing_must_haves") or [] if isinstance(m, dict)
    ]

    feedback = report.get("candidate_feedback") or {}
    return {
        "name": basic_name or email or report.get("candidate_identifier") or report.get("resume_name") or "Ứng viên",
        "email": email if basic_name else "",
        "failed": failed,
        "failed_categories": [CATEGORY_NAMES.get(k, k) for k in report.get("failed_categories") or []],
        "missing_must_haves": missing_must_haves,
        "ocr": bool(report.get("ocr_applied") or report.get("intensive_hr_review_required")),
        "score": "—" if failed else f"{score:.1f}",
        "score_color": "#64748B" if failed else _score_color(score),
        "match": _match(report, score),
        "evaluated_at": _evaluated_at(report.get("evaluated_at")),
        "feedback": feedback if not failed and feedback.get("status") in ("ok", "failed") else None,
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
