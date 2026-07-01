#!/usr/bin/env python3
import os
import sys
import json
import argparse

# Robust PDF Text Extraction Function
def extract_text_from_pdf(pdf_path):
    """
    Extracts text from a PDF file using multiple fallbacks:
    1. pdfplumber
    2. fitz (PyMuPDF)
    3. pypdf
    """
    if not os.path.exists(pdf_path):
        print(f"Error: File not found at {pdf_path}", file=sys.stderr)
        sys.exit(1)

    text = ""
    
    # Try pdfplumber
    try:
        import pdfplumber
        with pdfplumber.open(pdf_path) as pdf:
            pages_text = []
            for i, page in enumerate(pdf.pages):
                page_text = page.extract_text()
                if page_text:
                    pages_text.append(page_text)
            text = "\n\n".join(pages_text)
            if text.strip():
                return text
    except ImportError:
        pass
    except Exception as e:
        print(f"Warning: pdfplumber failed: {e}. Trying fallback...", file=sys.stderr)

    # Try PyMuPDF (fitz)
    try:
        import fitz
        doc = fitz.open(pdf_path)
        pages_text = []
        for page in doc:
            page_text = page.get_text()
            if page_text:
                pages_text.append(page_text)
        text = "\n\n".join(pages_text)
        if text.strip():
            return text
    except ImportError:
        pass
    except Exception as e:
        print(f"Warning: PyMuPDF failed: {e}. Trying fallback...", file=sys.stderr)

    # Try pypdf
    try:
        from pypdf import PdfReader
        reader = PdfReader(pdf_path)
        pages_text = []
        for page in reader.pages:
            page_text = page.extract_text()
            if page_text:
                pages_text.append(page_text)
        text = "\n\n".join(pages_text)
        if text.strip():
            return text
    except ImportError:
        pass
    except Exception as e:
        print(f"Warning: pypdf failed: {e}", file=sys.stderr)

    if not text.strip():
        print(f"Error: Could not extract any text from {pdf_path}", file=sys.stderr)
        sys.exit(1)

    return text

def parse_args():
    parser = argparse.ArgumentParser(description="Vietnamese Resume Extractor using Qwen2.5 7B-Instruct")
    parser.add_argument("--pdf", type=str, required=True, help="Path to the PDF resume file")
    parser.add_argument("--provider", type=str, choices=["local", "api"], default="local",
                        help="Model inference provider: 'local' (Hugging Face transformers) or 'api' (OpenAI-compatible server)")
    parser.add_argument("--model-name", type=str, default="Qwen/Qwen2.5-7B-Instruct",
                        help="Model repository name or path (for local) or model identifier (for api)")
    parser.add_argument("--api-base", type=str, default="http://localhost:8000/v1",
                        help="API base URL (only used if provider is 'api')")
    parser.add_argument("--api-key", type=str, default="token-none",
                        help="API key (only used if provider is 'api')")
    parser.add_argument("--mock", action="store_true",
                        help="Mock run: performs text extraction and returns mock JSON output without loading the model")
    parser.add_argument("--output", type=str, help="Path to save the JSON output (prints to stdout if not specified)")
    return parser.parse_args()

