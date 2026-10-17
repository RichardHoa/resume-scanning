"""
LLM Provider abstractions: vLLM Server and Mock Mode handlers.
"""
import os
import sys

# Ensure repository root is in sys.path for 'src' package imports
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import json
from typing import NamedTuple, Optional
from src.providers import vllm_client
from src.core.json_utils import load_extraction_json_schema
from src.prompts.extractor_prompts import get_system_prompt


class PageImage(NamedTuple):
    """One PDF page shown to the extractor in Combined Extraction: its 1-based number and its JPEG as a data URL."""
    page: int
    data_url: str


def extraction_messages(resume_text: str, language: str = "vietnamese", page_images: Optional[list[PageImage]] = None) -> list:
    """
    The chat messages of the extraction call: the system prompt, then the resume's markdown. With page images
    (Combined Extraction), the user message shows each page's image first, then the same markdown.
    """
    resume_prompt = f"Below is the extracted markdown text from the candidate's resume:\n\n{resume_text}"
    if not page_images:
        return [
            {"role": "system", "content": get_system_prompt(language)},
            {"role": "user", "content": resume_prompt}
        ]
    content = []
    for image in page_images:
        content.append({"type": "text", "text": f"PDF page {image.page}:"})
        content.append({"type": "image_url", "image_url": {"url": image.data_url}})
    content.append({"type": "text", "text": resume_prompt})
    return [
        {"role": "system", "content": get_system_prompt(language, combined=True)},
        {"role": "user", "content": content}
    ]


def prompt_log_text(messages: list) -> str:
    """The extraction messages as prompt-log text, each page image written as a placeholder instead of its bytes."""
    def content_text(content) -> str:
        if isinstance(content, str):
            return content
        return "\n".join(part["text"] if part["type"] == "text" else "[page image]" for part in content)
    return "\n\n".join(f"--- {m['role'].upper()} PROMPT ---\n{content_text(m['content'])}" for m in messages)


def run_vllm_inference(
    resume_text: str, model_name: str, vllm_url: str, language: str = "vietnamese", resume_name: Optional[str] = None,
    page_images: Optional[list[PageImage]] = None
) -> str:
    """Run extraction via a running vLLM server, from the resume text alone or with its page images (Combined Extraction)."""
    print("Generating structured output (vLLM)...", file=sys.stderr)
    return vllm_client.chat(
        vllm_url, model_name, extraction_messages(resume_text, language, page_images),
        json_schema=load_extraction_json_schema(), timeout=600, step=vllm_client.EXTRACTION_STEP, resume_name=resume_name
    ).content


def run_mock_extraction(resume_text: str, language: str = "vietnamese") -> str:
    print("=== MOCK MODE ACTIVATED ===", file=sys.stderr)
    print("--- Extracted Raw Text Preview ---", file=sys.stderr)
    lines = resume_text.split("\n")
    for line in lines[:30]:
        print(f"  {line}", file=sys.stderr)
    if len(lines) > 30:
        print(f"  ... [Truncated {len(lines)-30} lines] ...", file=sys.stderr)
    print("----------------------------------", file=sys.stderr)

    mock_data = {
        "position_applied": {
            "title": "Nhân viên phát triển phần mềm"
        },
        "self_evaluation": "Lập trình viên nhiệt huyết với kinh nghiệm phát triển hệ thống web, mong muốn đóng góp cho các dự án lớn.",
        "skills": [
            "Ngôn ngữ lập trình: Python, SQL",
            "Công cụ: Docker, Docker Compose, Git, GitLab CI/CD",
            "Cơ sở dữ liệu: PostgreSQL"
        ],
        "languages": [
            {
                "language": "English",
                "proficiency": "Thành thạo",
                "certificates": [
                    {
                        "name": "TOEIC",
                        "score": "640",
                        "issuing_organization": "ETS",
                        "duration": "2023 - Present"
                    }
                ]
            }
        ],
        "certifications": [],
        "work_experience": [
            {
                "company_name": "Công ty Công nghệ ABC",
                "company_description": "Công ty phát triển phần mềm và dịch vụ IT",
                "position": "Lập trình viên Python",
                "duration": "06/2022 - Hiện tại",
                "responsibilities": "Phát triển và bảo trì hệ thống backend, tối ưu hóa truy vấn cơ sở dữ liệu."
            }
        ],
        "basic_information": {
            "full_name": "Nguyễn Văn A",
            "email": "example@email.com",
            "phone": "0987654321",
            "location": "Hà Nội",
            "other_info": "github.com/example"
        },
        "education_background": [
            {
                "university_name": "Đại học Bách Khoa Hà Nội",
                "degree": "Kỹ sư",
                "field_of_study": "Khoa học Máy tính",
                "graduation_year": "2022"
            }
        ],
        "projects": [
            {
                "project_name": "Hệ thống Quản lý Nhân sự HRMS",
                "description": "Xây dựng hệ thống quản lý thông tin nhân viên, chấm công và tính lương sử dụng Django và React.",
                "duration": "09/2023 - 12/2023"
            }
        ]
    }
    return json.dumps(mock_data, ensure_ascii=False, indent=2)
