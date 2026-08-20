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
from src.prompts.extractor_prompts import get_system_prompt


def load_local_model(model_name: str) -> Tuple[Any, Any]:
    """Loads a HuggingFace CausalLM model and tokenizer."""
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

    model = AutoModelForCausalLM.from_pretrained(
        model_name,
        torch_dtype="auto",
        device_map="auto",
        trust_remote_code=True
    )
    tokenizer = AutoTokenizer.from_pretrained(model_name, trust_remote_code=True)
    return model, tokenizer


def run_local_inference(resume_text: str, model: Any, tokenizer: Any, language: str = "vietnamese") -> str:
    """Run text-based extraction using a locally-loaded HuggingFace model."""
    messages = [
        {"role": "system", "content": get_system_prompt(language)},
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
        do_sample=True,
        temperature=0.2,
        repetition_penalty=1.05,
        pad_token_id=tokenizer.eos_token_id
    )

    generated_ids = [
        output_ids[len(input_ids):] for input_ids, output_ids in zip(model_inputs.input_ids, generated_ids)
    ]

    response = tokenizer.batch_decode(generated_ids, skip_special_tokens=True)[0]
    return response



def vllm_discover_model(vllm_url: str) -> str:
    """Query the vLLM server's `/v1/models` endpoint and return the first model ID."""
    url = vllm_url.rstrip("/") + "/models"
    req = urllib.request.Request(url, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            body = json.loads(resp.read().decode("utf-8"))
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"Cannot connect to vLLM server at {vllm_url} ({e.reason or e}). "
            f"Please verify the vLLM server is running (e.g. './scripts/server.sh --start-vllm') "
            f"or switch to '--backend transformers' or '--mock'."
        ) from e
    except Exception as e:
        raise RuntimeError(f"Failed to query vLLM server models at {url}: {e}") from e

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
        "temperature": 0.2,
        "repetition_penalty": 1.05,
        "max_tokens": MAX_NEW_TOKENS,
        "guided_json": schema,
        "chat_template_kwargs": {
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
    except urllib.error.URLError as e:
        raise RuntimeError(
            f"Cannot connect to vLLM server at {vllm_url} ({e.reason or e}). "
            f"Please verify the vLLM server is running (e.g. './scripts/server.sh --start-vllm') "
            f"or switch to '--backend transformers' or '--mock'."
        ) from e


def run_vllm_inference(resume_text: str, model_name: Optional[str], vllm_url: str, language: str = "vietnamese") -> str:
    """Run text-based extraction via a running vLLM server."""
    messages = [
        {"role": "system", "content": get_system_prompt(language)},
        {"role": "user", "content": f"Below is the extracted markdown text from the candidate's resume:\n\n{resume_text}"}
    ]

    print("Generating structured output (vLLM)...", file=sys.stderr)
    return vllm_chat_request(vllm_url, model_name, messages)


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
        "skills_and_specialties": [
            "- Python: Quản lý và phát triển hệ thống backend web service với FastAPI và Django trong 3.5 năm. Thiết kế kiến trúc RESTful API hiệu năng cao xử lý hàng ngàn lượt truy cập song song. Tối ưu hóa mã nguồn Python bằng async I/O và cấu trúc dữ liệu hiệu quả.",
            "- SQL & PostgreSQL: Thiết kế và quản lý hệ thống cơ sở dữ liệu PostgreSQL quy mô lớn trong 3 năm. Thực hiện tối ưu hóa truy vấn phức tạp, lập chỉ mục phù hợp và điều chỉnh hiệu năng database. Đảm bảo tính toàn vẹn dữ liệu và xây dựng quy trình sao lưu tự động.",
            "- Docker & Containerization: Đóng gói và triển khai ứng dụng bằng Docker và Docker Compose trong 2 năm. Xây dựng môi trường phát triển và sản xuất đồng nhất giúp giảm thiểu lỗi phát sinh. Tối ưu hóa dung lượng image và thiết lập mạng container an toàn.",
            "- Git & CI/CD: Quản lý phiên bản mã nguồn bằng Git và xây dựng quy trình tự động hóa CI/CD trong 3 năm. Tự động hóa kiểm thử mã nguồn, đóng gói và triển khai phần mềm lên máy chủ. Xây dựng quy trình làm việc GitFlow hiệu quả cho đội ngũ phát triển."
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
