#!/usr/bin/env python3
import os
import sys
import json
import argparse
import time

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
    parser = argparse.ArgumentParser(description="Vietnamese Resume Extractor (Local Inference)")
    parser.add_argument("--pdf", type=str, help="Path to a single PDF resume file")
    parser.add_argument("--dir", type=str, help="Path to a directory containing PDF resumes to scan")
    parser.add_argument("--model-name", type=str, default="Qwen/Qwen2.5-7B-Instruct",
                        help="Model repository name or local path")
    parser.add_argument("--mock", action="store_true",
                        help="Mock run: performs text extraction and returns mock JSON output without loading the model")
    parser.add_argument("--output", type=str, help="Path to save the JSON output file (or output directory if --dir is used)")
    parser.add_argument("--arr", type=str,
                        help="Comma-separated list of resume numbers to process (e.g., --arr=6,7,8,10)")
    parser.add_argument("--image", action="store_true",
                        help="Vision-only mode: send only PDF page images to the model, skip extracted text entirely. "
                             "Use for resumes with complex multi-column or sidebar layouts where text extraction scrambles content.")
    parser.add_argument("--approved", action="store_true",
                        help="Only process PDFs that have a corresponding ground truth JSON in approved_jsons")
    return parser.parse_args()

def get_system_prompt():
    return """You are an AI resume extraction specialist. Your only job is to extract structured information from a resume and return it as valid JSON matching the schema below. Output nothing else — no markdown, no prose, no code fences.

EXTRACTION RULES:
1. EXTRACT ONLY — never modify, rephrase, translate, or infer beyond what is explicitly written. Copy text character-for-character as it appears on the resume. Only use inference when the resume genuinely omits a required field (e.g. position title not stated).
2. LANGUAGE SELECTION — if the resume contains two languages (e.g. Vietnamese + English), first determine the dominant language: if the resume is primarily Vietnamese, favor Vietnamese text throughout; if primarily English, favor English text. Apply this consistently to all fields.
3. IMAGE SOURCE — when resume page images are provided, read directly from the images (the authoritative source). Extracted text is a supplementary hint only and may be out of order due to multi-column layouts; cross-reference the image to correctly pair dates, positions, and responsibilities.

JSON SCHEMA:
{
  "position_applied": {
    "title": "Job title as written on the resume, or inferred from context if not stated explicitly.",
    "level": "Classify based on total years of experience (earliest job start to most recent job): <2 years = 'junior', 2-5 years = 'mid-level', >5 years = 'senior', manager/team-lead or above = 'leadership', insufficient data = 'unknown'. Values: junior | mid-level | senior | leadership | unknown"
  },
  "self_evaluation": "Personal summary or career objective section verbatim. Empty string if not present.",
  "skills_and_specialties": ["Skills, tools, technologies, and competencies extracted from the entire resume — including skills sections, work experience, projects, and education. Do not include languages. Extract all, omit none."],
  "languages": [
    {
      "language": "Language name",
      "proficiency": "Proficiency level as written. Empty string if not stated.",
      "certificates": [
        {
          "name": "Certificate name",
          "score": "Score as written. Empty string if not stated.",
          "issuing_organization": "Issuing organization as written. Empty string if not stated.",
          "duration": "Validity period as written. Empty string if not stated."
        }
      ]
    }
  ],
  "certifications": [
    {
      "name": "Professional certification name (exclude language certificates and academic degrees)",
      "issuing_organization": "Issuing organization as written. Empty string if not stated.",
      "duration": "Validity period as written. Empty string if not stated."
    }
  ],
  "work_experience": [
    {
      "company_name": "Company name as written",
      "company_description": "Company size, industry, client type, etc. as written. Empty string if not stated.",
      "position": "Job title at this company as written",
      "duration": "Employment period (start month/year - end month/year) as written. Use the image to correctly match dates to each job in multi-column layouts.",
      "responsibilities": "All duties, responsibilities, and achievements verbatim. Extract completely — do not summarize or omit. Use '- ' for main items, '+ ' for sub-items."
    }
  ],
  "basic_information": {
    "email": "Email address as written",
    "phone": "Phone number as written",
    "location": "Residence or hometown as written. Empty string if not stated.",
    "other_info": "LinkedIn, website, Skype, GitHub, etc. as written. Empty string if not stated."
  },
  "education_background": [
    {
      "university_name": "Institution name as written",
      "degree": "Degree as written",
      "field_of_study": "Field of study as written. Empty string if not stated.",
      "graduation_year": "Graduation year or status as written",
      "gpa": "GPA or classification as written. Empty string if not stated."
    }
  ],
  "projects": [
    {
      "project_name": "Project name as written",
      "description": "Description, technologies, results, and role as written. Empty string if not stated.",
      "duration": "Project period (start month/year - end month/year) as written. Empty string if not stated."
    }
  ]
}
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

def load_local_model(model_name, image_mode=False):
    print(f"Loading local model for: {model_name}...", file=sys.stderr)
    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer, AutoProcessor
    except ImportError:
        print("Error: PyTorch and Transformers libraries are required for local inference.", file=sys.stderr)
        print("Install them with: pip install torch transformers accelerate", file=sys.stderr)
        sys.exit(1)
        
    # Check GPU availability
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Using device: {device}", file=sys.stderr)

    if image_mode:
        # VLMs require AutoModelForVision2Seq or AutoModelForImageTextToText — 
        # AutoModelForCausalLM silently drops vision tensors (pixel_values, image_grid_thw, etc.) causing empty output.
        model = None
        # 1. Try AutoModelForImageTextToText
        try:
            from transformers import AutoModelForImageTextToText
            model = AutoModelForImageTextToText.from_pretrained(
                model_name,
                torch_dtype="auto",
                device_map="auto"
            )
            print(f"  [Vision] Loaded model with AutoModelForImageTextToText.", file=sys.stderr)
        except Exception as e:
            print(f"  Warning: AutoModelForImageTextToText failed ({e}). Trying AutoModelForVision2Seq...", file=sys.stderr)
            
        # 2. Try AutoModelForVision2Seq
        if model is None:
            try:
                from transformers import AutoModelForVision2Seq
                model = AutoModelForVision2Seq.from_pretrained(
                    model_name,
                    torch_dtype="auto",
                    device_map="auto"
                )
                print(f"  [Vision] Loaded model with AutoModelForVision2Seq.", file=sys.stderr)
            except Exception as e:
                print(f"  Warning: AutoModelForVision2Seq failed ({e}). Trying Qwen2VLForConditionalGeneration...", file=sys.stderr)
                
        # 3. Try Qwen2VLForConditionalGeneration
        if model is None:
            try:
                from transformers import Qwen2VLForConditionalGeneration
                model = Qwen2VLForConditionalGeneration.from_pretrained(
                    model_name,
                    torch_dtype="auto",
                    device_map="auto"
                )
                print(f"  [Vision] Loaded model with Qwen2VLForConditionalGeneration.", file=sys.stderr)
            except Exception as e:
                print(f"  Warning: Qwen2VLForConditionalGeneration failed ({e}). Falling back to AutoModelForCausalLM...", file=sys.stderr)
                
        # 4. Fallback to AutoModelForCausalLM
        if model is None:
            model = AutoModelForCausalLM.from_pretrained(
                model_name,
                torch_dtype="auto",
                device_map="auto"
            )
            print(f"  [Vision] Loaded model with AutoModelForCausalLM.", file=sys.stderr)
            
        try:
            processor = AutoProcessor.from_pretrained(model_name)
            print(f"  [Vision] Loaded AutoProcessor.", file=sys.stderr)
            return model, processor
        except Exception as e:
            print(f"  Warning: Could not load AutoProcessor ({e}). Falling back to AutoTokenizer.", file=sys.stderr)
    else:
        model = AutoModelForCausalLM.from_pretrained(
            model_name,
            torch_dtype="auto",
            device_map="auto"
        )

    tokenizer = AutoTokenizer.from_pretrained(model_name)
    return model, tokenizer

def run_local_inference(resume_text, model, tokenizer):
    messages = [
        {"role": "system", "content": get_system_prompt()},
        {"role": "user", "content": f"Below is the extracted text from the candidate's resume:\n\n{resume_text}"}
    ]
    
    text = tokenizer.apply_chat_template(
        messages,
        tokenize=False,
        add_generation_prompt=True,
        enable_thinking=False
    )
    
    model_inputs = tokenizer([text], return_tensors="pt").to(model.device)
    
    # Filter inputs to only keep keys accepted by model.forward or model.generate
    import inspect
    sig_forward = inspect.signature(model.forward).parameters
    sig_generate = inspect.signature(model.generate).parameters
    standard_generate_keys = {
        "max_length", "max_new_tokens", "min_length", "min_new_tokens", 
        "early_stopping", "max_time", "do_sample", "num_beams", "num_beam_groups", 
        "penalty_alpha", "use_cache", "temperature", "top_k", "top_p", "min_p", 
        "typical_p", "epsilon_cutoff", "eta_cutoff", "diversity_penalty", 
        "repetition_penalty", "encoder_repetition_penalty", "length_penalty", 
        "no_repeat_ngram_size", "bad_words_ids", "force_words_ids", 
        "renormalize_logits", "constraints", "forced_bos_token_id", 
        "forced_eos_token_id", "remove_invalid_values", "exponential_decay_length_penalty", 
        "suppress_tokens", "begin_suppress_tokens", "forced_decoder_ids", 
        "sequence_bias", "guidance_scale", "low_memory", "num_return_sequences", 
        "output_attentions", "output_hidden_states", "output_scores", 
        "return_dict_in_generate", "pad_token_id", "bos_token_id", "eos_token_id"
    }
    valid_keys = set(sig_forward.keys()) | set(sig_generate.keys()) | standard_generate_keys
    filtered_inputs = {k: v for k, v in model_inputs.items() if k in valid_keys}
    
    print("Generating structured output...", file=sys.stderr)
    generated_ids = model.generate(
        **filtered_inputs,
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

def run_local_inference_vision(pdf_path, model, processor):
    """Vision-only local inference: renders PDF pages as images and passes them to the model."""
    try:
        import fitz
    except ImportError:
        raise ImportError("PyMuPDF (fitz) is required for --image mode. Install with: pip install pymupdf")
    try:
        from PIL import Image
        import io
    except ImportError:
        raise ImportError("Pillow is required for --image mode. Install with: pip install Pillow")

    import base64
    # Render each PDF page to a PIL image
    doc = fitz.open(pdf_path)
    pil_images = []
    content = []
    content.append({"type": "text", "text": "Below are the original resume page images. Read directly from the images to extract information:"})
    for page_idx, page in enumerate(doc, start=1):
        pix = page.get_pixmap(dpi=150)
        img_bytes = pix.tobytes("png")
        img = Image.open(io.BytesIO(img_bytes)).convert("RGB")
        pil_images.append(img)
        
        base64_img = base64.b64encode(img_bytes).decode("utf-8")
        image_url = f"data:image/png;base64,{base64_img}"
        
        content.append({
            "type": "image_url",
            "image_url": {
                "url": image_url
            }
        })
        content.append({"type": "text", "text": f"[Page {page_idx}]"})
    print(f"  [Local Vision] Rendered {len(pil_images)} pages from {pdf_path}.", file=sys.stderr)

    messages = [
        {"role": "system", "content": get_system_prompt()},
        {"role": "user", "content": content}
    ]

    # Map standard messages to local format (replacing image_url with image format) for processor compatibility
    local_messages = []
    for msg in messages:
        new_msg = {"role": msg["role"]}
        if isinstance(msg["content"], list):
            new_content = []
            for item in msg["content"]:
                if item.get("type") == "image_url":
                    new_content.append({
                        "type": "image",
                        "image": item["image_url"]["url"]
                    })
                else:
                    new_content.append(item)
            new_msg["content"] = new_content
        else:
            new_msg["content"] = msg["content"]
        local_messages.append(new_msg)

    # Apply chat template
    try:
        text = processor.apply_chat_template(
            local_messages, tokenize=False, add_generation_prompt=True, enable_thinking=False
        )
    except TypeError:
        # Some processors don't support enable_thinking
        text = processor.apply_chat_template(
            local_messages, tokenize=False, add_generation_prompt=True
        )

    # Process inputs: try qwen_vl_utils first (Qwen VL family), fall back to direct PIL
    try:
        from qwen_vl_utils import process_vision_info
        image_inputs, video_inputs = process_vision_info(local_messages)
        inputs = processor(
            text=[text],
            images=image_inputs or None,
            videos=video_inputs or None,
            padding=True,
            return_tensors="pt"
        ).to(model.device)
        print("  [Local Vision] Using qwen_vl_utils for image processing.", file=sys.stderr)
    except ImportError:
        inputs = processor(
            text=[text],
            images=pil_images,
            padding=True,
            return_tensors="pt"
        ).to(model.device)
        print("  [Local Vision] Using direct PIL image processing.", file=sys.stderr)

    eos_id = (
        processor.tokenizer.eos_token_id
        if hasattr(processor, "tokenizer")
        else processor.eos_token_id
    )

    # Filter inputs to only keep keys accepted by model.forward or model.generate
    import inspect
    sig_forward = inspect.signature(model.forward).parameters
    sig_generate = inspect.signature(model.generate).parameters
    standard_generate_keys = {
        "max_length", "max_new_tokens", "min_length", "min_new_tokens", 
        "early_stopping", "max_time", "do_sample", "num_beams", "num_beam_groups", 
        "penalty_alpha", "use_cache", "temperature", "top_k", "top_p", "min_p", 
        "typical_p", "epsilon_cutoff", "eta_cutoff", "diversity_penalty", 
        "repetition_penalty", "encoder_repetition_penalty", "length_penalty", 
        "no_repeat_ngram_size", "bad_words_ids", "force_words_ids", 
        "renormalize_logits", "constraints", "forced_bos_token_id", 
        "forced_eos_token_id", "remove_invalid_values", "exponential_decay_length_penalty", 
        "suppress_tokens", "begin_suppress_tokens", "forced_decoder_ids", 
        "sequence_bias", "guidance_scale", "low_memory", "num_return_sequences", 
        "output_attentions", "output_hidden_states", "output_scores", 
        "return_dict_in_generate", "pad_token_id", "bos_token_id", "eos_token_id"
    }
    valid_keys = set(sig_forward.keys()) | set(sig_generate.keys()) | standard_generate_keys
    filtered_inputs = {k: v for k, v in inputs.items() if k in valid_keys}

    print("Generating structured output (vision mode)...", file=sys.stderr)
    generated_ids = model.generate(
        **filtered_inputs,
        max_new_tokens=100000,
        do_sample=True,
        temperature=0.7,
        top_p=0.8,
        top_k=20,
        min_p=0.0,
        repetition_penalty=1.0,
        pad_token_id=eos_id
    )

    # Trim the prompt tokens from the output
    input_len = inputs["input_ids"].shape[1]
    trimmed = generated_ids[:, input_len:]
    response = processor.batch_decode(trimmed, skip_special_tokens=True)[0]
    return response


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
        "projects":               '[]',
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
        
    # Initialize model once; reused across all files in --dir mode
    model = None
    tokenizer = None

    if not args.mock:
        model, tokenizer = load_local_model(args.model_name, image_mode=args.image)
            
    if args.pdf:
        # Processing a single PDF file
        if args.approved:
            pdf_basename = os.path.splitext(os.path.basename(args.pdf))[0]
            script_dir = os.path.dirname(os.path.abspath(__file__))
            approved_path = os.path.join(script_dir, "approved_jsons", pdf_basename + ".json")
            if not os.path.exists(approved_path):
                print(f"Skipping {args.pdf} because corresponding approved JSON {approved_path} does not exist.", file=sys.stderr)
                sys.exit(0)

        if args.arr:
            import re
            try:
                arr_indices = {int(x.strip()) for x in args.arr.split(",") if x.strip()}
            except ValueError:
                print("Error: --arr must be a comma-separated list of integers.", file=sys.stderr)
                sys.exit(1)
            pdf_basename = os.path.splitext(os.path.basename(args.pdf))[0]
            match = re.search(r'vietnamese_resume_(\d+)', pdf_basename, re.IGNORECASE)
            if not match or int(match.group(1)) not in arr_indices:
                print(f"Error: {args.pdf} does not match the filter in --arr ({args.arr}).", file=sys.stderr)
                sys.exit(1)
        start_time = time.time()
        if args.image and not args.mock:
            print(f"[--image] Vision-only mode: skipping text extraction for {args.pdf}.", file=sys.stderr)
            resume_text = ""
        else:
            try:
                print(f"Extracting text from {args.pdf}...", file=sys.stderr)
                resume_text = extract_text_from_pdf(args.pdf)
                print(f"Extracted {len(resume_text)} characters.", file=sys.stderr)
            except Exception as e:
                print(f"Error: {e}", file=sys.stderr)
                sys.exit(1)
        
        if args.mock:
            result = run_mock_extraction(resume_text)
        elif args.image:
            result = run_local_inference_vision(args.pdf, model, tokenizer)
        else:
            result = run_local_inference(resume_text, model, tokenizer)
            
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
            elapsed = time.time() - start_time
            print(f"Successfully saved JSON extraction to {args.output} (took {elapsed:.2f} seconds)", file=sys.stderr)
        else:
            print(formatted_json)
            elapsed = time.time() - start_time
            print(f"Processed in {elapsed:.2f} seconds", file=sys.stderr)
            
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
        
        if args.approved:
            script_dir = os.path.dirname(os.path.abspath(__file__))
            approved_dir = os.path.join(script_dir, "approved_jsons")
            pdf_files = [
                f for f in pdf_files
                if os.path.exists(os.path.join(approved_dir, os.path.splitext(f)[0] + ".json"))
            ]

        if args.arr:
            import re
            try:
                arr_indices = {int(x.strip()) for x in args.arr.split(",") if x.strip()}
            except ValueError:
                print("Error: --arr must be a comma-separated list of integers.", file=sys.stderr)
                sys.exit(1)
            
            def is_approved_resume(fn):
                m = re.search(r'vietnamese_resume_(\d+)', fn, re.IGNORECASE)
                return m and int(m.group(1)) in arr_indices
                
            pdf_files = [f for f in pdf_files if is_approved_resume(f)]

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
            start_time = time.time()
            try:
                if args.image and not args.mock:
                    print(f"  [--image] Vision-only mode: skipping text extraction.", file=sys.stderr)
                    resume_text = ""
                else:
                    resume_text = extract_text_from_pdf(pdf_path)
                    print(f"  Extracted {len(resume_text)} characters.", file=sys.stderr)

                if args.mock:
                    result = run_mock_extraction(resume_text)
                elif args.image:
                    result = run_local_inference_vision(pdf_path, model, tokenizer)
                else:
                    result = run_local_inference(resume_text, model, tokenizer)
                    
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
                elapsed = time.time() - start_time
                print(f"  Successfully saved JSON extraction to {output_path} (took {elapsed:.2f} seconds)", file=sys.stderr)
                
            except Exception as e:
                elapsed = time.time() - start_time
                print(f"  Error processing {filename} (failed after {elapsed:.2f} seconds): {e}", file=sys.stderr)
                
        print("\nBatch processing completed.", file=sys.stderr)

if __name__ == "__main__":
    main()
