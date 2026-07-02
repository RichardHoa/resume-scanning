#!/usr/bin/env python3
import os
import sys
import json
import argparse

# Fallback OCR Helper
def run_fallback_ocr(page):
    import io
    pix = page.get_pixmap(dpi=150)
    img_bytes = pix.tobytes("png")
    
    # Try EasyOCR first
    try:
        import easyocr
        reader = easyocr.Reader(['vi', 'en'])
        results = reader.readtext(img_bytes)
        
        blocks = []
        for i, (bbox, text, conf) in enumerate(results):
            x0 = bbox[0][0]
            y0 = bbox[0][1]
            x1 = bbox[2][0]
            y1 = bbox[2][1]
            blocks.append((x0, y0, x1, y1, text + "\n", i, 0))
        return blocks, pix.width
    except ImportError:
        pass
    except Exception as e:
        print(f"Warning: EasyOCR failed: {e}. Trying pytesseract fallback...", file=sys.stderr)
        
    # Try pytesseract
    try:
        import pytesseract
        from PIL import Image
        img = Image.open(io.BytesIO(img_bytes))
        data = pytesseract.image_to_data(img, output_type=pytesseract.Output.DICT, lang='vie+eng')
        
        blocks = []
        n_boxes = len(data['text'])
        for i in range(n_boxes):
            text = data['text'][i].strip()
            if text:
                x0 = data['left'][i]
                y0 = data['top'][i]
                x1 = x0 + data['width'][i]
                y1 = y0 + data['height'][i]
                blocks.append((x0, y0, x1, y1, text + " \n", i, 0))
        return blocks, pix.width
    except ImportError:
        pass
    except Exception as e:
        print(f"Warning: pytesseract failed: {e}", file=sys.stderr)
        
    raise RuntimeError("No OCR libraries (easyocr, pytesseract) available or working.")


