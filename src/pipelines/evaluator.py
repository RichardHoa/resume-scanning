"""
Resume Evaluator Pipeline — RAG criteria retrieval & 5-dimension evaluation engine
"""
import os
import sys

# Ensure repository root is in sys.path for 'src' package imports
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import json
import time
import statistics
from datetime import datetime
from typing import Dict, List, Any, Optional

from src.core.config import (
    DEFAULT_LLM_MODEL, DEFAULT_VLLM_URL, FALLBACK_ERROR_SCORE, MAX_NEW_TOKENS,
    CATEGORY_EVAL_MAX_TOKENS, CATEGORY_EVAL_RETRY_TEMPERATURE, SCRUTINY_MAX_QUESTIONS_PER_FIELD, HR_CHECK_ITEMS_KEY
)
from src.core.logger import log_llm_call, log_broken_json
from src.core.json_utils import clean_and_parse_json
from src.providers.rag_engine import LocalCriteriaRAG
from src.prompts.evaluator_prompts import (
    get_evaluator_system_prompt,
    get_requirements_decomposition_system_prompt,
    get_requirements_scrutiny_system_prompt,
    get_category_evaluation_prompt,
    CATEGORY_EVALUATION_SCHEMA
)
from src.pipelines.evaluator_mocks import (
    get_mock_category_response
)
from src.pipelines.evaluator_utils import (
    clean_and_deduplicate_list,
    validate_category_evaluation,
    extract_relevant_resume_field,
    is_missing_position,
    collect_missing_must_haves
)
from src.pipelines.evaluator_backend import (
    CATEGORY_LABELS,
    LLMReply,
    call_vllm_backend,
    decompose_requirements_with_llm,
    scrutinize_requirements_with_llm,
    aggregate_evaluation_results,
    save_evaluation_report
)
from src.pipelines.review_panel import create_review_panel

# Backwards-compatibility aliases for module-level functions
_clean_and_deduplicate_list = clean_and_deduplicate_list
_validate_category_evaluation = validate_category_evaluation

