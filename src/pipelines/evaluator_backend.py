"""
Evaluator Backend & Reporting Helper Functions
"""
import os
import sys
import json
import re
from typing import Dict, List, Any, Optional

from src.core.config import (
    DIMENSION_WEIGHTS, VLLM_REQUEST_TIMEOUT, FALLBACK_ERROR_SCORE, MATCH_THRESHOLDS, MAX_NEW_TOKENS
)
from src.core.logger import log_broken_json
from src.core.json_utils import clean_and_parse_json
from src.prompts.evaluator_prompts import (
    get_requirements_decomposition_prompt
)
from src.pipelines.evaluator_mocks import (
    get_mock_category_response,
    get_mock_decomposed_requirements
)

CATEGORY_LABELS = {
    "seniority_title": "Position & Seniority Match",
    "technical_skills": "Technical Skills & Competencies",
    "work_experience": "Work Experience & Project Relevance",
    "education_certifications": "Education & Certifications",
    "hidden_culture": "HR Hidden Requirements & Culture Fit"
}


def call_transformers_backend(evaluator_inst: Any, prompt: str, messages: List[Dict[str, str]]) -> str:
    """Helper to call HuggingFace transformers model backend."""
    import torch
    if evaluator_inst.model is None or evaluator_inst.tokenizer is None:
        evaluator_inst.load_model()

    if hasattr(evaluator_inst.tokenizer, "apply_chat_template"):
        try:
            formatted_prompt = evaluator_inst.tokenizer.apply_chat_template(
                messages, tokenize=False, add_generation_prompt=True
            )
        except Exception:
            formatted_prompt = prompt
    else:
        formatted_prompt = prompt

    inputs = evaluator_inst.tokenizer(formatted_prompt, return_tensors="pt")
    target_device = evaluator_inst.model.device if hasattr(evaluator_inst.model, "device") else ("cuda" if torch.cuda.is_available() else "cpu")
    inputs = {k: v.to(target_device) for k, v in inputs.items()}
    
    with evaluator_inst._llm_lock, torch.no_grad():
        outputs = evaluator_inst.model.generate(
            **inputs,
            max_new_tokens=MAX_NEW_TOKENS,
            temperature=0.2,
            top_p=0.95,
            repetition_penalty=1.05,
            do_sample=True
        )
    input_len = inputs["input_ids"].shape[1]
    generated_tokens = outputs[0][input_len:]
    return evaluator_inst.tokenizer.decode(generated_tokens, skip_special_tokens=True).strip()


def call_vllm_backend(evaluator_inst: Any, category: str, messages: List[Dict[str, str]]) -> str:
    """Helper to call vLLM HTTP server backend."""
    import urllib.request
    import urllib.error
    url = f"{evaluator_inst.vllm_url.rstrip('/')}/chat/completions"
    payload = {
        "model": evaluator_inst.model_name,
        "messages": messages,
        "temperature": 0.2,
        "top_p": 0.95,
        "repetition_penalty": 1.05,
        "max_tokens": MAX_NEW_TOKENS,
        "response_format": {"type": "json_object"}
    }
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"}
    )
    try:
        try:
            resp_obj = urllib.request.urlopen(req, timeout=VLLM_REQUEST_TIMEOUT)
        except urllib.error.HTTPError as he:
            if he.code == 400:
                payload.pop("response_format", None)
                req_fallback = urllib.request.Request(
                    url,
                    data=json.dumps(payload).encode("utf-8"),
                    headers={"Content-Type": "application/json"}
                )
                resp_obj = urllib.request.urlopen(req_fallback, timeout=VLLM_REQUEST_TIMEOUT)
            else:
                raise he

        with resp_obj as resp:
            res_data = json.loads(resp.read().decode("utf-8"))
            choice_msg = res_data["choices"][0]["message"]
            content = choice_msg.get("content", "") or ""
            reasoning = choice_msg.get("reasoning_content", "") or ""
            
            if reasoning.strip():
                return f"<think>\n{reasoning.strip()}\n</think>\n{content.strip()}"
            return content.strip()
    except Exception as e:
        print(f"[vLLM Call Error] Failed to call vLLM server at {url}: {e}", file=sys.stderr)
        if evaluator_inst.mock:
            return get_mock_category_response(category)
        raise RuntimeError(f"[vLLM Call Fatal Error] Connection to vLLM server at {url} failed: {e}") from e


