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
import re
import statistics
import threading
from datetime import datetime
from typing import Dict, List, Any, Optional
from src.core.config import DIMENSION_WEIGHTS, EVAL_RESULTS_DIR, DEFAULT_LLM_MODEL, DEFAULT_VLLM_URL, VLLM_REQUEST_TIMEOUT, FALLBACK_ERROR_SCORE, MATCH_THRESHOLDS
from src.core.logger import log_llm_call, log_broken_json
from src.core.json_utils import clean_and_parse_json
from src.providers.rag_engine import LocalCriteriaRAG
from src.prompts.evaluator_prompts import (
    get_evaluator_system_prompt,
    get_requirements_decomposition_system_prompt,
    get_requirements_decomposition_prompt,
    get_category_evaluation_prompt
)



def _clean_and_deduplicate_list(items: Any, max_items: int = 10) -> List[str]:
    """Helper to clean whitespace, remove duplicates while preserving order, and cap item count."""
    if isinstance(items, str):
        items = [items]
    elif not isinstance(items, list):
        items = []

    seen = set()
    cleaned = []
    for item in items:
        s = str(item).strip()
        if s and s not in seen:
            seen.add(s)
            cleaned.append(s)
            if len(cleaned) >= max_items:
                break
    return cleaned




def _validate_category_evaluation(parsed: Any) -> Optional[Dict[str, Any]]:
    """Validates that parsed JSON contains a valid numeric score (0-100) and required output fields."""
    if not isinstance(parsed, dict) or not parsed:
        return None

    score_val = parsed.get("score")
    if score_val is None:
        return None

    try:
        score_str = str(score_val).strip()
        # Reject string placeholders like '<integer>', '<integer 0-100>', or text containing no digits
        if score_str.startswith("<") or not any(c.isdigit() for c in score_str):
            return None
        # Extract digits
        clean_num = re.sub(r'[^0-9.]', '', score_str)
        if not clean_num:
            return None
        score = int(round(float(clean_num)))
    except (ValueError, TypeError):
        return None

    if not (0 <= score <= 100):
        return None

    strengths = _clean_and_deduplicate_list(parsed.get("strengths", []), max_items=10)
    gaps = _clean_and_deduplicate_list(parsed.get("gaps", []), max_items=8)
    quotes = _clean_and_deduplicate_list(parsed.get("evidence_quotes", []), max_items=6)
    reasoning = str(parsed.get("reasoning_summary", "")).strip()

    return {
        "score": score,
        "strengths": strengths,
        "gaps": gaps,
        "evidence_quotes": quotes,
        "reasoning_summary": reasoning
    }


