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
    1. fitz (PyMuPDF) - with layout-aware column sorting and OCR fallback
    2. pdfplumber
    3. pypdf
    """
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"File not found at {pdf_path}")

    text = ""
    missing_libs = []
    attempted_libs = []
    
    # Try PyMuPDF (fitz) with layout-aware sorting first
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
    return parser.parse_args()

def get_system_prompt():
    return """Bạn là một chuyên viên tuyển dụng AI (Hiring Assistant Agent) chịu trách nhiệm trích xuất thông tin có cấu trúc từ sơ yếu lý lịch (CV) tiếng Việt.
Nhiệm vụ của bạn là đọc kỹ văn bản CV và trích xuất thông tin thành định dạng JSON chuẩn.

Hãy tuân thủ nghiêm ngặt cấu trúc JSON sau đây:
{
  "position_applied": {
    "title": "Tên vị trí ứng tuyển hoặc công việc chính (ví dụ: Nhân viên Hành chính Nhân sự, Lập trình viên Python, ...). LƯU Ý: Hãy đọc toàn bộ CV (bao gồm cả tóm tắt mục tiêu, kinh nghiệm gần đây, và các câu đầu tiên của CV) để tìm ra vị trí công việc cụ thể nhất (ví dụ: 'iOS Developer', 'Chuyên viên C&B'). Tránh dùng các từ chung chung như 'Nhân viên' hay 'Chuyên viên' nếu CV có ghi rõ chức danh chuyên môn hoặc vị trí cụ thể.",
    "level": "Cấp bậc tương ứng. Chỉ chọn một trong các giá trị sau: 'junior', 'mid-level', 'senior', 'leadership', 'unknown'"
  },
  "self_evaluation": "Tóm tắt định hướng nghề nghiệp hoặc phần tự giới thiệu bản thân của ứng viên. Nếu không có, để trống.",
  "skills_and_specialties": [
    "Kỹ năng hoặc chuyên môn trích xuất được (ví dụ: Python, Quản lý thời gian, Kế toán tổng hợp, ...). LƯU Ý: Không đưa ngoại ngữ (tiếng Anh, tiếng Nhật, v.v.) vào danh sách này."
  ],
  "languages": [
    {
      "language": "Tên ngoại ngữ (ví dụ: Tiếng Anh, Tiếng Nhật, ...)",
      "proficiency": "Mức độ thông thạo hoặc mô tả khả năng ngôn ngữ (ví dụ: Thành thạo, Giao tiếp tốt, Bản xứ, ...). Nếu không có, để trống.",
      "certificates": [
        {
          "name": "Tên chứng chỉ ngoại ngữ (ví dụ: TOEIC, IELTS, TOEFL, ...)",
          "score": "Điểm số hoặc mức điểm đạt được (ví dụ: 525, 6.5, ...). Nếu không có, để trống.",
          "issuing_organization": "Tổ chức cấp chứng chỉ (ví dụ: IIG VIET NAM, British Council, ...). Nếu không có, để trống.",
          "duration": "Thời gian/năm cấp hoặc thời hạn (ví dụ: 08/2017 - 12/2018 hoặc 2017). Nếu không có, để trống."
        }
      ]
    }
  ],
  "certifications": [
    {
      "name": "Tên chứng chỉ chuyên môn hoặc các chứng chỉ khác không phải ngoại ngữ (ví dụ: Chuyên viên kế toán tin học, Quản trị nhân sự chuyên nghiệp, ...)",
      "issuing_organization": "Tổ chức cấp chứng chỉ (ví dụ: Trường Đại học Kinh tế TP. HCM, ...). Nếu không có, để trống.",
      "duration": "Thời gian/năm cấp hoặc thời hạn. Nếu không có, để trống."
    }
  ],
  "work_experience": [
    {
      "company_name": "Tên công ty hoạt động",
      "company_description": "Mô tả ngắn gọn về công ty bao gồm quy mô (scale/scope, ví dụ: quy mô hơn 1600 nhân viên, scope: 500+), lĩnh vực hoạt động, đối tác/loại khách hàng (ví dụ: FMCG client), hoặc bất kỳ thông tin mô tả nào khác về công ty hoặc quy mô dự án được ghi trong CV. Nếu không có, để trống.",
      "position": "Chức danh đảm nhận tại công ty đó. LƯU Ý: Chỉ điền chức danh công việc chính thức (ví dụ: 'Nhân viên C&B', 'Lập trình viên iOS'). Tuyệt đối KHÔNG gộp thông tin quy mô, phạm vi công việc (ví dụ: 'Scope: 500+', 'Scope: 4000-5000') hay thông tin phân loại khách hàng (ví dụ: 'FMCG CLIENT') vào trường này. Các thông tin này phải được đưa vào trường `company_description`.",
      "duration": "Thời gian làm việc (ví dụ: 01/2009 - Hiện tại hoặc 2021 - 2023)",
      "responsibilities": "Mô tả chi tiết nhiệm vụ, trách nhiệm, công việc chính hoặc thành tựu đạt được. Bạn phải thu thập toàn bộ các chi tiết nhiệm vụ và trách nhiệm được ghi trong CV. Định dạng chuỗi này tuân thủ cấu trúc phân cấp danh sách như sau:\n- Mỗi nhiệm vụ chính bắt đầu bằng dấu '- ' và kết thúc bằng xuống dòng '\\n'.\n- Nếu trong nhiệm vụ chính có danh sách các đầu việc con (danh sách cấp 2), mỗi đầu việc con bắt đầu bằng dấu '+ ' và kết thúc bằng xuống dòng '\\n'.\n- Nếu trong đầu việc con tiếp tục có danh sách con nhỏ hơn (danh sách cấp 3), bắt đầu bằng dấu '++ ' và kết thúc bằng xuống dòng '\\n'.\nVí dụ:\n- Quản lý hợp đồng lao động và dữ liệu nhân viên:\\n  + Theo dõi, kiểm tra dữ liệu chấm công và quản lý loại ngày nghỉ trong năm của nhân viên tại hơn 100 siêu thị trên toàn quốc.\\n  + Thực hiện báo cáo..."
    }
  ],
  "basic_information": {
    "email": "Email liên hệ",
    "phone": "Số điện thoại liên hệ",
    "location": "Nơi ở hiện tại hoặc quê quán. LƯU Ý: Nếu CV không ghi nơi ở/quê quán/địa chỉ, tuyệt đối để trống (chuỗi rỗng), không được tự ý điền thông tin khác như số điện thoại vào trường này.",
    "other_info": "Thông tin liên hệ bổ sung như LinkedIn, Website cá nhân, Skype, v.v. Nếu không có, để trống."
  },
  "education_background": [
    {
      "university_name": "Tên trường đại học, cao đẳng hoặc cơ sở đào tạo",
      "degree": "Bằng cấp đạt được (ví dụ: Cử nhân, Thạc sĩ, Kỹ sư, Bằng nghề, ...). Nếu trong CV ghi bằng tiếng Anh, hãy dịch sang tiếng Việt phù hợp (ví dụ: 'Bachelor's Degree' dịch thành 'Cử nhân').",
      "field_of_study": "Ngành học hoặc chuyên ngành đào tạo. LƯU Ý: Nếu trong CV ghi bằng tiếng Anh, hãy dịch sang tiếng Việt phù hợp (ví dụ: 'Information Technology' dịch thành 'Công nghệ thông tin'). Nếu CV không có chuyên ngành học cụ thể, hoặc chỉ ghi đề mục chung không rõ ràng (ví dụ: 'Học vấn & Chứng chỉ'), hãy để trống (chuỗi rỗng) chứ không tự ý điền.",
      "graduation_year": "Năm tốt nghiệp hoặc trạng thái hoàn thành",
      "gpa": "Điểm trung bình tích lũy GPA (ví dụ: 2.87/4.0 hoặc 7.5/10). Nếu CV ghi xếp loại bằng chữ bằng tiếng Anh (ví dụ: 'very good grades' hoặc 'Good Standing'), hãy chuyển đổi/dịch sang tiếng Việt tương ứng (ví dụ: 'Giỏi', 'Khá'). Nếu không có trong CV, để trống."
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
3. Ngoại ngữ (như Tiếng Anh, Tiếng Nhật, ...) KHÔNG phải là một phần của kỹ năng (skills_and_specialties), hãy đưa toàn bộ thông tin ngoại ngữ và chứng chỉ ngoại ngữ liên quan vào mục 'languages'.
4. Giữ nguyên ngôn ngữ tiếng Việt của nội dung trích xuất từ CV. Ưu tiên dịch các tên chuyên ngành học vấn, bằng cấp, và xếp loại học lực từ tiếng Anh sang tiếng Việt tương ứng (ví dụ: 'Information Technology' -> 'Công nghệ thông tin', 'Bachelor's Degree' -> 'Cử nhân', 'very good grades' -> 'Giỏi') để đảm bảo tính nhất quán của kết quả bằng tiếng Việt.
5. Trích xuất đầy đủ và toàn bộ (COMPLETENESS): Bạn phải thu thập toàn bộ các chi tiết nhiệm vụ và trách nhiệm (`responsibilities`) được ghi trong CV. Tuyệt đối không được bỏ sót, bỏ qua, tóm tắt hoặc gộp chung các đầu việc lại làm mất thông tin chi tiết. Đọc kỹ từng cột và từng phần của CV để không bỏ sót các phần văn bản.
6. Tất cả các vị trí công việc (All Work Experiences): Nếu một ứng viên có nhiều vị trí công việc hoặc dự án khác nhau tại cùng một công ty hoặc tại các công ty khác nhau, hãy trích xuất chúng thành các phần tử riêng biệt trong mảng `work_experience`. Tuyệt đối không được bỏ sót hoặc gộp chúng lại thành một phần tử duy nhất nếu chúng được liệt kê riêng biệt trong CV.
7. Phân biệt rõ ràng giữa bằng cấp giáo dục (education_background) và chứng chỉ chuyên môn (certifications): Tuyệt đối không được tự ý kết hợp chức danh công việc của ứng viên ở đầu CV (ví dụ: 'Chuyên viên C&B') với tên trường đại học/cao đẳng để tạo thành một chứng chỉ giả định trong mục `certifications`. Chỉ đưa vào mục `certifications` những chứng chỉ đào tạo thực sự (như chứng chỉ nghề, chứng chỉ hoàn thành khóa học ngắn hạn) được ghi rõ ràng trong CV.
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

def get_api_client(api_base, api_key):
    try:
        from openai import OpenAI
    except ImportError:
        print("Error: openai library is required for API inference.", file=sys.stderr)
        print("Install it with: pip install openai", file=sys.stderr)
        sys.exit(1)
        
    return OpenAI(base_url=api_base, api_key=api_key)

def run_api_inference(resume_text, client, model_name):
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
            result = run_api_inference(resume_text, client, args.model_name)
            
        clean_result = result.strip()
        if clean_result.startswith("```"):
            lines = clean_result.split("\n")
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines[-1].startswith("```"):
                lines = lines[:-1]
            clean_result = "\n".join(lines).strip()
            
        try:
            parsed_json = json.loads(clean_result)
            formatted_json = json.dumps(parsed_json, ensure_ascii=False, indent=2)
        except json.JSONDecodeError:
            print("Warning: Model output is not valid JSON.", file=sys.stderr)
            print("Raw output below:", file=sys.stderr)
            formatted_json = clean_result
            
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
                    result = run_api_inference(resume_text, client, args.model_name)
                    
                clean_result = result.strip()
                if clean_result.startswith("```"):
                    lines = clean_result.split("\n")
                    if lines[0].startswith("```"):
                        lines = lines[1:]
                    if lines[-1].startswith("```"):
                        lines = lines[:-1]
                    clean_result = "\n".join(lines).strip()
                    
                try:
                    parsed_json = json.loads(clean_result)
                    formatted_json = json.dumps(parsed_json, ensure_ascii=False, indent=2)
                except json.JSONDecodeError:
                    print(f"  Warning: Model output for {filename} is not valid JSON.", file=sys.stderr)
                    formatted_json = clean_result
                    
                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(formatted_json)
                print(f"  Successfully saved JSON extraction to {output_path}", file=sys.stderr)
                
            except Exception as e:
                print(f"  Error processing {filename}: {e}", file=sys.stderr)
                
        print("\nBatch processing completed.", file=sys.stderr)

if __name__ == "__main__":
    main()
