#!/usr/bin/env python3
"""
Vietnamese Resume Extractor — Step 1: Structured Information Extraction

Extracts structured JSON from Vietnamese PDF resumes.
1. Converts PDF to Markdown layout-aware representation using MinerU (magic-pdf).
2. Uses a text-only LLM (default: Qwen/Qwen3.5-9B) to parse the markdown into structured JSON.

Supports two inference backends:
  1. HuggingFace Transformers (default, --backend transformers)
  2. vLLM Server (--backend vllm)
"""
import os
import sys
import json
import argparse
import time
import tempfile
import shutil
import subprocess
import glob

# Maximum number of NEW tokens the model may generate.
MAX_NEW_TOKENS = 20000


def extract_text_from_pdf(pdf_path):
    """
    Converts a PDF file to Markdown layout-aware representation using Docling.
    Returns the markdown text.
    """
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"File not found: {pdf_path}")

    from docling.document_converter import DocumentConverter

    print(f"Parsing PDF with Docling: {pdf_path}", file=sys.stderr)
    converter = DocumentConverter()
    result = converter.convert(pdf_path)
    markdown_content = result.document.export_to_markdown()

    # Save markdown output to the root directory for inspection
    try:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        root_dir = os.path.dirname(script_dir)
        pdf_basename = os.path.splitext(os.path.basename(pdf_path))[0]
        md_output_path = os.path.join(root_dir, f"{pdf_basename}.md")
        
        print(f"Saving markdown preview to: {md_output_path}", file=sys.stderr)
        with open(md_output_path, "w", encoding="utf-8") as f:
            f.write(markdown_content)
    except Exception as e:
        print(f"Warning: Could not save markdown to root: {e}", file=sys.stderr)

    return markdown_content


def parse_args():
    parser = argparse.ArgumentParser(description="Vietnamese Resume Extractor (Local Inference)")
    parser.add_argument("--pdf", type=str, help="Path to a single PDF resume file")
    parser.add_argument("--dir", type=str, help="Path to a directory containing PDF resumes to scan")
    parser.add_argument("--model-name", type=str, default="Qwen/Qwen3.5-9B",
                        help="Model repository name or local path")
    parser.add_argument("--mock", action="store_true",
                        help="Mock run: performs text extraction and returns mock JSON output without loading the model")
    parser.add_argument("--output", type=str, help="Path to save the JSON output file (or output directory if --dir is used)")
    parser.add_argument("--arr", type=str,
                        help="Comma-separated list of resume numbers to process (e.g., --arr=6,7,8,10)")
    parser.add_argument("--approved", action="store_true",
                        help="Only process PDFs that have a corresponding ground truth JSON in approved_jsons")
    parser.add_argument("--backend", type=str, default="transformers", choices=["transformers", "vllm"],
                        help="Inference backend: 'transformers' (load model locally) or 'vllm' (call a running vLLM server)")
    parser.add_argument("--vllm-url", type=str, default="http://localhost:8100/v1",
                        help="Base URL of the vLLM OpenAI-compatible server (only used with --backend vllm)")
    return parser.parse_args()