class ResumeEvaluator:
    """
    Resume Evaluator Agent powered by local RAG criteria + Qwen/Qwen3.5-9B.
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
            response = self._get_mock_response(category)
            log_llm_call(prompt, response, category, resume_name, run_index=run_index)
            return response

        if system_prompt is None:
            if category == "requirements_decomposition":
                system_prompt = get_requirements_decomposition_system_prompt()
            else:
                system_prompt = get_evaluator_system_prompt()

        messages = [
            {
                "role": "system",
                "content": system_prompt
            },
            {"role": "user", "content": prompt}
        ]

        response_text = ""
        if self.backend == "transformers":
            import torch
            if self.model is None or self.tokenizer is None:
                self.load_model()

            if hasattr(self.tokenizer, "apply_chat_template"):
                try:
                    formatted_prompt = self.tokenizer.apply_chat_template(
                        messages,
                        tokenize=False,
                        add_generation_prompt=True
                    )
                except Exception:
                    formatted_prompt = prompt
            else:
                formatted_prompt = prompt

            inputs = self.tokenizer(formatted_prompt, return_tensors="pt")
            target_device = self.model.device if hasattr(self.model, "device") else ("cuda" if torch.cuda.is_available() else "cpu")
            inputs = {k: v.to(target_device) for k, v in inputs.items()}
            
            with self._llm_lock:
                with torch.no_grad():
                    outputs = self.model.generate(
                        **inputs,
                        max_new_tokens=8192,
                        temperature=0.2,
                        top_p=0.95,
                        repetition_penalty=1.05,
                        do_sample=True
                    )
            input_len = inputs["input_ids"].shape[1]
            generated_tokens = outputs[0][input_len:]
            response_text = self.tokenizer.decode(generated_tokens, skip_special_tokens=True).strip()

        elif self.backend == "vllm":
            import urllib.request
            import urllib.error
            url = f"{self.vllm_url.rstrip('/')}/chat/completions"
            payload = {
                "model": self.model_name,
                "messages": messages,
                "temperature": 0.2,
                "top_p": 0.95,
                "frequency_penalty": 0.3,
                "presence_penalty": 0.2,
                "repetition_penalty": 1.05,
                "max_tokens": 8192,
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
                        response_text = f"<think>\n{reasoning.strip()}\n</think>\n{content.strip()}"
                    else:
                        response_text = content.strip()
            except Exception as e:
                print(f"[vLLM Call Error] Failed to call vLLM server at {url}: {e}", file=sys.stderr)
                if self.mock:
                    response_text = self._get_mock_response(category)
                else:
                    raise RuntimeError(f"[vLLM Call Fatal Error] Connection to vLLM server at {url} failed: {e}") from e

        log_llm_call(prompt, response_text, category, resume_name, run_index=run_index)
        return response_text

    def _get_mock_response(self, category: str) -> str:
        mock_data = {
            "seniority_title": {
                "evidence_quotes": ["Worked as Senior Software Engineer for 4 years"],
                "strengths": ["Chức danh và cấp bậc rất phù hợp với vị trí tuyển dụng", "Tổng số năm kinh nghiệm đáp ứng yêu cầu cấp senior"],
                "gaps": ["Kinh nghiệm quản lý nhóm còn khiêm tốn"],
                "reasoning_summary": "Ứng viên đáp ứng tốt yêu cầu về số năm kinh nghiệm và vị trí tương đương.",
                "score": 85
            },
            "technical_skills": {
                "evidence_quotes": ["Skills: Python, PyTorch, Docker, PostgreSQL"],
                "strengths": ["Thành thạo các công nghệ Python, FastAPI và SQL", "Có kinh nghiệm thực tế làm việc với các công cụ cloud hiện đại"],
                "gaps": ["Chưa thể hiện rõ kinh nghiệm làm việc với Kubernetes"],
                "reasoning_summary": "Đáp ứng đầy đủ các kỹ năng cốt lõi được yêu cầu trong JD.",
                "score": 90
            },
            "work_experience": {
                "evidence_quotes": ["Built microservice backend handling 10k RPS"],
                "strengths": ["Có thành tích tốt trong các dự án quy mô lớn", "Kết quả dự án rõ ràng, có chỉ số đo lường cụ thể"],
                "gaps": ["Thời gian gắn bó tại dự án gần nhất tương đối ngắn (6 tháng)"],
                "reasoning_summary": "Kinh nghiệm thực tế sát với yêu cầu công việc.",
                "score": 82
            },
            "education_certifications": {
                "evidence_quotes": ["BS in Computer Science - VNU-HCM"],
                "strengths": ["Bằng Cử nhân Chuyên ngành Khoa học Máy tính", "Có các chứng chỉ kỹ thuật chuyên môn phù hợp"],
                "gaps": ["Chưa có bằng Thạc sĩ"],
                "reasoning_summary": "Bằng cấp phù hợp với yêu cầu tuyển dụng.",
                "score": 88
            },
            "hidden_culture": {
                "evidence_quotes": ["Active open-source contributor & tech blogger"],
                "strengths": ["Tinh thần chủ động học hỏi và tự nâng cao trình độ", "Kỹ năng giao tiếp tốt bằng cả tiếng Anh và tiếng Việt"],
                "gaps": ["Có thể ưu tiên hình thức làm việc hybrid hơn làm việc 100% tại văn phòng"],
                "reasoning_summary": "Đánh giá văn hóa cho thấy mức độ gắn kết và chủ động cao.",
                "score": 80
            }
        }
        return json.dumps(mock_data.get(category, {
            "evidence_quotes": ["Extracted from resume context"],
            "strengths": ["Ứng viên có nền tảng tổng thể phù hợp"],
            "gaps": ["Cần bổ sung và xác minh thêm thông tin chi tiết"],
            "reasoning_summary": "Đánh giá tổng quan dựa trên thông tin sơ bộ.",
            "score": 75
        }), ensure_ascii=False)

    def _decompose_requirements_with_llm(
        self,
        standard_req: str,
        hidden_req: str,
        resume_name: str = "job_requirements"
    ) -> Optional[Dict[str, List[str]]]:
        categories = ["seniority_title", "technical_skills", "work_experience", "education_certifications", "hidden_culture"]
        standard_req = (standard_req or "").strip()
        hidden_req = (hidden_req or "").strip()

        if not standard_req and not hidden_req:
            return {cat: [] for cat in categories}

        if self.mock:
            return self._get_mock_decomposed_requirements(standard_req, hidden_req)

        prompt = get_requirements_decomposition_prompt(standard_req, hidden_req, self.model_name)
        raw_out = self._call_llm(prompt, "requirements_decomposition", resume_name)
        parsed = clean_and_parse_json(raw_out)

        if parsed and isinstance(parsed, dict):
            cleaned = {}
            for cat in categories:
                items = parsed.get(cat, [])
                if isinstance(items, str):
                    items = [items]
                elif not isinstance(items, list):
                    items = []
                cleaned[cat] = [str(x).strip() for x in items if str(x).strip()]
            return cleaned

        if raw_out and any(cat in raw_out for cat in categories):
            print("[LocalRAG Warning] JSON parse failed, parsing text headers from LLM decomposition output...", file=sys.stderr)
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

    def _get_mock_decomposed_requirements(self, standard_req: str, hidden_req: str) -> Dict[str, List[str]]:
        lines_std = [l.strip() for l in standard_req.split('\n') if l.strip()]
        lines_hid = [l.strip() for l in hidden_req.split('\n') if l.strip()]
        
        result = {
            "seniority_title": [],
            "technical_skills": [],
            "work_experience": [],
            "education_certifications": [],
            "hidden_culture": lines_hid or []
        }
        
        for line in lines_std:
            line_low = line.lower()
            if any(w in line_low for w in ["năm", "year", "senior", "junior", "level", "vị trí", "chức danh", "c&b", "kinh nghiệm"]):
                result["seniority_title"].append(line)
            if any(w in line_low for w in ["skill", "python", "java", "sql", "kỹ năng", "thành thạo", "công nghệ"]):
                result["technical_skills"].append(line)
            if any(w in line_low for w in ["bằng", "đại học", "degree", "bachelor", "chứng chỉ", "certificate", "toeic", "ielts"]):
                result["education_certifications"].append(line)
            if any(w in line_low for w in ["công việc", "nhiệm vụ", "mô tả", "trách nhiệm", "kinh nghiệm", "dự án"]):
                result["work_experience"].append(line)

        return result

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
            validated = _validate_category_evaluation(parsed)

            if validated is not None:
                validated["failed"] = False
                return validated

            error_reason = "JSON parse failed, empty dict, or invalid non-numeric score returned (e.g. '<integer>')"
            print(f"[Eval Retry] Attempt {attempt}/{max_retries} for category '{category}' failed to produce valid numeric score. Retrying...", file=sys.stderr)
            log_broken_json(prompt, raw_out, category, resume_name, attempt=attempt, error_reason=error_reason, run_index=run_index)

        fatal_category_banner = f"""
