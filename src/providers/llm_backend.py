"""
LLM Provider abstractions: Local Transformers, vLLM Server, and Mock Mode handlers.
"""
import os
import sys

# Ensure repository root is in sys.path for 'src' package imports
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import json
import urllib.request
import urllib.error
from typing import Any, Tuple, Optional
from src.core.config import MAX_NEW_TOKENS, DEFAULT_VLLM_URL
from src.core.json_utils import load_schema_from_file
from src.prompts.extractor_prompts import get_system_prompt, get_nuextract_schema_template


def load_local_model(model_name: str) -> Tuple[Any, Any]:
    """Loads a HuggingFace CausalLM / ImageTextToText model and tokenizer/processor."""
    print(f"Loading local model for: {model_name}...", file=sys.stderr)
    try:
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
    except ImportError:
        print("Error: PyTorch and Transformers libraries are required for local inference.", file=sys.stderr)
        print("Install them with: pip install torch transformers accelerate", file=sys.stderr)
        sys.exit(1)

    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"Using device: {device}", file=sys.stderr)

    if "nuextract" in model_name.lower():
        from transformers import AutoModelForImageTextToText, AutoProcessor
        print("  [NuExtract] Loading as AutoModelForImageTextToText with trust_remote_code=True...", file=sys.stderr)
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


def run_local_inference(resume_text: str, model: Any, tokenizer: Any) -> str:
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


def run_local_inference_nuextract(resume_text: str, model: Any, processor: Any) -> str:
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


def vllm_discover_model(vllm_url: str) -> str:
    """Query the vLLM server's `/v1/models` endpoint and return the first model ID."""
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


def vllm_chat_request(vllm_url: str, model_name: Optional[str], messages: list) -> str:
    """Send a chat completion request to a vLLM OpenAI-compatible server."""
    if not model_name:
        model_name = vllm_discover_model(vllm_url)

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


def run_vllm_inference(resume_text: str, model_name: Optional[str], vllm_url: str) -> str:
    """Run text-based extraction via a running vLLM server."""
    messages = [
        {"role": "system", "content": get_system_prompt()},
        {"role": "user", "content": f"Below is the extracted markdown text from the candidate's resume:\n\n{resume_text}"}
    ]

    print("Generating structured output (vLLM)...", file=sys.stderr)
    return vllm_chat_request(vllm_url, model_name, messages)


def vllm_nuextract_chat_request(vllm_url: str, model_name: Optional[str], messages: list, template_str: str) -> str:
    if not model_name:
        model_name = vllm_discover_model(vllm_url)

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


def run_vllm_inference_nuextract(resume_text: str, model_name: Optional[str], vllm_url: str) -> str:
    """Run text-based NuExtract extraction via a running vLLM server."""
    messages = [
        {"role": "user", "content": f"Below is the extracted markdown text from the candidate's resume:\n\n{resume_text}"}
    ]
    template_str = json.dumps(get_nuextract_schema_template(), indent=4)
    print("Generating structured output (vLLM NuExtract)...", file=sys.stderr)
    return vllm_nuextract_chat_request(vllm_url, model_name, messages, template_str)


def run_mock_extraction(resume_text: str) -> str:
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
            "title": "Nhân viên phát triển phần mềm",
            "level": "mid-level",
            "total_years_experience": "3.5 years",
            "seniority_summary": "3.5 years total experience: 2.5 years in Python Backend development, 1.0 year in System Administration"
        },
        "self_evaluation": "Lập trình viên nhiệt huyết với kinh nghiệm phát triển hệ thống web, mong muốn đóng góp cho các dự án lớn.",
        "skills_and_specialties": [
            "Python: 3.5 năm kinh nghiệm phát triển backend web service với FastAPI và Django",
            "SQL & PostgreSQL: 3 năm kinh nghiệm thiết kế cơ sở dữ liệu và tối ưu truy vấn",
            "Docker & Containerization: 2 năm kinh nghiệm đóng gói và triển khai ứng dụng",
            "Git & CI/CD: 3 năm kinh nghiệm quản lý phiên bản mã nguồn và quy trình tự động hóa"
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
