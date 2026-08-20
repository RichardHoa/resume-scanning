"""
Mock data and mock requirement decomposition handlers for Resume Evaluator pipeline.
"""
import json
from typing import Dict, List


def get_mock_category_response(category: str) -> str:
    """Returns mock JSON response string for a given evaluation category."""
    mock_data = {
        "seniority_title": {
            "evidence_quotes": ["Worked as Senior Software Engineer for 4 years"],
            "strengths": ["Chức danh và cấp bậc rất phù hợp với vị trí tuyển dụng", "Số năm kinh nghiệm trong vị trí chuyên môn tương ứng đáp ứng đúng yêu cầu tuyển dụng"],
            "gaps": ["Kinh nghiệm quản lý nhóm còn khiêm tốn"],
            "reasoning_summary": "Ứng viên đáp ứng tốt yêu cầu về số năm kinh nghiệm cho vị trí yêu cầu.",
            "score": 85
        },
        "technical_skills": {
            "evidence_quotes": ["Skills: Python, PyTorch, Docker, PostgreSQL"],
            "strengths": ["Thành thạo các công nghệ Python, FastAPI và SQL", "Có kinh nghiệm thực tế làm việc với các công cụ cloud hiện đại"],
            "gaps": ["Chưa thể hiện rõ kinh nghiệm làm việc với Kubernetes"],
            "reasoning_summary": "Đáp ứng đầy đủ các kỹ năng cốt lõi được yêu cầu trong JD.",
            "score": 90
        },
        "work_experience": {
            "evidence_quotes": ["Built microservice backend handling 10k RPS"],
            "strengths": ["Có thành tích tốt trong các dự án quy mô lớn", "Kết quả dự án rõ ràng, có chỉ số đo lường cụ thể"],
            "gaps": ["Thời gian gắn bó tại dự án gần nhất tương đối ngắn (6 tháng)"],
            "reasoning_summary": "Kinh nghiệm thực tế sát với yêu cầu công việc.",
            "score": 82
        },
        "education_certifications": {
            "evidence_quotes": ["BS in Computer Science - VNU-HCM"],
            "strengths": ["Bằng Cử nhân Chuyên ngành Khoa học Máy tính", "Có các chứng chỉ kỹ thuật chuyên môn phù hợp"],
            "gaps": ["Chưa có bằng Thạc sĩ"],
            "reasoning_summary": "Bằng cấp phù hợp với yêu cầu tuyển dụng.",
            "score": 88
        },
        "hidden_culture": {
            "evidence_quotes": ["Active open-source contributor & tech blogger"],
            "strengths": ["Tinh thần chủ động học hỏi và tự nâng cao trình độ", "Kỹ năng giao tiếp tốt bằng cả tiếng Anh và tiếng Việt"],
            "gaps": ["Có thể ưu tiên hình thức làm việc hybrid hơn làm việc 100% tại văn phòng"],
            "reasoning_summary": "Đánh giá văn hóa cho thấy mức độ gắn kết và chủ động cao.",
            "score": 80
        }
    }
    default_resp = {
        "evidence_quotes": ["Extracted from resume context"],
        "strengths": ["Ứng viên có nền tảng tổng thể phù hợp"],
        "gaps": ["Cần bổ sung và xác minh thêm thông tin chi tiết"],
        "reasoning_summary": "Đánh giá tổng quan dựa trên thông tin sơ bộ.",
        "score": 75
    }
    return json.dumps(mock_data.get(category, default_resp), ensure_ascii=False)


def get_mock_decomposed_requirements(standard_req: str, hidden_req: str) -> Dict[str, List[str]]:
    """Generates mock decomposed requirements dict based on heuristic keyword matching."""
    lines_std = [l.strip() for l in (standard_req or "").split('\n') if l.strip()]
    lines_hid = [l.strip() for l in (hidden_req or "").split('\n') if l.strip()]
    
    result = {
        "seniority_title": [],
        "technical_skills": [],
        "work_experience": [],
        "education_certifications": [],
        "hidden_culture": lines_hid or []
    }
    
    for line in lines_std:
        line_low = line.lower()
        if any(w in line_low for w in ["năm", "year", "senior", "junior", "level", "vị trí", "chức danh", "c&b", "kinh nghiệm"]):
            result["seniority_title"].append(line)
        if any(w in line_low for w in ["skill", "python", "java", "sql", "kỹ năng", "thành thạo", "công nghệ"]):
            result["technical_skills"].append(line)
        if any(w in line_low for w in ["bằng", "đại học", "degree", "bachelor", "chứng chỉ", "certificate", "toeic", "ielts"]):
            result["education_certifications"].append(line)
        if any(w in line_low for w in ["công việc", "nhiệm vụ", "mô tả", "trách nhiệm", "kinh nghiệm", "dự án"]):
            result["work_experience"].append(line)

    return result
