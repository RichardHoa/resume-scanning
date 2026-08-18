"""
Local RAG Export & Summary Helper Utilities
"""
import os
import sys
from datetime import datetime
from typing import Dict, List, Any
from src.core.config import ROOT_DIR


def export_hr_rag_file(
    standard_req: str,
    hidden_req: str,
    decomposed: Dict[str, List[str]],
    output_path: str = "hr_rag.txt"
):
    """Exports a summary detailing how HR requirements are classified into 5 RAG dimensions."""
    lines = [
        "=" * 80,
        "HR RAG REQUIREMENT CLASSIFICATION SUMMARY",
        f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        "=" * 80,
        "\n--- RAW INPUT STANDARD REQUIREMENTS ---",
        standard_req or "None",
        "\n--- RAW INPUT HIDDEN REQUIREMENTS ---",
        hidden_req or "None",
        "\n" + "=" * 80,
        "CLASSIFICATION BY DIMENSION CATEGORY:",
        "=" * 80,
    ]

    cat_names = {
        "seniority_title": "1. SENIORITY_TITLE (Vị trí, cấp bậc & số năm kinh nghiệm)",
        "technical_skills": "2. TECHNICAL_SKILLS (Kỹ năng chuyên môn, công cụ & kiến thức ngành)",
        "work_experience": "3. WORK_EXPERIENCE (Kinh nghiệm công việc & trách nhiệm)",
        "education_certifications": "4. EDUCATION_CERTIFICATIONS (Bằng cấp, chuyên ngành, ngoại ngữ & chứng chỉ)",
        "hidden_culture": "5. HIDDEN_CULTURE (Yêu cầu ẩn, kỹ năng mềm & văn hóa doanh nghiệp)"
    }

    for cat_key, cat_label in cat_names.items():
        items = decomposed.get(cat_key, [])
        lines.append(f"\n[{cat_label}] (Total items: {len(items)})")
        if items:
            for idx, item in enumerate(items, 1):
                lines.append(f"   {idx}. {item}")
        else:
            lines.append("   (No items classified in this category)")

    lines.extend([
        "\n" + "=" * 80,
        "END OF CLASSIFICATION SUMMARY",
        "=" * 80 + "\n"
    ])

    try:
        with open(output_path, "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
        print(f"[LocalRAG] Exported requirement classification to {output_path}", file=sys.stderr)
    except Exception as e:
        print(f"[LocalRAG Error] Could not write {output_path}: {e}", file=sys.stderr)


def get_stored_rag_summary(rag_inst: Any) -> Dict[str, Any]:
    """Returns a structured summary of all RAG criteria stored in the persistent database."""
    categories_dict = {
        "seniority_title": [],
        "technical_skills": [],
        "work_experience": [],
        "education_certifications": [],
        "hidden_culture": []
    }
    for doc in rag_inst.documents:
        raw_cat = str(doc.get("category") or "").strip().lower()
        cat_map = {
            "seniority": "seniority_title",
            "seniority_title": "seniority_title",
            "position": "seniority_title",
            "skills": "technical_skills",
            "technical_skills": "technical_skills",
            "tech_skills": "technical_skills",
            "experience": "work_experience",
            "work_experience": "work_experience",
            "education": "education_certifications",
            "education_certifications": "education_certifications",
            "culture": "hidden_culture",
            "hidden": "hidden_culture",
            "hidden_culture": "hidden_culture"
        }
        cat = cat_map.get(raw_cat, raw_cat)
        if cat in categories_dict:
            categories_dict[cat].append({
                "text": doc.get("text"),
                "type": doc.get("type", "standard")
            })
        else:
            categories_dict["technical_skills"].append({
                "text": doc.get("text"),
                "type": doc.get("type", "standard")
            })

    hr_rag_content = ""
    hr_rag_path = os.path.join(ROOT_DIR, "hr_rag.txt")
    if os.path.exists(hr_rag_path):
        try:
            with open(hr_rag_path, "r", encoding="utf-8") as f:
                hr_rag_content = f.read()
        except Exception:
            pass

    engine_name = "ChromaDB Persistent Vector Store" if rag_inst.collection is not None else "ChromaDB (Pending Install - Run 'pip install chromadb')"

    return {
        "has_stored_rag": rag_inst.has_stored_rag(),
        "total_items": len(rag_inst.documents),
        "db_path": rag_inst.db_path,
        "engine": engine_name,
        "categories": categories_dict,
        "hr_rag_text": hr_rag_content
    }
