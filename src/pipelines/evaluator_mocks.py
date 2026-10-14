"""
Mock data and mock requirement decomposition handlers for Resume Evaluator pipeline.
"""
import json
from typing import Any, Dict, List

from src.core.config import HR_CHECK_ITEMS_KEY


def get_mock_category_response(category: str, language: str = "vietnamese") -> str:
    """Returns mock JSON response string for a given evaluation category."""
    is_english = language.lower() in ("english", "en")
    if is_english:
        mock_data = {
            "seniority_title": {
                "evidence_quotes": ["Worked as Senior Software Engineer for 4 years"],
                "strengths": ["Title and seniority level align well with the target role", "Years of specialized experience meet job requirements"],
                "gaps": ["Team management experience is limited"],
                "reasoning_summary": "Candidate meets the required years of specialized experience for the position.",
                "score": 85
            },
            "technical_skills": {
                "evidence_quotes": ["Skills: Python, PyTorch, Docker, PostgreSQL"],
                "strengths": ["Proficient in Python, FastAPI, and SQL technologies", "Hands-on experience with modern cloud tools"],
                "gaps": ["No explicit experience with Kubernetes mentioned"],
                "reasoning_summary": "Fully covers core technical skills specified in the job description.",
                "score": 90
            },
            "work_experience": {
                "evidence_quotes": ["Built microservice backend handling 10k RPS"],
                "strengths": ["Proven track record in large-scale projects", "Clear project achievements with quantifiable metrics"],
                "gaps": ["Tenure in recent project was relatively short (6 months)"],
                "reasoning_summary": "Work experience is directly relevant to job duties.",
                "score": 82
            },
            "education_certifications": {
                "evidence_quotes": ["BS in Computer Science - VNU-HCM"],
                "strengths": ["Bachelor's Degree in Computer Science", "Relevant technical certifications"],
                "gaps": ["No Master's degree"],
                "reasoning_summary": "Educational background aligns with hiring criteria.",
                "score": 88
            },
            "hidden_culture": {
                "evidence_quotes": ["Active open-source contributor & tech blogger"],
                "strengths": ["Proactive learning and self-improvement attitude", "Strong communication skills in both English and Vietnamese"],
                "gaps": ["May prefer hybrid work over 100% on-site"],
                "reasoning_summary": "Culture assessment indicates high engagement and initiative.",
                "score": 80
            }
        }
        default_resp = {
            "evidence_quotes": ["Extracted from resume context"],
            "strengths": ["Candidate shows good overall foundation"],
            "gaps": ["Additional detailed verification required"],
            "reasoning_summary": "Overall assessment based on preliminary information.",
            "score": 75
        }
    else:
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


def get_mock_scrutiny_response(standard_req: str, hidden_req: str, language: str = "vietnamese", max_questions: int = 5) -> Dict[str, List[Dict[str, str]]]:
    """Generates a mock Implicit Assumption / Clarification Question response via simple keyword heuristics."""
    is_english = language.lower() in ("english", "en")
    vague_terms = ["senior", "junior", "good", "strong", "fast-paced", "flexible", "team player", "cấp cao", "tốt", "linh hoạt"]

    def _find_assumptions(text: str) -> List[Dict[str, str]]:
        text_low = (text or "").lower()
        found = []
        for term in vague_terms:
            if term in text_low:
                if is_english:
                    found.append({
                        "assumption": f"The term '{term}' is not defined with a concrete threshold or example.",
                        "question": f"What specifically does '{term}' mean for this role?"
                    })
                else:
                    found.append({
                        "assumption": f"Thuật ngữ '{term}' chưa được định nghĩa cụ thể.",
                        "question": f"'{term}' cụ thể được hiểu như thế nào cho vị trí này?"
                    })
            if len(found) >= max_questions:
                break
        return found[:max_questions]

    return {
        "standard_requirements": _find_assumptions(standard_req),
        "hidden_requirements": _find_assumptions(hidden_req)
    }


def get_mock_decomposed_requirements(standard_req: str, hidden_req: str) -> Dict[str, List[str]]:
    """Generates mock decomposed requirements dict based on heuristic keyword matching."""
    lines_std = [l.strip() for l in (standard_req or "").split('\n') if l.strip()]
    lines_hid = [l.strip() for l in (hidden_req or "").split('\n') if l.strip()]
    
    # HR Check Items: requirements no resume would show, set aside before the Categories are filled
    check_words = ["tăng ca", "overtime", "ngoài giờ", "đi công tác", "nhận việc ngay", "mức lương", "salary"]
    is_check_item = lambda line: any(w in line.lower() for w in check_words)

    result = {
        "seniority_title": [],
        "technical_skills": [],
        "work_experience": [],
        "education_certifications": [],
        "hidden_culture": [l for l in lines_hid if not is_check_item(l)],
        HR_CHECK_ITEMS_KEY: [l for l in lines_std + lines_hid if is_check_item(l)]
    }

    for line in (l for l in lines_std if not is_check_item(l)):
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


def get_mock_candidate_feedback() -> Dict[str, Any]:
    """Canned Vietnamese Candidate Feedback content, in the shape the Review Panel produces (without status/timing)."""
    return {
        "summary": "Ứng viên có nền tảng chuyên môn phù hợp với vị trí và kinh nghiệm làm việc liên quan, nhưng kinh nghiệm dẫn dắt đội nhóm còn hạn chế. Các thành viên hội đồng đồng ý rằng ứng viên đáp ứng phần lớn yêu cầu chuẩn; điểm còn bàn cãi là mức độ phù hợp với văn hóa làm việc nhịp độ cao.",
        "strengths": [
            "Kỹ năng chuyên môn cốt lõi đáp ứng yêu cầu của vị trí",
            "Kinh nghiệm làm việc liên quan trực tiếp đến công việc",
            "Có bằng cấp phù hợp với lĩnh vực tuyển dụng"
        ],
        "weaknesses": [
            "Kinh nghiệm quản lý hoặc dẫn dắt đội nhóm còn ít",
            "Chưa thể hiện rõ thành tích định lượng trong các dự án",
            "Thiếu bằng chứng về khả năng làm việc trong môi trường nhịp độ cao"
        ],
        "panelist_views": {
            "leadership": "Ứng viên chưa có vai trò quản lý chính thức, nhưng đã chủ động đảm nhận một số phần việc quan trọng. Tôi đồng ý với thành viên Chuyên môn rằng nền tảng kỹ năng vững, và đây là cơ sở tốt để phát triển năng lực lãnh đạo.",
            "domain_expertise": "Kỹ năng chuyên môn của ứng viên khớp với phần lớn yêu cầu chuẩn. Tôi không hoàn toàn đồng ý với thành viên Con người & Văn hóa: hồ sơ có dấu hiệu làm việc nhóm tốt qua các dự án chung.",
            "people_culture": "Hồ sơ cho thấy ứng viên làm việc nhóm ổn định, nhưng chưa có bằng chứng rõ về khả năng thích nghi với môi trường nhịp độ cao. Tôi đồng ý với thành viên Lãnh đạo rằng cần kiểm tra thêm trong phỏng vấn."
        }
    }