# Robust PDF Text Extraction Function
def extract_text_from_pdf(pdf_path):
    """
    Extracts text from a PDF file using multiple fallbacks:
    1. pymupdf4llm  - layout-agnostic markdown extraction (handles 1-col, 2-col, mixed layouts)
    2. fitz (PyMuPDF) - with layout-aware column sorting and OCR fallback
    3. pdfplumber
    4. pypdf
    """
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"File not found at {pdf_path}")

    text = ""
    missing_libs = []
    attempted_libs = []

    # Try pymupdf4llm first — converts PDF to clean Markdown, handles any column layout robustly
    try:
        import pymupdf4llm
        attempted_libs.append("pymupdf4llm")
        md_text = pymupdf4llm.to_markdown(pdf_path)
        if md_text.strip():
            print(f"  [pymupdf4llm] Successfully extracted text as Markdown.", file=sys.stderr)
            return md_text
    except ImportError:
        missing_libs.append("pymupdf4llm")
    except Exception as e:
        print(f"Warning: pymupdf4llm failed: {e}. Trying fallback...", file=sys.stderr)

    # Try PyMuPDF (fitz) with layout-aware sorting
    try:
        import fitz
        attempted_libs.append("pymupdf (fitz)")
        doc = fitz.open(pdf_path)
        pages_text = []
        for page_idx, page in enumerate(doc):
            rect = page.rect
            W = rect.width
            blocks = page.get_text("blocks")
            
            # Check if the page is empty/scanned
            has_text = any(b[6] == 0 and b[4].strip() for b in blocks)
            
            used_ocr = False
            if not has_text:
                print(f"Page {page_idx+1} has no digital text. Attempting OCR...", file=sys.stderr)
                try:
                    # 1. Try PyMuPDF native Tesseract integration
                    tp = page.get_textpage_ocr(flags=0, full=True)
                    blocks = page.get_text("blocks", textpage=tp)
                    has_text = any(b[6] == 0 and b[4].strip() for b in blocks)
                    if has_text:
                        used_ocr = True
                except Exception as ocr_err:
                    pass
                
                # 2. Try Python fallbacks
                if not used_ocr:
                    try:
                        blocks, W = run_fallback_ocr(page)
                        used_ocr = True
                    except Exception as fallback_err:
                        print(f"OCR fallback failed on page {page_idx+1}: {fallback_err}", file=sys.stderr)
            
            # Filter and clean text blocks
            text_blocks = []
            for b in blocks:
                if b[6] == 0:  # text block
                    txt = b[4].strip()
                    if txt:
                        text_blocks.append(b)
            
            # Sort blocks by y0 (top to bottom) first
            text_blocks.sort(key=lambda x: x[1])
            
            # Group blocks separated by spanning (full-width) blocks (width > 60% of page width)
            sections = []
            current_section = []
            for b in text_blocks:
                x0, y0, x1, y1, txt, block_no, block_type = b
                block_width = x1 - x0
                is_spanning = block_width > (0.6 * W)
                if is_spanning:
                    if current_section:
                        sections.append((False, current_section))
                        current_section = []
                    sections.append((True, [b]))
                else:
                    current_section.append(b)
            if current_section:
                sections.append((False, current_section))
                
            page_lines = []
            for is_span, sec_blocks in sections:
                if is_span:
                    page_lines.append(sec_blocks[0][4])
                else:
                    # Two-column section: separate into left and right columns
                    left_col = []
                    right_col = []
                    mid_x = W / 2
                    for b in sec_blocks:
                        x0, y0, x1, y1, txt, block_no, block_type = b
                        center_x = (x0 + x1) / 2
                        if center_x < mid_x:
                            left_col.append(b)
                        else:
                            right_col.append(b)
                    
                    left_col.sort(key=lambda x: x[1])
                    right_col.sort(key=lambda x: x[1])
                    for b in left_col:
                        page_lines.append(b[4])
                    for b in right_col:
                        page_lines.append(b[4])
            
            page_text = "\n".join(page_lines)
            if page_text.strip():
                pages_text.append(page_text)
                
        text = "\n\n".join(pages_text)
        if text.strip():
            return text
    except ImportError:
        missing_libs.append("pymupdf (fitz)")
    except Exception as e:
        print(f"Warning: PyMuPDF failed: {e}. Trying fallback...", file=sys.stderr)

    # Try pdfplumber
    try:
        import pdfplumber
        attempted_libs.append("pdfplumber")
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
        missing_libs.append("pdfplumber")
    except Exception as e:
        print(f"Warning: pdfplumber failed: {e}. Trying fallback...", file=sys.stderr)

    # Try pypdf
    try:
        from pypdf import PdfReader
        attempted_libs.append("pypdf")
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
        missing_libs.append("pypdf")
    except Exception as e:
        print(f"Warning: pypdf failed: {e}", file=sys.stderr)

    # Print diagnostic information
    if len(missing_libs) == 3:
        raise ImportError(
            "Error: No PDF extraction libraries ('pdfplumber', 'pymupdf', 'pypdf') could be imported. "
            "Please install the dependencies first using:\n  pip install -r requirements.txt"
        )
        
    if not text.strip():
        error_msg = (
            f"Could not extract any text from {pdf_path}. "
            f"We successfully tried using {', '.join(attempted_libs)} but they returned empty text. "
            "This usually happens if the PDF is a scanned image (non-searchable PDF)."
        )
        if missing_libs:
            error_msg += f"\nNote: The following libraries were missing and could not be tried: {', '.join(missing_libs)}"
        raise ValueError(error_msg)

    return text


def parse_args():
    parser = argparse.ArgumentParser(description="Vietnamese Resume Extractor using Qwen2.5 7B-Instruct")
    parser.add_argument("--pdf", type=str, help="Path to a single PDF resume file")
    parser.add_argument("--dir", type=str, help="Path to a directory containing PDF resumes to scan")
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
    parser.add_argument("--output", type=str, help="Path to save the JSON output file (or output directory if --dir is used)")
    parser.add_argument("--no-json-mode", action="store_true",
                        help="Disable JSON-mode (response_format=json_object) for API inference. Use if your server does not support it.")
    return parser.parse_args()

