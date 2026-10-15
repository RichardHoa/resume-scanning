"""
Evaluator Backend & Reporting Helper Functions
"""
import os
import sys
import json
import re
from typing import Dict, List, Any, NamedTuple, Optional

from src.core.config import (
    DIMENSION_WEIGHTS, FALLBACK_ERROR_SCORE, MATCH_THRESHOLDS, MAX_NEW_TOKENS,
    REQUIREMENTS_DECOMPOSITION_MAX_TOKENS, HR_CHECK_ITEMS_KEY,
    SCRUTINY_TEMPERATURE, SCRUTINY_MAX_QUESTIONS_PER_FIELD
)
from src.core.logger import log_broken_json
from src.core.json_utils import clean_and_parse_json
from src.core.importance import split_criterion_item
from src.providers import vllm_client
from src.prompts.evaluator_prompts import (
    get_requirements_decomposition_prompt,
    get_requirements_scrutiny_prompt
)
from src.pipelines.evaluator_mocks import (
    get_mock_decomposed_requirements,
    get_mock_scrutiny_response
)

class LLMReply(NamedTuple):
    text: str
    # Set only by the vLLM backend, which reports why generation stopped and how many tokens it produced
    finish_reason: Optional[str] = None
    completion_tokens: Optional[int] = None


CATEGORY_LABELS = {
    "seniority_title": "Position & Seniority Match",
    "technical_skills": "Technical Skills & Competencies",
    "work_experience": "Work Experience & Project Relevance",
    "education_certifications": "Education & Certifications",
    "hidden_culture": "HR Hidden Requirements & Culture Fit"
}


def call_transformers_backend(evaluator_inst: Any, prompt: str, messages: List[Dict[str, str]], temperature: float = 0.0, max_tokens: int = MAX_NEW_TOKENS) -> str:
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
            max_new_tokens=max_tokens,
            temperature=temperature,
            top_p=0.95,
            repetition_penalty=1.05,
            do_sample=temperature > 0.0
        )
    input_len = inputs["input_ids"].shape[1]
    generated_tokens = outputs[0][input_len:]
    return evaluator_inst.tokenizer.decode(generated_tokens, skip_special_tokens=True).strip()


def call_vllm_backend(
    evaluator_inst: Any,
    messages: List[Dict[str, str]],
    temperature: float = 0.0,
    json_schema: Optional[Dict[str, Any]] = None,
    max_tokens: int = MAX_NEW_TOKENS,
    step: str = "unlabeled"
) -> LLMReply:
    """Helper to call vLLM HTTP server backend."""
    result = vllm_client.chat(
        evaluator_inst.vllm_url, evaluator_inst.model_name, messages,
        temperature=temperature, top_p=0.95, json_schema=json_schema, max_tokens=max_tokens, step=step
    )
    text = result.content.strip()
    if result.reasoning.strip():
        text = f"<think>\n{result.reasoning.strip()}\n</think>\n{text}"
    return LLMReply(text, result.finish_reason, result.completion_tokens)


def decompose_requirements_with_llm(
    evaluator_inst: Any,
    standard_req: str,
    hidden_req: str,
    resume_name: str = "job_requirements",
    log_dir: Optional[str] = None
) -> Optional[Dict[str, List[Any]]]:
    """
    Helper to decompose HR standard & hidden requirements into 5 dimension categories, plus the HR Check Items.
    Each Criterion comes back as {"text", "importance"} (the decomposer's proposal, which HR reviews);
    HR Check Items stay plain strings.
    """
    categories = list(CATEGORY_LABELS.keys()) + [HR_CHECK_ITEMS_KEY]
    standard_req = (standard_req or "").strip()
    hidden_req = (hidden_req or "").strip()

    if not standard_req and not hidden_req:
        return {cat: [] for cat in categories}

    if evaluator_inst.mock:
        return get_mock_decomposed_requirements(standard_req, hidden_req)

    prompt = get_requirements_decomposition_prompt(standard_req, hidden_req, evaluator_inst.model_name)
    reply = evaluator_inst._call_llm(
        prompt, "requirements_decomposition", resume_name, log_dir=log_dir, max_tokens=REQUIREMENTS_DECOMPOSITION_MAX_TOKENS
    )
    raw_out = reply.text
    parsed = clean_and_parse_json(raw_out)

    if parsed and isinstance(parsed, dict):
        result: Dict[str, List[Any]] = {}
        for cat in categories:
            raw = parsed.get(cat)
            raw_items = raw if isinstance(raw, list) else [raw] if raw else []
            # Each item may be {"text", "importance"} or a plain string (read as Standard)
            items = [split_criterion_item(x) for x in raw_items]
            if cat == HR_CHECK_ITEMS_KEY:
                result[cat] = [text for text, _ in items if text]
            else:
                result[cat] = [{"text": text, "importance": importance} for text, importance in items if text]
        return result

    # Fallback text parsing for header-formatted responses
    if raw_out and any(cat in raw_out for cat in categories):
        print("[LocalRAG Warning] JSON parse failed, parsing text headers from LLM output...", file=sys.stderr)
        log_broken_json(prompt, raw_out, "requirements_decomposition", resume_name, attempt=1, error_reason="Decomposition JSON parse failed, header fallback used", finish_reason=reply.finish_reason, completion_tokens=reply.completion_tokens, log_dir=log_dir)
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

    log_broken_json(prompt, raw_out, "requirements_decomposition", resume_name, attempt=1, error_reason="Decomposition JSON parse failed completely", finish_reason=reply.finish_reason, completion_tokens=reply.completion_tokens, log_dir=log_dir)
    return None