def get_system_prompt():
    return """Bạn là một chuyên viên tuyển dụng AI (Hiring Assistant Agent) chịu trách nhiệm trích xuất thông tin có cấu trúc từ sơ yếu lý lịch (CV) tiếng Việt.
Nhiệm vụ của bạn là đọc kỹ văn bản CV và trích xuất thông tin thành định dạng JSON chuẩn.

Hãy tuân thủ nghiêm ngặt cấu trúc JSON sau đây:
{
  "position_applied": {
    "title": "Tên vị trí ứng tuyển hoặc công việc chính (ví dụ: Nhân viên Hành chính Nhân sự, Lập trình viên Python, ...)",
    "level": "Cấp bậc tương ứng. Chỉ chọn một trong các giá trị sau: 'junior', 'mid-level', 'senior', 'leadership', 'unknown'"
  },
  "self_evaluation": "Tóm tắt định hướng nghề nghiệp hoặc phần tự giới thiệu bản thân của ứng viên. Nếu không có, để trống.",
  "skills_and_specialties": [
    "Kỹ năng hoặc chuyên môn trích xuất được (ví dụ: Python, Quản lý thời gian, Kế toán tổng hợp, ...)"
  ],
  "work_experience": [
    {
      "company_name": "Tên công ty hoạt động",
      "location": "Địa điểm làm việc (ví dụ: Hà Nội, TP.HCM, ...). Nếu không có, để trống.",
      "position": "Chức danh đảm nhận tại công ty đó",
      "duration": "Thời gian làm việc (ví dụ: 01/2009 - Hiện tại hoặc 2021 - 2023)",
      "responsibilities": "Mô tả ngắn gọn về nhiệm vụ, công việc chính hoặc thành tựu đạt được"
    }
  ],
  "basic_information": {
    "email": "Email liên hệ",
    "phone": "Số điện thoại liên hệ",
    "location": "Nơi ở hiện tại hoặc quê quán",
    "other_info": "Thông tin liên hệ bổ sung như LinkedIn, Website cá nhân, Skype, v.v. Nếu không có, để trống."
  },
  "education_background": [
    {
      "university_name": "Tên trường đại học, cao đẳng hoặc cơ sở đào tạo",
      "degree": "Bằng cấp đạt được (ví dụ: Cử nhân, Thạc sĩ, Kỹ sư, Bằng nghề, ...)",
      "field_of_study": "Ngành học hoặc chuyên ngành đào tạo",
      "graduation_year": "Năm tốt nghiệp hoặc trạng thái hoàn thành"
    }
  ]
}

LƯU Ý QUAN TRỌNG:
1. Đảm bảo toàn bộ kết quả trả về là một JSON hợp lệ và CHỈ chứa JSON (không có block giải thích ngoài lề, không viết ```json ... ```).
2. Hãy cố gắng suy luận chính xác cấp bậc (level) dựa trên số năm kinh nghiệm và chức danh:
   - junior: < 2 năm kinh nghiệm, thực tập sinh, nhân viên mới.
   - mid-level: 2-5 năm kinh nghiệm, nhân viên có kinh nghiệm.
   - senior: > 5 năm kinh nghiệm, chuyên viên cao cấp, team lead.
   - leadership: Trưởng phòng (Manager), Giám đốc (Director), Trưởng bộ phận (Head of), v.v.
   - unknown: Nếu không thể xác định.
3. Giữ nguyên ngôn ngữ tiếng Việt của nội dung trích xuất từ CV.
"""

def run_mock_extraction(resume_text):
    print("=== MOCK MODE ACTIVATED ===", file=sys.stderr)
    print("--- Extracted Raw Text Preview ---", file=sys.stderr)
    lines = resume_text.split("\n")
    for line in lines[:30]:
        print(f"  {line}", file=sys.stderr)
    if len(lines) > 30:
        print(f"  ... [Truncated {len(lines)-30} lines] ...", file=sys.stderr)
    print("----------------------------------", file=sys.stderr)
    
    # Return a template mock JSON
    mock_data = {
        "position_applied": {
            "title": "Nhân viên phát triển phần mềm",
            "level": "mid-level"
        },
        "self_evaluation": "Lập trình viên nhiệt huyết với kinh nghiệm phát triển hệ thống web, mong muốn đóng góp cho các dự án lớn.",
        "skills_and_specialties": ["Python", "Django", "SQL", "Git", "Giao tiếp tiếng Anh"],
        "work_experience": [
            {
                "company_name": "Công ty Công nghệ ABC",
                "location": "Hà Nội, Việt Nam",
                "position": "Lập trình viên Python",
                "duration": "06/2022 - Hiện tại",
                "responsibilities": "Phát triển và bảo trì hệ thống backend, tối ưu hóa truy vấn cơ sở dữ liệu."
            }
        ],
        "basic_information": {
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
        ]
    }
    return json.dumps(mock_data, ensure_ascii=False, indent=2)