def decompose_requirements_with_llm(
    evaluator_inst: Any,
    standard_req: str,
    hidden_req: str,
    resume_name: str = "job_requirements"
) -> Optional[Dict[str, List[str]]]:
    """Helper to decompose HR standard & hidden requirements into 5 dimension categories."""
    categories = list(CATEGORY_LABELS.keys())
    standard_req = (standard_req or "").strip()
    hidden_req = (hidden_req or "").strip()

    if not standard_req and not hidden_req:
        return {cat: [] for cat in categories}

    if evaluator_inst.mock:
        return get_mock_decomposed_requirements(standard_req, hidden_req)

    prompt = get_requirements_decomposition_prompt(standard_req, hidden_req, evaluator_inst.model_name)
    raw_out = evaluator_inst._call_llm(prompt, "requirements_decomposition", resume_name)
    parsed = clean_and_parse_json(raw_out)

    if parsed and isinstance(parsed, dict):
        return {
            cat: [str(x).strip() for x in (parsed.get(cat, []) if isinstance(parsed.get(cat), list) else [parsed.get(cat)] if parsed.get(cat) else []) if str(x).strip()]
            for cat in categories
        }

    # Fallback text parsing for header-formatted responses
    if raw_out and any(cat in raw_out for cat in categories):
        print("[LocalRAG Warning] JSON parse failed, parsing text headers from LLM output...", file=sys.stderr)
        log_broken_json(prompt, raw_out, "requirements_decomposition", resume_name, attempt=1, error_reason="Decomposition JSON parse failed, header fallback used")
        fallback_dict = {cat: [] for cat in categories}
        current_cat = None
        for line in raw_out.split('\n'):
            line_str = line.strip()
            for cat in categories:
                if cat in line_str and (':' in line_str or '"' in line_str):
                    current_cat = cat
                    break
            if current_cat and line_str.startswith(('-', '*', '+', '•')):
                item_text = line_str.lstrip('-*+• ').strip(' ",')
                if item_text:
                    fallback_dict[current_cat].append(item_text)
        if any(fallback_dict.values()):
            return fallback_dict

    log_broken_json(prompt, raw_out, "requirements_decomposition", resume_name, attempt=1, error_reason="Decomposition JSON parse failed completely")
    return None


def aggregate_evaluation_results(
    cat_eval_outputs: Dict[str, Any],
    resume_name: str,
    num_evaluations: int
) -> tuple:
    """Helper to aggregate dimension scores and calculate final overall score & recommendation."""
    dimension_results = {}
    category_timings = {}
    weighted_total = 0.0
    any_evaluation_failed = False
    failed_categories = []

    for cat_key, cat_name in CATEGORY_LABELS.items():
        if cat_key in cat_eval_outputs:
            cat_name, cat_res, retrieved, elapsed_cat = cat_eval_outputs[cat_key]
        else:
            cat_res = {
                "score": FALLBACK_ERROR_SCORE,
                "strengths": [],
                "gaps": ["Lỗi xử lý mục đánh giá"],
                "evidence_quotes": [],
                "reasoning_summary": "Evaluation error.",
                "all_scores": [],
                "median_score": float(FALLBACK_ERROR_SCORE),
                "failed": True
            }
            retrieved = []
            elapsed_cat = 0.0

        if cat_res.get("failed", False):
            any_evaluation_failed = True
            failed_categories.append(cat_name)

        category_timings[cat_key] = round(elapsed_cat, 2)
        weight = DIMENSION_WEIGHTS.get(cat_key, 0.20)
        score = cat_res.get("score", FALLBACK_ERROR_SCORE)
        
        dimension_results[cat_key] = {
            "category_name": cat_name,
            "weight": weight,
            "score": score,
            "weighted_score": round(score * weight, 2),
            "strengths": cat_res.get("strengths", []),
            "gaps": cat_res.get("gaps", []),
            "evidence_quotes": cat_res.get("evidence_quotes", []),
            "reasoning_summary": cat_res.get("reasoning_summary", ""),
            "retrieved_criteria": retrieved,
            "processing_time_seconds": round(elapsed_cat, 2),
            "evaluation_runs_count": num_evaluations,
            "all_run_scores": cat_res.get("all_scores", []),
            "median_score": cat_res.get("median_score", score)
        }
        weighted_total += score * weight

    if any_evaluation_failed:
        failed_cats_str = ", ".join(failed_categories)
        print(f"[FATAL FAILURE] Evaluation failed for resume '{resume_name}' in categories: [{failed_cats_str}]. Resetting scores to 0.", file=sys.stderr)
        for cat_key in dimension_results:
            dimension_results[cat_key]["score"] = 0
            dimension_results[cat_key]["weighted_score"] = 0.0
            dimension_results[cat_key]["median_score"] = 0.0
            dimension_results[cat_key]["all_run_scores"] = [0] * num_evaluations
            dimension_results[cat_key]["reasoning_summary"] = f"EVALUATION FAILED: Category parse failed in '{failed_cats_str}'."
        overall_score = 0.0
        recommendation = "REJECT"
    else:
        overall_score = round(weighted_total, 1)
        if overall_score >= MATCH_THRESHOLDS["STRONG"]:
            recommendation = "STRONG_MATCH"
        elif overall_score >= MATCH_THRESHOLDS["POTENTIAL"]:
            recommendation = "POTENTIAL_MATCH"
        elif overall_score >= MATCH_THRESHOLDS["LOW"]:
            recommendation = "LOW_MATCH"
        else:
            recommendation = "REJECT"

    return dimension_results, category_timings, overall_score, recommendation


def save_evaluation_report(
    evaluation_output: Dict[str, Any],
    resume_name: str,
    output_dir: Optional[str],
    output_path: Optional[str]
):
    """Helper to save evaluation report JSON to disk."""
    out_target = output_path
    if not out_target and output_dir:
        out_filename = f"{re.sub(r'[^a-zA-Z0-9_-]', '_', resume_name)}_evaluation.json"
        out_target = os.path.join(output_dir, out_filename)

    if out_target:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(out_target)), exist_ok=True)
            with open(out_target, "w", encoding="utf-8") as f:
                json.dump(evaluation_output, f, ensure_ascii=False, indent=2)
            print(f"[Evaluation Complete] Report saved to {out_target}", file=sys.stderr)
        except Exception as e:
            print(f"[Save Error] Failed to write evaluation output to {out_target}: {e}", file=sys.stderr)
