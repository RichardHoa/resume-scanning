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
from datetime import datetime
from typing import Dict, List, Any, Optional
from src.core.config import DIMENSION_WEIGHTS, EVAL_RESULTS_DIR, DEFAULT_LLM_MODEL, DEFAULT_VLLM_URL
from src.core.logger import log_llm_call
from src.core.json_utils import clean_and_parse_json
from src.providers.rag_engine import LocalCriteriaRAG
from src.prompts.evaluator_prompts import (
    get_requirements_decomposition_prompt,
    get_category_evaluation_prompt
)


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

    def _call_llm(self, prompt: str, category: str, resume_name: str = "candidate") -> str:
        if self.mock:
            response = self._get_mock_response(category)
            log_llm_call(prompt, response, category, resume_name)
            return response

        response_text = ""
        if self.backend == "transformers":
            import torch
            if self.model is None or self.tokenizer is None:
                self.load_model()

            inputs = self.tokenizer(prompt, return_tensors="pt")
            target_device = self.model.device if hasattr(self.model, "device") else ("cuda" if torch.cuda.is_available() else "cpu")
            inputs = {k: v.to(target_device) for k, v in inputs.items()}
            
            with torch.no_grad():
                outputs = self.model.generate(
                    **inputs,
                    max_new_tokens=10000,
                    temperature=0.2,
                    do_sample=True
                )
            input_len = inputs["input_ids"].shape[1]
            generated_tokens = outputs[0][input_len:]
            response_text = self.tokenizer.decode(generated_tokens, skip_special_tokens=True).strip()

        elif self.backend == "vllm":
            current_date_str = datetime.now().strftime("%Y-%m-%d")
            import urllib.request
            url = f"{self.vllm_url.rstrip('/')}/chat/completions"
            payload = {
                "model": self.model_name,
                "messages": [
                    {"role": "system", "content": f"You are a professional HR Evaluation Agent. Current Date: {current_date_str}. Output strictly valid JSON. All evaluation strengths and gaps MUST be written in Vietnamese (Tiếng Việt)."},
                    {"role": "user", "content": prompt}
                ],
                "temperature": 0.2,
                "max_tokens": 4096
            }
            req = urllib.request.Request(
                url,
                data=json.dumps(payload).encode("utf-8"),
                headers={"Content-Type": "application/json"}
            )
            try:
                with urllib.request.urlopen(req, timeout=60) as resp:
                    res_data = json.loads(resp.read().decode("utf-8"))
                    response_text = res_data["choices"][0]["message"]["content"].strip()
            except Exception as e:
                print(f"[vLLM Call Error] {e}. Falling back to mock response.", file=sys.stderr)
                response_text = self._get_mock_response(category)

        log_llm_call(prompt, response_text, category, resume_name)
        return response_text

    def _get_mock_response(self, category: str) -> str:
        mock_data = {
            "seniority_title": {
                "score": 85,
                "strengths": ["Chức danh và cấp bậc rất phù hợp với vị trí tuyển dụng", "Tổng số năm kinh nghiệm đáp ứng yêu cầu cấp senior"],
                "gaps": ["Kinh nghiệm quản lý nhóm còn khiêm tốn"],
                "evidence_quotes": ["Worked as Senior Software Engineer for 4 years"]
            },
            "technical_skills": {
                "score": 90,
                "strengths": ["Thành thạo các công nghệ Python, FastAPI và SQL", "Có kinh nghiệm thực tế làm việc với các công cụ cloud hiện đại"],
                "gaps": ["Chưa thể hiện rõ kinh nghiệm làm việc với Kubernetes"],
                "evidence_quotes": ["Skills: Python, PyTorch, Docker, PostgreSQL"]
            },
            "work_experience": {
                "score": 82,
                "strengths": ["Có thành tích tốt trong các dự án quy mô lớn", "Kết quả dự án rõ ràng, có chỉ số đo lường cụ thể"],
                "gaps": ["Thời gian gắn bó tại dự án gần nhất tương đối ngắn (6 tháng)"],
                "evidence_quotes": ["Built microservice backend handling 10k RPS"]
            },
            "education_certifications": {
                "score": 88,
                "strengths": ["Bằng Cử nhân Chuyên ngành Khoa học Máy tính", "Có các chứng chỉ kỹ thuật chuyên môn phù hợp"],
                "gaps": ["Chưa có bằng Thạc sĩ"],
                "evidence_quotes": ["BS in Computer Science - VNU-HCM"]
            },
            "hidden_culture": {
                "score": 80,
                "strengths": ["Tinh thần chủ động học hỏi và tự nâng cao trình độ", "Kỹ năng giao tiếp tốt bằng cả tiếng Anh và tiếng Việt"],
                "gaps": ["Có thể ưu tiên hình thức làm việc hybrid hơn làm việc 100% tại văn phòng"],
                "evidence_quotes": ["Active open-source contributor & tech blogger"]
            }
        }
        return json.dumps(mock_data.get(category, {
            "score": 80,
            "strengths": ["Ứng viên có nền tảng tổng thể phù hợp"],
            "gaps": ["Cần bổ sung và xác minh thêm thông tin chi tiết"],
            "evidence_quotes": ["Extracted from resume context"]
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
        resume_name: str
    ) -> Dict[str, Any]:
        resume_snippet = self._extract_relevant_resume_field(category, resume_data)
        prompt = get_category_evaluation_prompt(category_name, self.model_name, retrieved_criteria, resume_snippet)

        raw_out = self._call_llm(prompt, category, resume_name)
        parsed = clean_and_parse_json(raw_out)

        if parsed and isinstance(parsed, dict):
            try:
                score = int(parsed.get("score", 70))
            except (ValueError, TypeError):
                score = 70
            score = max(0, min(100, score))

            strengths = parsed.get("strengths", [])
            if isinstance(strengths, str): strengths = [strengths]
            elif not isinstance(strengths, list): strengths = []
            
            gaps = parsed.get("gaps", [])
            if isinstance(gaps, str): gaps = [gaps]
            elif not isinstance(gaps, list): gaps = []

            quotes = parsed.get("evidence_quotes", [])
            if isinstance(quotes, str): quotes = [quotes]
            elif not isinstance(quotes, list): quotes = []

            return {
                "score": score,
                "strengths": [str(s) for s in strengths],
                "gaps": [str(g) for g in gaps],
                "evidence_quotes": [str(q) for q in quotes]
            }

        return {
            "score": 75,
            "strengths": ["Ứng viên có nền tảng chuyên môn phù hợp quan sát được trong hồ sơ"],
            "gaps": ["Cần xác minh thêm thông tin chi tiết trong buổi phỏng vấn"],
            "evidence_quotes": ["Khớp thông tin từ hồ sơ ứng viên"]
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
                    work_exp_summary.append(f"{pos} tại {comp} ({dur})")
                elif isinstance(w, str):
                    work_exp_summary.append(w)
            return {
                "position_applied": resume.get("position_applied", {}),
                "self_evaluation": resume.get("self_evaluation", ""),
                "work_experience_history": work_exp_summary
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
        resume_name: str = "candidate"
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

        for cat_key, cat_name in category_labels.items():
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
                    "evidence_quotes": ["No HR requirements specified for this dimension."]
                }
            else:
                cat_res = self.evaluate_category(cat_key, cat_name, resume_data, retrieved, resume_name)

            elapsed_cat = time.time() - t_cat_start
            category_timings[cat_key] = round(elapsed_cat, 2)
            print(f"[Timing Log] [{resume_name}] Category '{cat_name}' ({cat_key}) evaluation took: {elapsed_cat:.2f}s", file=sys.stderr)

            weight = DIMENSION_WEIGHTS.get(cat_key, 0.20)
            score = cat_res.get("score", 70)
            
            dimension_results[cat_key] = {
                "category_name": cat_name,
                "weight": weight,
                "score": score,
                "weighted_score": round(score * weight, 2),
                "strengths": cat_res.get("strengths", []),
                "gaps": cat_res.get("gaps", []),
                "evidence_quotes": cat_res.get("evidence_quotes", []),
                "retrieved_criteria": retrieved,
                "processing_time_seconds": round(elapsed_cat, 2)
            }
            weighted_total += score * weight

        total_resume_time = time.time() - start_resume_time
        print(f"[Timing Log] [{resume_name}] Total Resume Evaluation Completed in: {total_resume_time:.2f}s", file=sys.stderr)

        overall_score = round(weighted_total, 1)

        if overall_score >= 85:
            recommendation = "STRONG_MATCH"
        elif overall_score >= 70:
            recommendation = "POTENTIAL_MATCH"
        elif overall_score >= 55:
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

        out_filename = f"{re.sub(r'[^a-zA-Z0-9_-]', '_', resume_name)}_evaluation.json"
        out_path = os.path.join(EVAL_RESULTS_DIR, out_filename)
        try:
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(evaluation_output, f, ensure_ascii=False, indent=2)
            print(f"[Evaluation Complete] Report saved to {out_path}", file=sys.stderr)
        except Exception as e:
            print(f"[Save Error] Failed to write evaluation output: {e}", file=sys.stderr)

        return evaluation_output