def run_local_inference(resume_text, model_name):
    print(f"Loading local model and tokenizer for: {model_name}...", file=sys.stderr)
    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except ImportError:
        print("Error: PyTorch and Transformers libraries are required for local inference.", file=sys.stderr)
        print("Install them with: pip install torch transformers accelerate", file=sys.stderr)
        sys.exit(1)
        
    # Check GPU availability
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Using device: {device}", file=sys.stderr)
    
    tokenizer = AutoTokenizer.from_pretrained(model_name)
    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        torch_dtype="auto",
        device_map="auto"
    )
    
    messages = [
        {"role": "system", "content": get_system_prompt()},
        {"role": "user", "content": f"Dưới đây là văn bản trích xuất từ CV của ứng viên:\n\n{resume_text}"}
    ]
    
    text = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True
    )
    
    model_inputs = tokenizer([text], return_tensors="pt").to(model.device)
    
    print("Generating structured output...", file=sys.stderr)
    generated_ids = model.generate(
        **model_inputs,
        max_new_tokens=2048,
        temperature=0.1,
        top_p=0.9
    )
    
    generated_ids = [
        output_ids[len(input_ids):] for input_ids, output_ids in zip(model_inputs.input_ids, generated_ids)
    ]
    
    response = tokenizer.batch_decode(generated_ids, skip_special_tokens=True)[0]
    return response

def run_api_inference(resume_text, model_name, api_base, api_key):
    print(f"Querying API server ({api_base}) with model {model_name}...", file=sys.stderr)
    try:
        from openai import OpenAI
    except ImportError:
        print("Error: openai library is required for API inference.", file=sys.stderr)
        print("Install it with: pip install openai", file=sys.stderr)
        sys.exit(1)
        
    client = OpenAI(base_url=api_base, api_key=api_key)
    
    messages = [
        {"role": "system", "content": get_system_prompt()},
        {"role": "user", "content": f"Dưới đây là văn bản trích xuất từ CV của ứng viên:\n\n{resume_text}"}
    ]
    
    response = client.chat.completions.create(
        model=model_name,
        messages=messages,
        temperature=0.1,
        max_tokens=2048
    )
    
    return response.choices[0].message.content

def main():
    args = parse_args()
    
    # 1. Extract text from PDF
    print(f"Extracting text from {args.pdf}...", file=sys.stderr)
    resume_text = extract_text_from_pdf(args.pdf)
    print(f"Extracted {len(resume_text)} characters.", file=sys.stderr)
    
    # 2. Get LLM response
    if args.mock:
        result = run_mock_extraction(resume_text)
    elif args.provider == "local":
        result = run_local_inference(resume_text, args.model_name)
    else:
        result = run_api_inference(resume_text, args.model_name, args.api_base, args.api_key)
        
    # Clean up the output in case the model added markdown fences
    clean_result = result.strip()
    if clean_result.startswith("```"):
        # Remove leading fence
        lines = clean_result.split("\n")
        if lines[0].startswith("```"):
            lines = lines[1:]
        if lines[-1].startswith("```"):
            lines = lines[:-1]
        clean_result = "\n".join(lines).strip()
        
    # Validate if it's valid JSON
    try:
        parsed_json = json.loads(clean_result)
        formatted_json = json.dumps(parsed_json, ensure_ascii=False, indent=2)
    except json.JSONDecodeError:
        print("Warning: Model output is not valid JSON.", file=sys.stderr)
        print("Raw output below:", file=sys.stderr)
        formatted_json = clean_result
        
    # 3. Output results
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(formatted_json)
        print(f"Successfully saved JSON extraction to {args.output}", file=sys.stderr)
    else:
        print(formatted_json)

if __name__ == "__main__":
    main()