def get_system_prompt():
    return """Bạn là một chuyên viên tuyển dụng AI chịu trách nhiệm trích xuất thông tin có cấu trúc từ sơ yếu lý lịch (CV) tiếng Việt.
Đọc kỹ toàn bộ văn bản CV và trả về đúng định dạng JSON sau (không có bất kỳ văn bản nào ngoài JSON):

{
  "position_applied": {
    "title": "Vị trí ứng tuyển hoặc chức danh chuyên môn chính xác nhất rút ra từ CV",
    "level": "Cấp bậc: 'junior' (<2 năm), 'mid-level' (2–5 năm), 'senior' (>5 năm), 'leadership' (quản lý/trưởng phòng trở lên), hoặc 'unknown'"
  },
  "self_evaluation": "Tóm tắt định hướng nghề nghiệp hoặc phần tự giới thiệu của ứng viên. Để trống nếu không có.",
  "skills_and_specialties": [
    "Kỹ năng hoặc chuyên môn (không bao gồm ngoại ngữ)"
  ],
  "languages": [
    {
      "language": "Tên ngoại ngữ",
      "proficiency": "Mức độ thông thạo. Để trống nếu không có.",
      "certificates": [
        {
          "name": "Tên chứng chỉ ngoại ngữ",
          "score": "Điểm số. Để trống nếu không có.",
          "issuing_organization": "Tổ chức cấp. Để trống nếu không có.",
          "duration": "Thời gian cấp hoặc thời hạn. Để trống nếu không có."
        }
      ]
    }
  ],
  "certifications": [
    {
      "name": "Tên chứng chỉ chuyên môn (không phải ngoại ngữ, không phải bằng đại học)",
      "issuing_organization": "Tổ chức cấp. Để trống nếu không có.",
      "duration": "Thời gian cấp hoặc thời hạn. Để trống nếu không có."
    }
  ],
  "work_experience": [
    {
      "company_name": "Tên công ty",
      "company_description": "Mô tả ngắn về công ty: quy mô, lĩnh vực, loại khách hàng, v.v. Để trống nếu không có.",
      "position": "Chức danh công việc chính thức tại công ty đó",
      "duration": "Thời gian làm việc",
      "responsibilities": "Mô tả đầy đủ nhiệm vụ, trách nhiệm và thành tựu. Sử dụng định dạng danh sách phân cấp với '- ' cho mục chính, '+ ' cho mục con."
    }
  ],
  "basic_information": {
    "email": "Email liên hệ",
    "phone": "Số điện thoại",
    "location": "Nơi ở hiện tại hoặc quê quán. Để trống nếu không có.",
    "other_info": "Thông tin liên hệ bổ sung (LinkedIn, website, Skype, v.v.). Để trống nếu không có."
  },
  "education_background": [
    {
      "university_name": "Tên trường hoặc cơ sở đào tạo",
      "degree": "Bằng cấp (dịch sang tiếng Việt nếu ghi bằng tiếng Anh)",
      "field_of_study": "Ngành học hoặc chuyên ngành (dịch sang tiếng Việt nếu cần). Để trống nếu không rõ.",
      "graduation_year": "Năm tốt nghiệp hoặc trạng thái hoàn thành",
      "gpa": "Điểm GPA hoặc xếp loại học lực (dịch sang tiếng Việt nếu cần). Để trống nếu không có."
    }
  ]
}

LƯU Ý:
1. Chỉ trả về JSON hợp lệ, không có giải thích hay markdown.
2. Trích xuất đầy đủ tất cả kinh nghiệm làm việc — mỗi vị trí/dự án riêng biệt là một phần tử riêng trong mảng `work_experience`.
3. Không bỏ sót hoặc tóm tắt nội dung `responsibilities`; thu thập toàn bộ chi tiết nhiệm vụ từ CV.
4. Ngoại ngữ thuộc mục `languages`, không thuộc `skills_and_specialties`.
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
                "company_description": "Công ty phát triển phần mềm và dịch vụ IT",
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

def load_local_model(model_name):
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
    return model, tokenizer

def run_local_inference(resume_text, model, tokenizer):
    messages = [
        {"role": "system", "content": get_system_prompt()},
        {"role": "user", "content": f"Dưới đây là văn bản trích xuất từ CV của ứng viên:\n\n{resume_text}"}
    ]
    
    text = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
        enable_thinking=False
    )
    
    model_inputs = tokenizer([text], return_tensors="pt").to(model.device)
    
    print("Generating structured output...", file=sys.stderr)
    generated_ids = model.generate(
        **model_inputs,
        max_new_tokens=100000,
        do_sample=True,
        temperature=0.7,
        top_p=0.8,
        top_k=20,
        min_p=0.0,
        repetition_penalty=1.0,
        pad_token_id=tokenizer.eos_token_id
    )
    
    generated_ids = [
        output_ids[len(input_ids):] for input_ids, output_ids in zip(model_inputs.input_ids, generated_ids)
    ]
    
    response = tokenizer.batch_decode(generated_ids, skip_special_tokens=True)[0]
    return response

def get_api_client(api_base, api_key):
    try:
        from openai import OpenAI
    except ImportError:
        print("Error: openai library is required for API inference.", file=sys.stderr)
        print("Install it with: pip install openai", file=sys.stderr)
        sys.exit(1)
        
    return OpenAI(base_url=api_base, api_key=api_key)

def run_api_inference(resume_text, client, model_name, json_mode=True):
    messages = [
        {"role": "system", "content": get_system_prompt()},
        {"role": "user", "content": f"Dưới đây là văn bản trích xuất từ CV của ứng viên:\n\n{resume_text}"}
    ]

    kwargs = dict(
        model=model_name,
        messages=messages,
        temperature=0.7,
        top_p=0.8,
        presence_penalty=1.5,
        max_tokens=100000,
    )

    # JSON mode constrains the model to only emit valid JSON tokens,
    # eliminating stray text, markdown fences, or incomplete structures.
    if json_mode:
        try:
            kwargs["response_format"] = {"type": "json_object"}
            response = client.chat.completions.create(**kwargs)
            print("  [API] JSON mode active.", file=sys.stderr)
        except Exception as e:
            # Server may not support response_format; fall back to plain completion
            print(f"  Warning: JSON mode not supported ({e}), retrying without it.", file=sys.stderr)
            del kwargs["response_format"]
            response = client.chat.completions.create(**kwargs)
    else:
        response = client.chat.completions.create(**kwargs)

    return response.choices[0].message.content

def extract_json_substring(text):
    """
    Strips out thinking blocks (e.g. <think>...</think>), markdown code blocks,
    and isolates the actual JSON string by finding the first '{' and last '}'.
    """
    cleaned = text.strip()
    
    # Remove thinking tags if present
    import re
    cleaned = re.sub(r'<think>.*?</think>', '', cleaned, flags=re.DOTALL)
    cleaned = re.sub(r'^Thinking Process:.*?(?=\n\s*\{)', '', cleaned, flags=re.DOTALL | re.IGNORECASE)
    
    # Find the start of the JSON object
    start_idx = cleaned.find('{')
    if start_idx == -1:
        return cleaned
        
    # Find the end of the JSON object
    end_idx = cleaned.rfind('}')
    if end_idx == -1:
        return cleaned[start_idx:]
        
    return cleaned[start_idx:end_idx + 1]


def repair_truncated_json(text):
    """
    Best-effort repair of a JSON string truncated mid-stream (e.g. due to token limits).

    Strategy:
    1. Single forward pass tracking in-string state, bracket nesting stack, and
       the last position where the JSON was in a structurally 'safe' state
       (i.e., after a complete value, closing bracket, or comma — not mid-key or mid-value).
    2. Truncate to that safe position, then close all open brackets in LIFO order.
    3. Pad any missing top-level required keys with empty defaults so downstream
       code always receives a structurally complete object.
    """
    if not text or not text.strip():
        return text

    in_string = False
    escape_next = False
    stack = []       # 'o' = object, 'a' = array
    # Track the last position that is safe to cut at:
    # after a closed string VALUE (not a key), after ']' or '}', or after ','
    # We use a small state machine inside objects to distinguish key vs value strings.
    # States inside an object: 'expect_key', 'expect_colon', 'expect_value', 'after_value'
    # Inside arrays: always 'value' context.
    ctx_stack = []   # mirrors stack, holds ('o','expect_key') or ('a','value') etc.
    last_safe_end = 0  # byte index just past the last safe cut point

    i = 0
    n = len(text)
    while i < n:
        ch = text[i]

        if escape_next:
            escape_next = False
            i += 1
            continue

        if ch == '\\' and in_string:
            escape_next = True
            i += 1
            continue

        if ch == '"':
            if in_string:
                # String just closed
                in_string = False
                # Determine if this closed string was a VALUE (safe cut) or a KEY (not safe)
                ctx = ctx_stack[-1] if ctx_stack else None
                if ctx and ctx[0] == 'o':
                    if ctx[1] == 'expect_value':
                        # Closed a value string — safe cut
                        last_safe_end = i + 1
                        ctx_stack[-1] = ('o', 'after_value')
                    elif ctx[1] == 'expect_key':
                        # Closed a key string — NOT a safe cut yet
                        ctx_stack[-1] = ('o', 'expect_colon')
                elif ctx and ctx[0] == 'a':
                    # Array element value closed — safe cut
                    last_safe_end = i + 1
            else:
                # String opening
                in_string = True
                # Determine expected role
                ctx = ctx_stack[-1] if ctx_stack else None
                if ctx and ctx[0] == 'o' and ctx[1] == 'after_value':
                    # After comma was consumed, now starting next key
                    ctx_stack[-1] = ('o', 'expect_key')
            i += 1
            continue

        if in_string:
            i += 1
            continue

        # Outside string
        if ch == '{':
            stack.append('o')
            ctx_stack.append(('o', 'expect_key'))
        elif ch == '[':
            stack.append('a')
            ctx_stack.append(('a', 'value'))
        elif ch == '}':
            if stack:
                stack.pop()
                ctx_stack.pop()
            last_safe_end = i + 1
            # After closing an object, parent context advances
            if ctx_stack:
                parent = ctx_stack[-1]
                if parent[0] == 'o' and parent[1] == 'expect_value':
                    ctx_stack[-1] = ('o', 'after_value')
        elif ch == ']':
            if stack:
                stack.pop()
                ctx_stack.pop()
            last_safe_end = i + 1
            if ctx_stack:
                parent = ctx_stack[-1]
                if parent[0] == 'o' and parent[1] == 'expect_value':
                    ctx_stack[-1] = ('o', 'after_value')
        elif ch == ':':
            if ctx_stack and ctx_stack[-1] == ('o', 'expect_colon'):
                ctx_stack[-1] = ('o', 'expect_value')
        elif ch == ',':
            last_safe_end = i + 1
            if ctx_stack:
                parent = ctx_stack[-1]
                if parent[0] == 'o':
                    ctx_stack[-1] = ('o', 'expect_key')
                # array stays in 'value' context
        # primitives (digits, true/false/null) advance state when we hit next delimiter,
        # so we handle them implicitly via the comma/bracket/brace paths above.

        i += 1

    # Truncate to last safe position (drops any dangling key, partial value, or mid-string)
    safe_text = text[:last_safe_end]

    # Recompute the bracket stack for the truncated text
    stack2 = []
    in_str2 = False
    esc2 = False
    for ch in safe_text:
        if esc2:
            esc2 = False
            continue
        if ch == '\\' and in_str2:
            esc2 = True
            continue
        if ch == '"':
            in_str2 = not in_str2
            continue
        if in_str2:
            continue
        if ch == '{':
            stack2.append('o')
        elif ch == '[':
            stack2.append('a')
        elif ch in ('}', ']'):
            if stack2:
                stack2.pop()

    # Close all open structures
    closing = ''.join('}' if s == 'o' else ']' for s in reversed(stack2))
    repaired = safe_text.rstrip().rstrip(',') + closing

    # Pad missing top-level required keys with empty defaults
    REQUIRED_KEYS = {
        "position_applied":       '{"title": "", "level": "unknown"}',
        "self_evaluation":        '""',
        "skills_and_specialties": '[]',
        "languages":              '[]',
        "certifications":         '[]',
        "work_experience":        '[]',
        "basic_information":      '{"email": "", "phone": "", "location": "", "other_info": ""}',
        "education_background":   '[]',
    }
    try:
        obj = json.loads(repaired)
        for key, default_str in REQUIRED_KEYS.items():
            if key not in obj:
                obj[key] = json.loads(default_str)
        return json.dumps(obj, ensure_ascii=False)
    except json.JSONDecodeError:
        # Repair failed — return what we have and let the caller handle it
        return repaired


def main():
    args = parse_args()
    
    # Validation of mutually exclusive/required inputs
    if not args.pdf and not args.dir:
        print("Error: You must specify either --pdf or --dir.", file=sys.stderr)
        sys.exit(1)
    if args.pdf and args.dir:
        print("Error: You cannot specify both --pdf and --dir. Please choose one.", file=sys.stderr)
        sys.exit(1)
        
    # Initialize shared model/client resources once
    model = None
    tokenizer = None
    client = None
    
    if not args.mock:
        if args.provider == "local":
            model, tokenizer = load_local_model(args.model_name)
        elif args.provider == "api":
            client = get_api_client(args.api_base, args.api_key)
            
    if args.pdf:
        # Processing a single PDF file
        try:
            print(f"Extracting text from {args.pdf}...", file=sys.stderr)
            resume_text = extract_text_from_pdf(args.pdf)
            print(f"Extracted {len(resume_text)} characters.", file=sys.stderr)
        except Exception as e:
            print(f"Error: {e}", file=sys.stderr)
            sys.exit(1)
        
        if args.mock:
            result = run_mock_extraction(resume_text)
        elif args.provider == "local":
            result = run_local_inference(resume_text, model, tokenizer)
        else:
            result = run_api_inference(resume_text, client, args.model_name,
                                       json_mode=not args.no_json_mode)
            
        clean_result = extract_json_substring(result)
            
        try:
            parsed_json = json.loads(clean_result)
            formatted_json = json.dumps(parsed_json, ensure_ascii=False, indent=2)
        except json.JSONDecodeError:
            print("Warning: Model output is not valid JSON. Attempting auto-repair...", file=sys.stderr)
            repaired = repair_truncated_json(clean_result)
            try:
                parsed_json = json.loads(repaired)
                formatted_json = json.dumps(parsed_json, ensure_ascii=False, indent=2)
                print("  Auto-repair succeeded.", file=sys.stderr)
            except json.JSONDecodeError:
                print("  Auto-repair failed. Saving raw output.", file=sys.stderr)
                formatted_json = clean_result
                if args.output:
                    if args.output.lower().endswith(".json"):
                        txt_path = args.output[:-5] + ".txt"
                    else:
                        txt_path = args.output + ".txt"
                    try:
                        with open(txt_path, "w", encoding="utf-8") as f:
                            f.write(result)
                        print(f"Saved raw model output to {txt_path}", file=sys.stderr)
                    except Exception as save_err:
                        print(f"Warning: Failed to save raw model output to {txt_path}: {save_err}", file=sys.stderr)
            
        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(formatted_json)
            print(f"Successfully saved JSON extraction to {args.output}", file=sys.stderr)
        else:
            print(formatted_json)
            
    else:
        # Processing a directory of PDF files
        if not args.output:
            print("Error: --output is required when scanning a directory using --dir.", file=sys.stderr)
            sys.exit(1)
            
        if not os.path.isdir(args.dir):
            print(f"Error: Input directory {args.dir} does not exist or is not a directory.", file=sys.stderr)
            sys.exit(1)
            
        os.makedirs(args.output, exist_ok=True)
        
        pdf_files = [f for f in os.listdir(args.dir) if f.lower().endswith('.pdf')]
        if not pdf_files:
            print(f"No PDF files found in {args.dir}.", file=sys.stderr)
            sys.exit(0)
            
        pdf_files.sort()
        print(f"Found {len(pdf_files)} PDF files in {args.dir}. Starting batch processing...", file=sys.stderr)
        
        for idx, filename in enumerate(pdf_files, start=1):
            pdf_path = os.path.join(args.dir, filename)
            output_filename = os.path.splitext(filename)[0] + ".json"
            output_path = os.path.join(args.output, output_filename)
            
            print(f"\n[{idx}/{len(pdf_files)}] Processing {filename}...", file=sys.stderr)
            try:
                resume_text = extract_text_from_pdf(pdf_path)
                print(f"  Extracted {len(resume_text)} characters.", file=sys.stderr)
                
                if args.mock:
                    result = run_mock_extraction(resume_text)
                elif args.provider == "local":
                    result = run_local_inference(resume_text, model, tokenizer)
                else:
                    result = run_api_inference(resume_text, client, args.model_name,
                                               json_mode=not args.no_json_mode)
                    
                clean_result = extract_json_substring(result)
                    
                try:
                    parsed_json = json.loads(clean_result)
                    formatted_json = json.dumps(parsed_json, ensure_ascii=False, indent=2)
                except json.JSONDecodeError:
                    print(f"  Warning: Model output for {filename} is not valid JSON. Attempting auto-repair...", file=sys.stderr)
                    repaired = repair_truncated_json(clean_result)
                    try:
                        parsed_json = json.loads(repaired)
                        formatted_json = json.dumps(parsed_json, ensure_ascii=False, indent=2)
                        print(f"  Auto-repair succeeded for {filename}.", file=sys.stderr)
                    except json.JSONDecodeError:
                        print(f"  Auto-repair failed for {filename}. Saving raw output.", file=sys.stderr)
                        formatted_json = clean_result
                        if output_path.lower().endswith(".json"):
                            txt_path = output_path[:-5] + ".txt"
                        else:
                            txt_path = output_path + ".txt"
                        try:
                            with open(txt_path, "w", encoding="utf-8") as f:
                                f.write(result)
                            print(f"  Saved raw model output to {txt_path}", file=sys.stderr)
                        except Exception as save_err:
                            print(f"  Warning: Failed to save raw model output to {txt_path}: {save_err}", file=sys.stderr)
                    
                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(formatted_json)
                print(f"  Successfully saved JSON extraction to {output_path}", file=sys.stderr)
                
            except Exception as e:
                print(f"  Error processing {filename}: {e}", file=sys.stderr)
                
        print("\nBatch processing completed.", file=sys.stderr)

if __name__ == "__main__":
    main()
