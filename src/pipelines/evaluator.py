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
import threading
from datetime import datetime
from typing import Dict, List, Any, Optional

from src.core.config import (
    DEFAULT_LLM_MODEL, DEFAULT_VLLM_URL, FALLBACK_ERROR_SCORE
)
from src.core.logger import log_llm_call, log_broken_json
from src.core.json_utils import clean_and_parse_json
from src.providers.rag_engine import LocalCriteriaRAG
from src.prompts.evaluator_prompts import (
    get_evaluator_system_prompt,
    get_requirements_decomposition_system_prompt,
    get_category_evaluation_prompt
)
from src.pipelines.evaluator_mocks import (
    get_mock_category_response
)
from src.pipelines.evaluator_utils import (
    clean_and_deduplicate_list,
    validate_category_evaluation,
    extract_relevant_resume_field
)
from src.pipelines.evaluator_backend import (
    CATEGORY_LABELS,
    call_transformers_backend,
    call_vllm_backend,
    decompose_requirements_with_llm,
    aggregate_evaluation_results,
    save_evaluation_report
)

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
        backend: str = "transformers",
        vllm_url: str = DEFAULT_VLLM_URL,
        mock: bool = False
    ):
        self.model_name = model_name or DEFAULT_LLM_MODEL
        self.backend = backend
        self.vllm_url = vllm_url
        self.mock = mock
        self.rag = LocalCriteriaRAG()

        self.tokenizer = None
        self.model = None
        self._llm_lock = threading.Lock()

    def load_model(self):
        """Loads HuggingFace model or checks vLLM connection."""
        if self.mock:
            print("[ResumeEvaluator] Running in MOCK mode. Model will not be loaded.", file=sys.stderr)
            return

        if self.backend == "transformers":
            import torch
            from transformers import AutoTokenizer, AutoModelForCausalLM

            print(f"[ResumeEvaluator] Loading HuggingFace model: {self.model_name}...", file=sys.stderr)
            self.tokenizer = AutoTokenizer.from_pretrained(self.model_name, trust_remote_code=True)
            self.model = AutoModelForCausalLM.from_pretrained(
                self.model_name,
                torch_dtype=torch.bfloat16 if torch.cuda.is_available() else torch.float32,
                device_map="auto" if torch.cuda.is_available() else None,
                trust_remote_code=True
            )
            print("[ResumeEvaluator] Model loaded successfully!", file=sys.stderr)
        elif self.backend == "vllm":
            print(f"[ResumeEvaluator] Using vLLM server backend at {self.vllm_url}", file=sys.stderr)

    def _call_llm(
        self, 
        prompt: str, 
        category: str, 
        resume_name: str = "candidate", 
        system_prompt: Optional[str] = None, 
        run_index: Optional[int] = None
    ) -> str:
        if self.mock:
            response = get_mock_category_response(category)
            log_llm_call(prompt, response, category, resume_name, run_index=run_index)
            return response

        if system_prompt is None:
            if category == "requirements_decomposition":
                system_prompt = get_requirements_decomposition_system_prompt()
            else:
                system_prompt = get_evaluator_system_prompt()

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": prompt}
        ]

        if self.backend == "transformers":
            response_text = self._call_transformers_backend(prompt, messages)
        elif self.backend == "vllm":
            response_text = self._call_vllm_backend(category, messages)
        else:
            response_text = ""

        log_llm_call(prompt, response_text, category, resume_name, run_index=run_index)
        return response_text

    def _call_transformers_backend(self, prompt: str, messages: List[Dict[str, str]]) -> str:
        return call_transformers_backend(self, prompt, messages)

    def _call_vllm_backend(self, category: str, messages: List[Dict[str, str]]) -> str:
        return call_vllm_backend(self, category, messages)

    def _decompose_requirements_with_llm(
        self,
        standard_req: str,
        hidden_req: str,
        resume_name: str = "job_requirements"
    ) -> Optional[Dict[str, List[str]]]:
        return decompose_requirements_with_llm(self, standard_req, hidden_req, resume_name)

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
        max_retries: int = 30,
        run_index: Optional[int] = None
    ) -> Dict[str, Any]:
        resume_snippet = self._extract_relevant_resume_field(category, resume_data)
        prompt = get_category_evaluation_prompt(category_name, self.model_name, retrieved_criteria, resume_snippet)

        for attempt in range(1, max_retries + 1):
            raw_out = self._call_llm(prompt, category, resume_name, run_index=run_index)
            parsed = clean_and_parse_json(raw_out)
            validated = validate_category_evaluation(parsed)

            if validated is not None:
                validated["failed"] = False
                return validated

            print(f"[Eval Retry] Attempt {attempt}/{max_retries} for category '{category}' failed. Retrying...", file=sys.stderr)
            log_broken_json(prompt, raw_out, category, resume_name, attempt=attempt, error_reason="Invalid numeric score or JSON", run_index=run_index)

        print(f"[FATAL] Category '{category_name}' failed after {max_retries} retries.", file=sys.stderr)
        log_broken_json(prompt, raw_out, category, resume_name, attempt=max_retries, error_reason=f"Max retries ({max_retries}) reached", run_index=run_index)
        return {
            "score": 0,
            "strengths": [],
            "gaps": [f"Không thể phân tích dữ liệu đánh giá từ mô hình (Format JSON/Score không hợp lệ sau {max_retries} lần thử)"],
            "evidence_quotes": [],
            "reasoning_summary": f"THẤT BẠI DỮ LIỆU: Không thể phân tích JSON hợp lệ sau {max_retries} lần thử.",
            "failed": True
        }

    def _evaluate_single_category(
        self,
        cat_key: str,
        cat_name: str,
        resume_data: Dict[str, Any],
        resume_name: str,
        num_evaluations: int
    ):
        t_cat_start = time.time()
        query_context = json.dumps(self._extract_relevant_resume_field(cat_key, resume_data), ensure_ascii=False)
        top_k = 5 if cat_key == "work_experience" else 3
        retrieved = self.rag.retrieve(cat_key, query_context, top_k=top_k)

        if not retrieved:
            print(f"[Evaluation] Category '{cat_name}' has no HR requirements. Auto-assigning 100/100 score.", file=sys.stderr)
            cat_res = {
                "score": 100,
                "strengths": [f"Không có yêu cầu từ HR cho mục này ({cat_name}) trong JD/Hidden Requirements - Tự động đạt điểm tối đa (100/100)"],
                "gaps": [],
                "evidence_quotes": ["No HR requirements specified for this dimension."],
                "reasoning_summary": "Không có yêu cầu từ HR được chỉ định cho mục này trong mô tả công việc.",
                "all_scores": [100] * num_evaluations,
                "median_score": 100.0
            }
        else:
            if self.backend == "vllm" and num_evaluations > 1:
                from concurrent.futures import ThreadPoolExecutor
                def _run_single_eval(run_i: int) -> Dict[str, Any]:
                    return self.evaluate_category(
                        cat_key, cat_name, resume_data, retrieved, resume_name, run_index=run_i
                    )
                max_workers = min(10, num_evaluations)
                with ThreadPoolExecutor(max_workers=max_workers) as executor:
                    eval_runs = list(executor.map(_run_single_eval, range(1, num_evaluations + 1)))
            else:
                eval_runs = [
                    self.evaluate_category(cat_key, cat_name, resume_data, retrieved, resume_name, run_index=run_i)
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
        num_evaluations: int
    ) -> Dict[str, Any]:
        cat_eval_outputs = {}
        for cat_key, cat_name in CATEGORY_LABELS.items():
            try:
                ck, cn, cat_res, retrieved, elapsed = self._evaluate_single_category(
                    cat_key, cat_name, resume_data, resume_name, num_evaluations
                )
                cat_eval_outputs[ck] = (cn, cat_res, retrieved, elapsed)
            except Exception as e:
                import traceback
                print(f"[Category Eval Error] Exception during execution for '{cat_name}': {e}\n{traceback.format_exc()}", file=sys.stderr)
                cat_eval_outputs[cat_key] = (
                    cat_name,
                    {
                        "score": FALLBACK_ERROR_SCORE,
                        "strengths": [],
                        "gaps": [f"Lỗi xử lý mục đánh giá: {e}"],
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
        num_evaluations: int = 20
    ) -> Dict[str, Any]:
        start_resume_time = time.time()
        standard_req = standard_req or ""
        hidden_req = hidden_req or ""
        resume_data = resume_data if isinstance(resume_data, dict) else {}

        # 1. Ingest requirements into Local RAG
        t_decomp_start = time.time()
        self.rag.ingest_requirements(
            standard_req,
            hidden_req,
            llm_decomposer_func=lambda s, h: self._decompose_requirements_with_llm(s, h, resume_name)
        )
        decomp_time = time.time() - t_decomp_start
        print(f"[Timing Log] [{resume_name}] HR Requirement Categorization took: {decomp_time:.2f}s", file=sys.stderr)

        # 2. Evaluate each category
        cat_eval_outputs = self._evaluate_all_categories(resume_data, resume_name, num_evaluations)

        # 3. Aggregate results
        dimension_results, category_timings, overall_score, recommendation = self._aggregate_evaluation_results(
            cat_eval_outputs, resume_name, num_evaluations
        )

        total_resume_time = time.time() - start_resume_time
        print(f"[Timing Log] [{resume_name}] Total Resume Evaluation Completed in: {total_resume_time:.2f}s", file=sys.stderr)

        # 4. Format output structure
        basic_info = resume_data.get("basic_information")
        basic_info = basic_info if isinstance(basic_info, dict) else {}
        candidate_name = basic_info.get("full_name") or basic_info.get("name") or basic_info.get("email") or resume_name

        evaluation_output = {
            "resume_name": resume_name,
            "candidate_identifier": candidate_name,
            "overall_score": overall_score,
            "match_recommendation": recommendation,
            "evaluated_at": datetime.now().isoformat(),
            "execution_timings": {
                "requirement_decomposition_seconds": round(decomp_time, 2),
                "total_resume_evaluation_seconds": round(total_resume_time, 2),
                "category_timings_seconds": category_timings
            },
            "dimension_scores": dimension_results,
            "hidden_requirements_assessment": dimension_results.get("hidden_culture", {}),
            "summary": {
                "total_strengths": sum([len(v["strengths"]) for v in dimension_results.values()]),
                "total_gaps": sum([len(v["gaps"]) for v in dimension_results.values()])
            }
        }

        # 5. Save report if requested
        self._save_evaluation_report(evaluation_output, resume_name, output_dir, output_path)

        return evaluation_output