def _validate_scrutiny_response(parsed: Any, max_questions: int) -> Optional[Dict[str, List[Dict[str, str]]]]:
    """Validates and truncates a parsed scrutiny response to the {standard_requirements, hidden_requirements} shape."""
    if not isinstance(parsed, dict):
        return None

    result: Dict[str, List[Dict[str, str]]] = {}
    for field in ("standard_requirements", "hidden_requirements"):
        if field not in parsed:
            # A missing key is a malformed response, not "no assumptions found" — treat it as a
            # parse failure so the caller retries instead of silently under-reporting to HR.
            return None
        items = parsed[field]
        if not isinstance(items, list):
            return None
        cleaned = []
        for item in items:
            if not isinstance(item, dict):
                continue
            assumption = str(item.get("assumption", "")).strip()
            question = str(item.get("question", "")).strip()
            if assumption and question:
                cleaned.append({"assumption": assumption, "question": question})
        result[field] = cleaned[:max_questions]
    return result


def scrutinize_requirements_with_llm(
    evaluator_inst: Any,
    standard_req: str,
    hidden_req: str,
    resume_name: str = "hr_requirements",
    language: Optional[str] = None,
    max_questions: int = SCRUTINY_MAX_QUESTIONS_PER_FIELD,
    max_retries: int = 5,
    log_dir: Optional[str] = None
) -> Dict[str, List[Dict[str, str]]]:
    """
    Scrutinizes HR standard & hidden requirements for Implicit Assumptions, returning up to
    `max_questions` Clarification Questions per field. Fails closed: raises RuntimeError if a
    valid response can't be parsed after `max_retries` attempts, rather than silently returning
    an empty (falsely reassuring) result.
    """
    standard_req = (standard_req or "").strip()
    hidden_req = (hidden_req or "").strip()
    eff_language = language or getattr(evaluator_inst, "language", "vietnamese")

    if not standard_req and not hidden_req:
        return {"standard_requirements": [], "hidden_requirements": []}

    if evaluator_inst.mock:
        return get_mock_scrutiny_response(standard_req, hidden_req, language=eff_language, max_questions=max_questions)

    prompt = get_requirements_scrutiny_prompt(standard_req, hidden_req, evaluator_inst.model_name, language=eff_language)

    reply = LLMReply("")
    for attempt in range(1, max_retries + 1):
        reply = evaluator_inst._call_llm(
            prompt, "requirements_scrutiny", resume_name,
            language=eff_language, temperature=SCRUTINY_TEMPERATURE, log_dir=log_dir
        )
        parsed = clean_and_parse_json(reply.text)
        validated = _validate_scrutiny_response(parsed, max_questions)
        if validated is not None:
            return validated

        print(f"[Scrutiny Retry] Attempt {attempt}/{max_retries} failed to parse. Retrying...", file=sys.stderr)
        log_broken_json(prompt, reply.text, "requirements_scrutiny", resume_name, attempt=attempt, error_reason="Scrutiny JSON parse failed", finish_reason=reply.finish_reason, completion_tokens=reply.completion_tokens, log_dir=log_dir)

    log_broken_json(prompt, reply.text, "requirements_scrutiny", resume_name, attempt=max_retries, error_reason=f"Max retries ({max_retries}) reached", finish_reason=reply.finish_reason, completion_tokens=reply.completion_tokens, log_dir=log_dir)
    raise RuntimeError(f"Requirement scrutiny failed to produce valid output after {max_retries} attempts.")


