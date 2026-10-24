"""
Evaluator Backend & Reporting Helper Functions
"""
import os
import sys
import json
import re
from typing import Dict, List, Any, NamedTuple, Optional

from src.core.config import (
    CATEGORY_LABELS, MAX_NEW_TOKENS, REQUIREMENTS_DECOMPOSITION_MAX_TOKENS, HR_CHECK_ITEMS_KEY,
    SCRUTINY_TEMPERATURE, SCRUTINY_MAX_QUESTIONS_PER_FIELD
)
from src.core.logger import log_broken_json, HR_RAG_LOG_NAME
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


def call_vllm_backend(
    evaluator_inst: Any,
    messages: List[Dict[str, str]],
    temperature: float = 0.0,
    json_schema: Optional[Dict[str, Any]] = None,
    max_tokens: int = MAX_NEW_TOKENS,
    step: str = "unlabeled",
    resume_name: Optional[str] = None
) -> LLMReply:
    """Helper to call vLLM HTTP server backend."""
    result = vllm_client.chat(
        evaluator_inst.vllm_url, evaluator_inst.model_name, messages,
        temperature=temperature, top_p=0.95, json_schema=json_schema, max_tokens=max_tokens, step=step, resume_name=resume_name
    )
    text = result.content.strip()
    if result.reasoning.strip():
        text = f"<think>\n{result.reasoning.strip()}\n</think>\n{text}"
    return LLMReply(text, result.finish_reason, result.completion_tokens)


def decompose_requirements_with_llm(
    evaluator_inst: Any,
    standard_req: str,
    hidden_req: str,
    resume_name: str = HR_RAG_LOG_NAME,
    log_dir: Optional[str] = None
) -> Optional[Dict[str, List[str]]]:
    """
    Helper to decompose HR standard & hidden requirements into 5 dimension categories, plus the HR Check Items.
    Every item comes back as a plain string: the decomposer never proposes an Importance, so each Criterion reads as
    Standard until HR sets it (a Must-have rejects candidates, so only HR may choose one).
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
        result: Dict[str, List[str]] = {}
        for cat in categories:
            raw = parsed.get(cat)
            raw_items = raw if isinstance(raw, list) else [raw] if raw else []
            # An item the model still wrote as {"text", "importance"} keeps only its text
            result[cat] = [text for text, _ in (split_criterion_item(x) for x in raw_items) if text]
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
    resume_name: str = HR_RAG_LOG_NAME,
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


def evaluation_report_filename(resume_name: str) -> str:
    """File name of a resume's evaluation report in an output directory, as find_eval_file looks it up."""
    return f"{re.sub(r'[^a-zA-Z0-9_-]', '_', resume_name)}_evaluation.json"


def save_evaluation_report(
    evaluation_output: Dict[str, Any],
    resume_name: str,
    output_dir: Optional[str],
    output_path: Optional[str]
):
    """Helper to save evaluation report JSON to disk."""
    out_target = output_path
    if not out_target and output_dir:
        out_target = os.path.join(output_dir, evaluation_report_filename(resume_name))

    if out_target:
        try:
            os.makedirs(os.path.dirname(os.path.abspath(out_target)), exist_ok=True)
            with open(out_target, "w", encoding="utf-8") as f:
                json.dump(evaluation_output, f, ensure_ascii=False, indent=2)
            print(f"[Evaluation Complete] Report saved to {out_target}", file=sys.stderr)
        except Exception as e:
            print(f"[Save Error] Failed to write evaluation output to {out_target}: {e}", file=sys.stderr)