================================================================================
 💥 FATAL CATEGORY EVALUATION FAILURE 💥
 Candidate/Resume : '{resume_name}'
 Category         : '{category_name}' ({category})
 Error            : Failed to produce valid numeric JSON score after {max_retries} retries!
================================================================================
"""
        print(fatal_category_banner, file=sys.stderr)
        log_broken_json(prompt, raw_out, category, resume_name, attempt=max_retries, error_reason=f"Max retries ({max_retries}) reached without valid numeric score", run_index=run_index)
        return {
            "score": 0,
            "strengths": [],
            "gaps": [f"Không thể phân tích dữ liệu đánh giá từ mô hình (Format JSON/Score không hợp lệ sau {max_retries} lần thử)"],
            "evidence_quotes": [],
            "reasoning_summary": f"THẤT BẠI DỮ LIỆU: Không thể phân tích JSON hợp lệ sau {max_retries} lần thử.",
            "failed": True
        }


    def _extract_relevant_resume_field(self, category: str, resume: Dict[str, Any]) -> Dict[str, Any]:
        resume = resume if isinstance(resume, dict) else {}
        work_exp = resume.get("work_experience", [])
        work_exp_list = work_exp if isinstance(work_exp, list) else []

        if category == "seniority_title":
            work_exp_summary = []
            for w in work_exp_list:
                if isinstance(w, dict):
                    pos = w.get("position", "")
                    comp = w.get("company_name", "")
                    dur = w.get("duration", "")
                    comp_info = w.get("company_description") or w.get("company_size") or w.get("industry") or ""
                    if comp_info:
                        work_exp_summary.append(f"{pos} tại {comp} ({comp_info}) ({dur})")
                    else:
                        work_exp_summary.append(f"{pos} tại {comp} ({dur})")
                elif isinstance(w, str):
                    work_exp_summary.append(w)
            return {
                "position_applied": resume.get("position_applied", {}),
                "self_evaluation": resume.get("self_evaluation", ""),
                "work_experience_history": work_exp_summary,
                "work_experience_details": work_exp_list
            }
        elif category == "technical_skills":
            return {
                "skills_and_specialties": resume.get("skills_and_specialties", []),
                "languages": resume.get("languages", [])
            }
        elif category == "work_experience":
            return {
                "work_experience": work_exp_list,
                "projects": resume.get("projects", []),
                "skills_and_specialties": resume.get("skills_and_specialties", [])
            }
        elif category == "education_certifications":
            return {
                "education_background": resume.get("education_background", []),
                "certifications": resume.get("certifications", []),
                "languages": resume.get("languages", [])
            }
        else:
            summary_lines = []
            for w in work_exp_list:
                if isinstance(w, dict):
                    resp = w.get("responsibilities", "")
                    if resp:
                        summary_lines.append(str(resp))
                elif isinstance(w, str):
                    summary_lines.append(w)
            return {
                "self_evaluation": resume.get("self_evaluation", ""),
                "basic_information": resume.get("basic_information", {}),
                "work_experience_summary": summary_lines
            }

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

        t_decomp_start = time.time()
        self.rag.ingest_requirements(
            standard_req,
            hidden_req,
            llm_decomposer_func=lambda s, h: self._decompose_requirements_with_llm(s, h, resume_name)
        )
        decomp_time = time.time() - t_decomp_start
        print(f"[Timing Log] [{resume_name}] HR Requirement Categorization (Decomposition) took: {decomp_time:.2f}s", file=sys.stderr)

        category_labels = {
            "seniority_title": "Position & Seniority Match",
            "technical_skills": "Technical Skills & Competencies",
            "work_experience": "Work Experience & Project Relevance",
            "education_certifications": "Education & Certifications",
            "hidden_culture": "HR Hidden Requirements & Culture Fit"
        }

        dimension_results = {}
        category_timings = {}
        weighted_total = 0.0

        def _evaluate_category_task(cat_key, cat_name):
            t_cat_start = time.time()
            query_context = json.dumps(self._extract_relevant_resume_field(cat_key, resume_data), ensure_ascii=False)
            top_k = 5 if cat_key == "work_experience" else 3
            retrieved = self.rag.retrieve(cat_key, query_context, top_k=top_k)

            if not retrieved or len(retrieved) == 0:
                print(f"[Evaluation] Category '{cat_name}' has no HR requirements in JD/Hidden Requirements. Auto-assigning 100/100 score.", file=sys.stderr)
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
                            cat_key,
                            cat_name,
                            resume_data,
                            retrieved,
                            resume_name,
                            run_index=run_i
                        )
                    max_workers = min(10, num_evaluations)
                    with ThreadPoolExecutor(max_workers=max_workers) as executor:
                        eval_runs = list(executor.map(_run_single_eval, range(1, num_evaluations + 1)))
                else:
                    eval_runs = []
                    for run_i in range(1, num_evaluations + 1):
                        run_res = self.evaluate_category(
                            cat_key,
                            cat_name,
                            resume_data,
                            retrieved,
                            resume_name,
                            run_index=run_i
                        )
                        eval_runs.append(run_res)

                has_category_failure = any(r.get("failed", False) for r in eval_runs)
                scores = [r.get("score", FALLBACK_ERROR_SCORE) for r in eval_runs]
                sorted_runs = sorted(eval_runs, key=lambda r: r.get("score", FALLBACK_ERROR_SCORE))
                med_score = int(round(float(statistics.median(scores))))
                # Select the median result: middle item in sorted_runs
                median_idx = (len(sorted_runs) - 1) // 2
                cat_res = dict(sorted_runs[median_idx])
                cat_res["score"] = med_score
                cat_res["median_score"] = float(med_score)
                cat_res["all_scores"] = scores
                if has_category_failure:
                    cat_res["failed"] = True

            elapsed_cat = time.time() - t_cat_start
            print(f"[Timing Log] [{resume_name}] Category '{cat_name}' ({cat_key}) {num_evaluations}-run evaluation took: {elapsed_cat:.2f}s (Median Score: {cat_res.get('score')})", file=sys.stderr)
            return cat_key, cat_name, cat_res, retrieved, elapsed_cat

        cat_eval_outputs = {}
        for cat_key, cat_name in category_labels.items():
            try:
                cat_key, cat_name, cat_res, retrieved, elapsed_cat = _evaluate_category_task(cat_key, cat_name)
                cat_eval_outputs[cat_key] = (cat_name, cat_res, retrieved, elapsed_cat)
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

        any_evaluation_failed = False
        failed_categories = []

        for cat_key, cat_name in category_labels.items():
            if cat_key in cat_eval_outputs:
                cat_name, cat_res, retrieved, elapsed_cat = cat_eval_outputs[cat_key]
            else:
                cat_res = {
                    "score": FALLBACK_ERROR_SCORE,
                    "strengths": [],
                    "gaps": ["Lỗi xử lý mục đánh giá"],
                    "evidence_quotes": [],
                    "reasoning_summary": "Evaluation error.",
                    "error": "Category not processed",
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

        total_resume_time = time.time() - start_resume_time
        print(f"[Timing Log] [{resume_name}] Total Resume Evaluation Completed in: {total_resume_time:.2f}s", file=sys.stderr)

        if any_evaluation_failed:
            failed_cats_str = ", ".join(failed_categories)
            fatal_evaluation_banner = f"""
================================================================================
 🚨 FATAL EVALUATION FAILURE FOR RESUME: '{resume_name}' 🚨
 REASON  : Category evaluation [{failed_cats_str}] failed JSON parsing after 30 retries.
 ACTION  : Evaluation FLAGGED AS TOTAL FAILURE. Forcing ALL dimension scores & overall score to 0!
================================================================================
"""
            print(fatal_evaluation_banner, file=sys.stderr)

            # Override all dimension scores to 0
            for cat_key in dimension_results:
                dimension_results[cat_key]["score"] = 0
                dimension_results[cat_key]["weighted_score"] = 0.0
                dimension_results[cat_key]["median_score"] = 0.0
                dimension_results[cat_key]["all_run_scores"] = [0] * num_evaluations
                dimension_results[cat_key]["reasoning_summary"] = f"EVALUATION FAILED: JSON parse failed after 30 retries in category '{failed_cats_str}'."

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

        out_target = None
        if output_path:
            out_target = output_path
        elif output_dir:
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

        return evaluation_output