def load_schema_from_file(model_name: str) -> dict:
    """Loads the appropriate schema dictionary from the schemas/ directory based on active model name."""
    script_dir = os.path.dirname(os.path.abspath(__file__))
    workspace_dir = os.path.dirname(script_dir)
    
    if not model_name:
        model_name = ""
        
    model_name_lower = model_name.lower()
    
    if "nuextract" in model_name_lower:
        schema_file = "nuextract_schema.json"
    else:
        schema_file = "qwen_schema.json"
        
    schema_path = os.path.join(workspace_dir, "schemas", schema_file)
    try:
        with open(schema_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Warning: Failed to load schema from {schema_path} ({e}). Falling back to empty object.", file=sys.stderr)
        return {}


def get_nuextract_schema_template():
    """Returns the JSON schema template specifically formatted with NuExtract3 data types."""
    return load_schema_from_file("nuextract")


def get_system_prompt():
    qwen_schema = load_schema_from_file("qwen")
    schema_str = json.dumps(qwen_schema, ensure_ascii=False, indent=2)
    return f"""You are an AI resume extraction specialist. Your only job is to extract structured information from a resume and return it as valid JSON matching the schema below.

REASONING & FORMATTING RULES:
1. THINKING PROCESS — You may reason step-by-step inside `<think>...</think>` tags, but the final output outside of the thinking block must be strictly valid JSON matching the schema below.
2. NO MARKDOWN BLOCK — Do not wrap the final JSON in markdown code fences (e.g. do not use ```json ... ```). Output raw JSON only.

EXTRACTION RULES:
1. EXHAUSTIVE EXTRACTION — Record ALL details. Do not summarize, skip, omit, or truncate any information (especially responsibilities, achievements, projects, skills, education details, and dates). Extract every single item completely and verbatim from the CV.
2. EXTRACT ONLY — Never modify, rephrase, translate, or infer beyond what is explicitly written. Copy text character-for-character as it appears on the resume. Only use inference when the resume genuinely omits a required field (e.g. position title not stated).
3. EMPTY VALUES — If a field is not present in the resume, represent it as an empty string "" or an empty array [] as defined in the schema. Never omit keys from the JSON object. Do not invent placeholder values like "N/A" or "Not specified".
4. LANGUAGE SELECTION — If the resume contains two languages (e.g. Vietnamese + English), first determine the dominant language: if the resume is primarily Vietnamese, favor Vietnamese text throughout; if primarily English, favor English text. Apply this consistently to all fields.

JSON SCHEMA:
{schema_str}
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


def load_local_model(model_name):
    print(f"Loading local model for: {model_name}...", file=sys.stderr)
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

    if "nuextract" in model_name.lower():
        from transformers import AutoModelForImageTextToText, AutoProcessor
        print(f"  [NuExtract] Loading as AutoModelForImageTextToText with trust_remote_code=True...", file=sys.stderr)
        model = AutoModelForImageTextToText.from_pretrained(
            model_name,
            torch_dtype="auto",
            device_map="auto",
            trust_remote_code=True
        )
        processor = AutoProcessor.from_pretrained(model_name, trust_remote_code=True)
        return model, processor

    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        torch_dtype="auto",
        device_map="auto",
        trust_remote_code=True
    )
    tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
    return model, tokenizer


def run_local_inference(resume_text, model, tokenizer):
    """Run text-based extraction using a locally-loaded HuggingFace model."""
    messages = [
        {"role": "system", "content": get_system_prompt()},
        {"role": "user", "content": f"Below is the extracted markdown text from the candidate's resume:\n\n{resume_text}"}
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
        max_new_tokens=MAX_NEW_TOKENS,
        do_sample=False,
        repetition_penalty=1.0,
        pad_token_id=tokenizer.eos_token_id
    )
    
    generated_ids = [
        output_ids[len(input_ids):] for input_ids, output_ids in zip(model_inputs.input_ids, generated_ids)
    ]
    
    response = tokenizer.batch_decode(generated_ids, skip_special_tokens=True)[0]
    return response


def run_local_inference_nuextract(resume_text, model, processor):
    """Run text-based extraction using a locally-loaded NuExtract model."""
    import torch
    messages = [
        {"role": "user", "content": f"Below is the extracted markdown text from the candidate's resume:\n\n{resume_text}"}
    ]
    template_str = json.dumps(get_nuextract_schema_template(), indent=4)
    
    inputs = processor.apply_chat_template(
        messages,
        template=template_str,
        enable_thinking=False,
        add_generation_prompt=True,
        tokenize=True,
        return_dict=True,
        return_tensors="pt"
    ).to(model.device)
    
    print("Generating structured output (NuExtract)...", file=sys.stderr)
    with torch.no_grad():
        generated_ids = model.generate(
            **inputs,
            max_new_tokens=MAX_NEW_TOKENS,
            do_sample=False
        )
        
    input_len = inputs["input_ids"].shape[1]
    trimmed_ids = generated_ids[:, input_len:]
    response = processor.batch_decode(
        trimmed_ids,
        skip_special_tokens=True,
        clean_up_tokenization_spaces=False
    )[0].strip()
    
    return response


def _vllm_discover_model(vllm_url):
    """Query the vLLM server's ``/v1/models`` endpoint and return the first model ID."""
    import urllib.request

    url = vllm_url.rstrip("/") + "/models"
    req = urllib.request.Request(url, method="GET")
    with urllib.request.urlopen(req, timeout=30) as resp:
        body = json.loads(resp.read().decode("utf-8"))
    models = body.get("data", [])
    if not models:
        raise RuntimeError(f"No models found on vLLM server at {vllm_url}")
    model_id = models[0]["id"]
    print(f"  [vLLM] Auto-discovered model: {model_id}", file=sys.stderr)
    return model_id


def _vllm_chat_request(vllm_url, model_name, messages):
    """Send a chat completion request to a vLLM OpenAI-compatible server."""
    import urllib.request
    import urllib.error

    if not model_name:
        model_name = _vllm_discover_model(vllm_url)

    # Load schema to force guided decoding in vLLM
    schema = load_schema_from_file(model_name)

    url = vllm_url.rstrip("/") + "/chat/completions"
    payload = json.dumps({
        "model": model_name,
        "messages": messages,
        "temperature": 0.0,
        "max_tokens": MAX_NEW_TOKENS,
        "guided_json": schema
    }).encode("utf-8")

    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        return body["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        error_body = ""
        try:
            error_body = e.read().decode("utf-8")
        except Exception:
            pass
        raise RuntimeError(
            f"vLLM request failed (HTTP {e.code}): {error_body}"
        ) from e


def run_vllm_inference(resume_text, model_name, vllm_url):
    """Run text-based extraction via a running vLLM server."""
    messages = [
        {"role": "system", "content": get_system_prompt()},
        {"role": "user", "content": f"Below is the extracted markdown text from the candidate's resume:\n\n{resume_text}"}
    ]

    print("Generating structured output (vLLM)...", file=sys.stderr)
    return _vllm_chat_request(vllm_url, model_name, messages)


def _vllm_nuextract_chat_request(vllm_url, model_name, messages, template_str):
    import urllib.request
    import urllib.error

    if not model_name:
        model_name = _vllm_discover_model(vllm_url)

    url = vllm_url.rstrip("/") + "/chat/completions"
    payload = json.dumps({
        "model": model_name,
        "messages": messages,
        "temperature": 0.0,
        "max_tokens": MAX_NEW_TOKENS,
        "chat_template_kwargs": {
            "template": template_str,
            "enable_thinking": False
        }
    }).encode("utf-8")

    req = urllib.request.Request(
        url, data=payload,
        headers={"Content-Type": "application/json"},
        method="POST"
    )

    try:
        with urllib.request.urlopen(req, timeout=600) as resp:
            body = json.loads(resp.read().decode("utf-8"))
        return body["choices"][0]["message"]["content"]
    except urllib.error.HTTPError as e:
        error_body = ""
        try:
            error_body = e.read().decode("utf-8")
        except Exception:
            pass
        raise RuntimeError(
            f"vLLM request failed (HTTP {e.code}): {error_body}"
        ) from e


def run_vllm_inference_nuextract(resume_text, model_name, vllm_url):
    """Run text-based NuExtract extraction via a running vLLM server."""
    messages = [
        {"role": "user", "content": f"Below is the extracted markdown text from the candidate's resume:\n\n{resume_text}"}
    ]
    template_str = json.dumps(get_nuextract_schema_template(), indent=4)
    print("Generating structured output (vLLM NuExtract)...", file=sys.stderr)
    return _vllm_nuextract_chat_request(vllm_url, model_name, messages, template_str)


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
    """
    if not text or not text.strip():
        return text

    in_string = False
    escape_next = False
    stack = []
    ctx_stack = []
    last_safe_end = 0

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
                in_string = False
                ctx = ctx_stack[-1] if ctx_stack else None
                if ctx and ctx[0] == 'o':
                    if ctx[1] == 'expect_value':
                        last_safe_end = i + 1
                        ctx_stack[-1] = ('o', 'after_value')
                    elif ctx[1] == 'expect_key':
                        ctx_stack[-1] = ('o', 'expect_colon')
                elif ctx and ctx[0] == 'a':
                    last_safe_end = i + 1
            else:
                in_string = True
                ctx = ctx_stack[-1] if ctx_stack else None
                if ctx and ctx[0] == 'o' and ctx[1] == 'after_value':
                    ctx_stack[-1] = ('o', 'expect_key')
            i += 1
            continue

        if in_string:
            i += 1
            continue

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

        i += 1

    safe_text = text[:last_safe_end]

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

    closing = ''.join('}' if s == 'o' else ']' for s in reversed(stack2))
    repaired = safe_text.rstrip().rstrip(',') + closing

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
        return repaired


class ResumeExtractor:
    """Unified interface for resume extraction across both inference backends.

    Wraps the HuggingFace Transformers and vLLM inference paths behind a
    single ``extract(pdf_path)`` method.
    """

    def __init__(self, model_name: str, mock: bool = False,
                 backend: str = "transformers", vllm_url: str = "http://localhost:8100/v1"):
        self.model_name = model_name
        self.mock = mock
        self.backend = backend
        self.vllm_url = vllm_url
        self.model = None
        self.tokenizer_or_processor = None

    def load_model(self):
        if not self.mock and self.backend == "transformers":
            self.model, self.tokenizer_or_processor = load_local_model(self.model_name)
        elif self.backend == "vllm" and not self.model_name:
            self.model_name = _vllm_discover_model(self.vllm_url)

    def extract(self, pdf_path: str) -> str:
        if self.mock:
            resume_text = "Mock resume content converted from PDF."
        else:
            resume_text = extract_text_from_pdf(pdf_path)

        is_nuextract = self.model_name and "nuextract" in self.model_name.lower()
        if self.mock:
            result = run_mock_extraction(resume_text)
        elif self.backend == "vllm":
            if is_nuextract:
                result = run_vllm_inference_nuextract(resume_text, self.model_name, self.vllm_url)
            else:
                result = run_vllm_inference(resume_text, self.model_name, self.vllm_url)
        else:
            if is_nuextract:
                result = run_local_inference_nuextract(resume_text, self.model, self.tokenizer_or_processor)
            else:
                result = run_local_inference(resume_text, self.model, self.tokenizer_or_processor)

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
                print("  Auto-repair failed. Returning raw substring.", file=sys.stderr)
                formatted_json = clean_result

        return formatted_json


def main():
    args = parse_args()
    
    if not args.pdf and not args.dir:
        print("Error: You must specify either --pdf or --dir.", file=sys.stderr)
        sys.exit(1)
    if args.pdf and args.dir:
        print("Error: You cannot specify both --pdf and --dir. Please choose one.", file=sys.stderr)
        sys.exit(1)
        
    extractor = ResumeExtractor(
        model_name=args.model_name, mock=args.mock,
        backend=args.backend, vllm_url=args.vllm_url
    )
    if not args.mock and args.backend == "transformers":
        extractor.load_model()
            
    if args.pdf:
        if args.approved:
            pdf_basename = os.path.splitext(os.path.basename(args.pdf))[0]
            script_dir = os.path.dirname(os.path.abspath(__file__))
            approved_path = os.path.abspath(os.path.join(script_dir, "..", "approved_jsons", pdf_basename + ".json"))
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
        try:
            formatted_json = extractor.extract(args.pdf)
        except Exception as e:
            print(f"Error during extraction: {e}", file=sys.stderr)
            sys.exit(1)
            
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
            approved_dir = os.path.abspath(os.path.join(script_dir, "..", "approved_jsons"))
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
                formatted_json = extractor.extract(pdf_path)
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