def aggregate_evaluation_results(
    cat_eval_outputs: Dict[str, Any],
    resume_name: str,
    num_evaluations: int
) -> tuple:
    """
    Helper to aggregate dimension scores and calculate final overall score & recommendation.
    Also returns the keys of the Categories that failed; any failure makes this a Failed Evaluation.
    """
    dimension_results = {}
    category_timings = {}
    weighted_total = 0.0
    any_evaluation_failed = False
    failed_category_names = []
    failed_category_keys = []

    # 1. Identify categories existing vs non-existing in RAG
    existing_cat_keys = []
    non_existing_cat_keys = []

    for cat_key in CATEGORY_LABELS.keys():
        if cat_key in cat_eval_outputs:
            _, cat_res, retrieved, _ = cat_eval_outputs[cat_key]
            if retrieved and len(retrieved) > 0:
                existing_cat_keys.append(cat_key)
            else:
                non_existing_cat_keys.append(cat_key)
        else:
            non_existing_cat_keys.append(cat_key)

    # 2. Calculate adjusted weights
    # Divide the percentage sum of non-existing categories equally among existing categories
    non_existing_weight_sum = sum(DIMENSION_WEIGHTS.get(ck, 0.20) for ck in non_existing_cat_keys)

    adjusted_weights = {}
    if non_existing_cat_keys and existing_cat_keys:
        addon = non_existing_weight_sum / len(existing_cat_keys)
        for ck in CATEGORY_LABELS.keys():
            if ck in existing_cat_keys:
                adjusted_weights[ck] = DIMENSION_WEIGHTS.get(ck, 0.20) + addon
            else:
                adjusted_weights[ck] = 0.0
    else:
        for ck in CATEGORY_LABELS.keys():
            adjusted_weights[ck] = DIMENSION_WEIGHTS.get(ck, 0.20)

    # 3. Process each category with adjusted weights
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
            failed_category_names.append(cat_name)
            failed_category_keys.append(cat_key)

        category_timings[cat_key] = round(elapsed_cat, 2)
        weight = round(adjusted_weights.get(cat_key, 0.20), 4)

        if cat_key in non_existing_cat_keys:
            score = 0
            weighted_score = 0.0
        else:
            score = cat_res.get("score", FALLBACK_ERROR_SCORE)
            weighted_score = round(score * weight, 2)
        
        dimension_results[cat_key] = {
            "category_name": cat_name,
            "weight": weight,
            "score": score,
            "weighted_score": weighted_score,
            "strengths": cat_res.get("strengths", []),
            "gaps": cat_res.get("gaps", []),
            "evidence_quotes": cat_res.get("evidence_quotes", []),
            "reasoning_summary": cat_res.get("reasoning_summary", ""),
            # Per-criterion verdicts with the resume quotes given for each, from the median run
            "criteria_evaluations": cat_res.get("criteria_evaluations", []),
            "retrieved_criteria": retrieved,
            "processing_time_seconds": round(elapsed_cat, 2),
            "evaluation_runs_count": num_evaluations,
            "all_run_scores": cat_res.get("all_scores", []),
            "median_score": cat_res.get("median_score", float(score))
        }
        # A Not Applicable Category: HR's requirements gave it no Criterion, so it is never shown to HR
        if cat_res.get("not_applicable"):
            dimension_results[cat_key]["not_applicable"] = True
        weighted_total += score * weight

    if any_evaluation_failed:
        failed_cats_str = ", ".join(failed_category_names)
        print(f"[FAILED EVALUATION] Evaluation failed in categories: [{failed_cats_str}] for resume '{resume_name}'. Failed categories zeroed; partial scores kept for debugging.", file=sys.stderr)
        for cat_key, cat_data in dimension_results.items():
            if cat_data.get("score") == FALLBACK_ERROR_SCORE and cat_key in [
                ck for ck, cn in CATEGORY_LABELS.items() if cn in failed_category_names
            ]:
                dimension_results[cat_key]["score"] = 0
                dimension_results[cat_key]["weighted_score"] = 0.0
                dimension_results[cat_key]["median_score"] = 0.0
                dimension_results[cat_key]["all_run_scores"] = []

    # Recompute weighted_total from final dimension scores (post-failure adjustment)
    weighted_total = sum(
        d["score"] * d["weight"] for d in dimension_results.values()
    )

    overall_score = round(weighted_total, 1)
    if overall_score >= MATCH_THRESHOLDS["STRONG"]:
        recommendation = "STRONG_MATCH"
    elif overall_score >= MATCH_THRESHOLDS["POTENTIAL"]:
        recommendation = "POTENTIAL_MATCH"
    elif overall_score >= MATCH_THRESHOLDS["LOW"]:
        recommendation = "LOW_MATCH"
    else:
        recommendation = "REJECT"

    return dimension_results, category_timings, overall_score, recommendation, failed_category_keys


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