class ResumeEvaluator:
    """
    Resume Evaluator Agent powered by local RAG criteria + LLM / vLLM.
    """
    def __init__(
        self,
        model_name: str = DEFAULT_LLM_MODEL,
        vllm_url: str = DEFAULT_VLLM_URL,
        mock: bool = False,
        language: str = "vietnamese"
    ):
        self.model_name = model_name or DEFAULT_LLM_MODEL
        self.vllm_url = vllm_url
        self.mock = mock
        self.language = language
        self.rag = LocalCriteriaRAG()
        self.review_panel = create_review_panel(mock, vllm_url, self.model_name)

    def load_model(self):
        """Reports the vLLM server in use (nothing is loaded locally)."""
        if self.mock:
            print("[ResumeEvaluator] Running in MOCK mode. Model will not be loaded.", file=sys.stderr)
            return
        print(f"[ResumeEvaluator] Using vLLM server backend at {self.vllm_url}", file=sys.stderr)

    def _call_llm(
        self,
        prompt: str,
        category: str,
        resume_name: str = "candidate",
        system_prompt: Optional[str] = None,
        run_index: Optional[int] = None,
        language: Optional[str] = None,
        temperature: float = 0.0,
        json_schema: Optional[Dict[str, Any]] = None,
        log_dir: Optional[str] = None,
        max_tokens: int = MAX_NEW_TOKENS
    ) -> LLMReply:
        eff_language = language or self.language
        if system_prompt is None:
            if category == "requirements_decomposition":
                system_prompt = get_requirements_decomposition_system_prompt()
            elif category == "requirements_scrutiny":
                system_prompt = get_requirements_scrutiny_system_prompt(max_questions=SCRUTINY_MAX_QUESTIONS_PER_FIELD)
            else:
                system_prompt = get_evaluator_system_prompt(language=eff_language)

        full_prompt = f"--- SYSTEM PROMPT ---\n{system_prompt}\n\n--- USER PROMPT ---\n{prompt}" if system_prompt else prompt

        if self.mock:
            response = get_mock_category_response(category, language=eff_language)
            log_llm_call(full_prompt, response, category, resume_name, run_index=run_index, log_dir=log_dir)
            return LLMReply(response)

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]

        reply = self._call_vllm_backend(messages, temperature=temperature, json_schema=json_schema, max_tokens=max_tokens, step=category)

        log_llm_call(full_prompt, reply.text, category, resume_name, run_index=run_index, log_dir=log_dir)
        return reply

    def _call_vllm_backend(
        self,
        messages: List[Dict[str, str]],
        temperature: float = 0.0,
        json_schema: Optional[Dict[str, Any]] = None,
        max_tokens: int = MAX_NEW_TOKENS,
        step: str = "unlabeled"
    ) -> LLMReply:
        return call_vllm_backend(self, messages, temperature=temperature, json_schema=json_schema, max_tokens=max_tokens, step=step)

    def _decompose_requirements_with_llm(
        self,
        standard_req: str,
        hidden_req: str,
        resume_name: str = "job_requirements",
        log_dir: Optional[str] = None
    ) -> Optional[Dict[str, List[Any]]]:
        return decompose_requirements_with_llm(self, standard_req, hidden_req, resume_name, log_dir=log_dir)

    def decompose_requirements(
        self,
        standard_req: str,
        hidden_req: str,
        resume_name: str = "hr_requirements",
        log_dir: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Decomposes HR requirements using LLM, stores in RAG, exports hr_rag.txt, and returns stored summary.
        """
        return self.rag.decompose_only(
            standard_req,
            hidden_req,
            llm_decomposer_func=lambda s, h: self._decompose_requirements_with_llm(s, h, resume_name, log_dir=log_dir)
        )

    def scrutinize_requirements(
        self,
        standard_req: str,
        hidden_req: str,
        resume_name: str = "hr_requirements",
        language: Optional[str] = None,
        log_dir: Optional[str] = None
    ) -> Dict[str, List[Dict[str, str]]]:
        """
        Scrutinizes HR standard & hidden requirements for Implicit Assumptions, returning
        {"standard_requirements": [...], "hidden_requirements": [...]} Clarification Questions.
        Ephemeral: does not touch the RAG store. Raises on failure (fails closed).
        """
        return scrutinize_requirements_with_llm(self, standard_req, hidden_req, resume_name, language=language, log_dir=log_dir)

    def _extract_relevant_resume_field(self, category: str, resume: Dict[str, Any]) -> Dict[str, Any]:
        """Wrapper for resume section extraction utility."""
        return extract_relevant_resume_field(category, resume)

    def evaluate_category(
        self,
        category: str,
        category_name: str,
        resume_data: Dict[str, Any],
        retrieved_criteria: List[str],
        resume_name: str,
        max_retries: int = 5,
        run_index: Optional[int] = None,
        language: Optional[str] = None,
        log_dir: Optional[str] = None,
        importance_map: Optional[Dict[str, str]] = None
    ) -> Dict[str, Any]:
        """
        One evaluation run of a Category. importance_map ({criterion_text: importance}) weights the Verdicts in the
        Category score; the LLM never sees it, so the prompt is the same whatever Importance HR set.
        """
        eff_language = language or self.language
        resume_snippet = self._extract_relevant_resume_field(category, resume_data)
        prompt = get_category_evaluation_prompt(category_name, self.model_name, retrieved_criteria, resume_snippet)

        reply = LLMReply("")
        for attempt in range(1, max_retries + 1):
            reply = self._call_llm(
                prompt, category, resume_name, run_index=run_index, language=eff_language,
                temperature=0.0 if attempt == 1 else CATEGORY_EVAL_RETRY_TEMPERATURE,
                json_schema=CATEGORY_EVALUATION_SCHEMA, log_dir=log_dir, max_tokens=CATEGORY_EVAL_MAX_TOKENS
            )
            parsed = clean_and_parse_json(reply.text)
            validated = validate_category_evaluation(parsed, importance_map=importance_map)

            if validated is not None:
                validated["failed"] = False
                return validated

            print(f"[Eval Retry] Attempt {attempt}/{max_retries} for category '{category}' failed. Retrying...", file=sys.stderr)
            log_broken_json(
                prompt, reply.text, category, resume_name, attempt=attempt, error_reason="Invalid numeric score or JSON",
                run_index=run_index, finish_reason=reply.finish_reason, completion_tokens=reply.completion_tokens, log_dir=log_dir
            )

        print(f"[FATAL] Category '{category_name}' failed after {max_retries} retries.", file=sys.stderr)
        log_broken_json(
            prompt, reply.text, category, resume_name, attempt=max_retries, error_reason=f"Max retries ({max_retries}) reached",
            run_index=run_index, finish_reason=reply.finish_reason, completion_tokens=reply.completion_tokens, log_dir=log_dir
        )
        is_en = eff_language.lower() in ("english", "en")
        gap_msg = f"Failed to parse evaluation data from model (Invalid JSON/Score after {max_retries} attempts)" if is_en else f"Không thể phân tích dữ liệu đánh giá từ mô hình (Format JSON/Score không hợp lệ sau {max_retries} lần thử)"
        reason_msg = f"DATA FAILURE: Unable to parse valid JSON after {max_retries} attempts." if is_en else f"THẤT BẠI DỮ LIỆU: Không thể phân tích JSON hợp lệ sau {max_retries} lần thử."
        return {
            "score": 0,
            "strengths": [],
            "gaps": [gap_msg],
            "evidence_quotes": [],
            "reasoning_summary": reason_msg,
            "failed": True
        }

    def _evaluate_single_category(
        self,
        cat_key: str,
        cat_name: str,
        resume_data: Dict[str, Any],
        resume_name: str,
        num_evaluations: int,
        language: Optional[str] = None,
        log_dir: Optional[str] = None
    ):
        eff_language = language or self.language
        is_en = eff_language.lower() in ("english", "en")
        t_cat_start = time.time()
        query_context = json.dumps(self._extract_relevant_resume_field(cat_key, resume_data), ensure_ascii=False)
        retrieved = self.rag.retrieve(cat_key, query_context, top_k=None)
        importance_map = self.rag.get_importance_map(cat_key)

        if not retrieved:
            print(f"[Evaluation] Category '{cat_name}' has no criteria in RAG. Setting 0% weight (not applicable).", file=sys.stderr)
            reasoning_msg = "No HR requirements specified for this dimension in RAG (Not applicable)." if is_en else "Không có tiêu chí từ HR trong RAG cho mục này (Không áp dụng)."
            cat_res = {
                "score": 0,
                "strengths": [],
                "gaps": [],
                "evidence_quotes": [],
                "reasoning_summary": reasoning_msg,
                "all_scores": [0] * num_evaluations,
                "median_score": 0.0,
                "not_applicable": True
            }
        else:
            if num_evaluations > 1:
                from concurrent.futures import ThreadPoolExecutor
                def _run_single_eval(run_i: int) -> Dict[str, Any]:
                    return self.evaluate_category(
                        cat_key, cat_name, resume_data, retrieved, resume_name, run_index=run_i, language=eff_language, log_dir=log_dir,
                        importance_map=importance_map
                    )
                max_workers = 40
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    eval_runs = list(executor.map(_run_single_eval, range(1, num_evaluations + 1)))
            else:
                eval_runs = [
                    self.evaluate_category(
                        cat_key, cat_name, resume_data, retrieved, resume_name, run_index=run_i, language=eff_language, log_dir=log_dir,
                        importance_map=importance_map
                    )
                    for run_i in range(1, num_evaluations + 1)
                ]

            has_category_failure = any(r.get("failed", False) for r in eval_runs)
            scores = [r.get("score", FALLBACK_ERROR_SCORE) for r in eval_runs]
            sorted_runs = sorted(eval_runs, key=lambda r: r.get("score", FALLBACK_ERROR_SCORE))
            med_score = int(round(float(statistics.median(scores))))
            median_idx = (len(sorted_runs) - 1) // 2
            
            cat_res = dict(sorted_runs[median_idx])
            cat_res["score"] = med_score
            cat_res["median_score"] = float(med_score)
            cat_res["all_scores"] = scores
            if has_category_failure:
                cat_res["failed"] = True

        elapsed_cat = time.time() - t_cat_start
        print(f"[Timing Log] [{resume_name}] Category '{cat_name}' ({cat_key}) evaluation took: {elapsed_cat:.2f}s (Median Score: {cat_res.get('score')})", file=sys.stderr)
        return cat_key, cat_name, cat_res, retrieved, elapsed_cat

    def _evaluate_all_categories(
        self,
        resume_data: Dict[str, Any],
        resume_name: str,
        num_evaluations: int,
        language: Optional[str] = None,
        log_dir: Optional[str] = None
    ) -> Dict[str, Any]:
        eff_language = language or self.language
        cat_eval_outputs = {}

        def _evaluate_dimension_task(item):
            cat_key, cat_name = item
            try:
                ck, cn, cat_res, retrieved, elapsed = self._evaluate_single_category(
                    cat_key, cat_name, resume_data, resume_name, num_evaluations, language=eff_language, log_dir=log_dir
                )
                return ck, (cn, cat_res, retrieved, elapsed)
            except Exception as e:
                import traceback
                print(f"[Category Eval Error] Exception during execution for '{cat_name}': {e}\n{traceback.format_exc()}", file=sys.stderr)
                is_en = eff_language.lower() in ("english", "en")
                err_gap = f"Evaluation dimension processing error: {e}" if is_en else f"Lỗi xử lý mục đánh giá: {e}"
                return cat_key, (
                    cat_name,
                    {
                        "score": FALLBACK_ERROR_SCORE,
                        "strengths": [],
                        "gaps": [err_gap],
                        "evidence_quotes": [],
                        "reasoning_summary": f"Evaluation execution error: {e}",
                        "error": str(e),
                        "all_scores": [],
                        "median_score": float(FALLBACK_ERROR_SCORE),
                        "failed": True
                    },
                    [],
                    0.0
                )

        from concurrent.futures import ThreadPoolExecutor
        categories_items = list(CATEGORY_LABELS.items())
        with ThreadPoolExecutor(max_workers=len(categories_items)) as executor:
            for ck, res_tuple in executor.map(_evaluate_dimension_task, categories_items):
                cat_eval_outputs[ck] = res_tuple

        return cat_eval_outputs

    def _aggregate_evaluation_results(
        self,
        cat_eval_outputs: Dict[str, Any],
        resume_name: str,
        num_evaluations: int
    ) -> tuple:
        return aggregate_evaluation_results(cat_eval_outputs, resume_name, num_evaluations)

    def _save_evaluation_report(
        self,
        evaluation_output: Dict[str, Any],
        resume_name: str,
        output_dir: Optional[str],
        output_path: Optional[str]
    ):
        return save_evaluation_report(evaluation_output, resume_name, output_dir, output_path)

    def evaluate_resume(
        self,
        resume_data: Dict[str, Any],
        standard_req: str,
        hidden_req: str,
        resume_name: str = "candidate",
        output_dir: Optional[str] = None,
        output_path: Optional[str] = None,
        num_evaluations: int = 1,
        language: Optional[str] = None,
        log_dir: Optional[str] = None,
        resume_path: Optional[str] = None,
        generate_feedback: bool = True
    ) -> Dict[str, Any]:
        eff_language = language or self.language
        start_resume_time = time.time()
        standard_req = standard_req or ""
        hidden_req = hidden_req or ""
        resume_data = resume_data if isinstance(resume_data, dict) else {}

        # 1. Judge against the HR RAG as HR set it; evaluation never builds or changes it
        self.rag.require_stored_rag()

        # 2. Evaluate each category
        cat_eval_outputs = self._evaluate_all_categories(resume_data, resume_name, num_evaluations, language=eff_language, log_dir=log_dir)

        # 3. Aggregate results
        dimension_results, category_timings, overall_score, recommendation, failed_categories = self._aggregate_evaluation_results(
            cat_eval_outputs, resume_name, num_evaluations
        )

        total_resume_time = time.time() - start_resume_time
        print(f"[Timing Log] [{resume_name}] Total Resume Evaluation Completed in: {total_resume_time:.2f}s", file=sys.stderr)

        # 4. Format output structure
        basic_info = resume_data.get("basic_information")
        basic_info = basic_info if isinstance(basic_info, dict) else {}
        candidate_name = basic_info.get("full_name") or basic_info.get("name") or basic_info.get("email") or resume_name

        # A Failed Evaluation keeps its partial scores for debugging, but is never ranked or shown as a result
        evaluation_output = {
            "status": "error" if failed_categories else "ok",
            "resume_name": resume_name,
            "candidate_identifier": candidate_name,
            # Copied from the extraction for display only; stripped from every LLM input
            "candidate_name": str(basic_info.get("full_name") or basic_info.get("name") or "").strip(),
            "overall_score": overall_score,
            "match_recommendation": recommendation,
            "evaluated_at": datetime.now().isoformat(),
            "execution_timings": {
                "total_resume_evaluation_seconds": round(total_resume_time, 2),
                "category_timings_seconds": category_timings
            },
            "dimension_scores": dimension_results,
            "hidden_requirements_assessment": dimension_results.get("hidden_culture", {}),
            # Not scored: HR checks these by hand. The Review Panel sees them only so it can leave them out
            HR_CHECK_ITEMS_KEY: self.rag.get_hr_check_items(),
            # Missing Must-Haves: informs HR (and the Review Panel) only; the candidate is still ranked
            "missing_must_haves": collect_missing_must_haves(dimension_results),
            "summary": {
                "total_strengths": sum([len(v["strengths"]) for v in dimension_results.values()]),
                "total_gaps": sum([len(v["gaps"]) for v in dimension_results.values()])
            },
            # Self-contained: everything needed to revisit this evaluation is in the report
            "standard_requirements": standard_req,
            "hidden_requirements": hidden_req,
            "resume_path": os.path.abspath(resume_path) if resume_path else None,
            "language": eff_language
        }
        if failed_categories:
            evaluation_output["failed_categories"] = failed_categories

        if resume_data.get("ocr_applied") or resume_data.get("intensive_hr_review_required"):
            evaluation_output["ocr_applied"] = True
            evaluation_output["intensive_hr_review_required"] = True
        if "warning" in resume_data:
            evaluation_output["warning"] = resume_data["warning"]

        # 5. Candidate Feedback, only for a fully scored evaluation. The panel returns a separate object and
        # never touches the scores; a panel failure is recorded in it and the evaluation is still saved
        if not failed_categories:
            if generate_feedback:
                evaluation_output["candidate_feedback"] = self.review_panel.review(
                    evaluation_output, resume_data, standard_req, hidden_req,
                    language=eff_language, resume_name=resume_name, log_dir=log_dir
                )
            else:
                evaluation_output["candidate_feedback"] = {"status": "skipped"}

        # A Missing Position is evaluated like any other resume, as if applying for this job; the flag is set after
        # the Review Panel so it only reaches HR on the website, never the panel
        if is_missing_position(resume_data):
            evaluation_output["missing_position"] = True

        # 6. Save report if requested
        self._save_evaluation_report(evaluation_output, resume_name, output_dir, output_path)

        return evaluation_output
