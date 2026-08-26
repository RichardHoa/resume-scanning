"""
DSPy Prompt Optimizer & Metric Evaluation Engine (Technique A)

This module implements Stanford DSPy teleprompter compilation for training 
and optimizing evaluation prompts against candidate ground truth target categories.
"""

import os
import sys
import json
import re
import logging
import statistics
import traceback
from typing import Dict, List, Any, Optional, Tuple

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import warnings
warnings.filterwarnings("ignore", category=UserWarning, module="dspy.*")
logging.getLogger("dspy").setLevel(logging.WARNING)

from src.core.config import (
    MATCH_THRESHOLDS, DIMENSION_WEIGHTS, DEFAULT_LLM_MODEL, DEFAULT_VLLM_URL, MAX_NEW_TOKENS, DSPY_MAX_TOKENS
)
from src.prompts.evaluator_prompts import get_evaluator_system_prompt
from src.pipelines.evaluator_backend import CATEGORY_LABELS
from src.pipelines.evaluator_utils import extract_relevant_resume_field

logger = logging.getLogger(__name__)

GROUND_TRUTH_DATASET_PATH = os.path.join(_PROJECT_ROOT, "data", "candidate_ground_truth.json")


def load_candidate_ground_truth(dataset_path: str = GROUND_TRUTH_DATASET_PATH) -> Dict[str, Any]:
    """Loads candidate email & filename to target category mapping dataset."""
    if not os.path.exists(dataset_path):
        raise FileNotFoundError(f"Candidate ground truth dataset not found at {dataset_path}")
    with open(dataset_path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_rag_criteria_by_category() -> Dict[str, str]:
    """
    Loads HR requirement criteria for all 5 evaluation categories 
    from persistent LocalCriteriaRAG or hr_rag.txt summary.
    """
    criteria_map = {
        "seniority_title": "Cần 3+ năm kinh nghiệm vị trí tương đương hoặc quản lý.",
        "technical_skills": "Kỹ năng chuyên môn Python, FastAPI, PostgreSQL, RAG, System Design.",
        "work_experience": "Kinh nghiệm thực hiện các dự án thực tế, chịu trách nhiệm kết quả công việc.",
        "education_certifications": "Tốt nghiệp Đại học chuyên ngành CNTT/Toán tin hoặc có chứng chỉ chuyên môn.",
        "hidden_culture": "Thái độ làm việc chuyên nghiệp, có tinh thần cầu tiến và khả năng làm việc nhóm."
    }

    # 1. Attempt loading from LocalCriteriaRAG DB
    try:
        from src.providers.rag_engine import LocalCriteriaRAG
        rag = LocalCriteriaRAG()
        if rag.documents:
            grouped = {}
            for doc in rag.documents:
                cat = doc.get("category")
                text = doc.get("text")
                if cat and text:
                    grouped.setdefault(cat, []).append(str(text))
            for cat, items in grouped.items():
                if items:
                    criteria_map[cat] = "\n".join(items)
            print(f"[DSPy Dataset] Loaded RAG criteria from ChromaDB vector store for {len(grouped)} dimensions.", file=sys.stderr)
            return criteria_map
    except Exception as e:
        print(f"[DSPy Dataset Warning] Failed loading criteria from LocalCriteriaRAG DB ({e}). Trying fallback...", file=sys.stderr)

    # 2. Attempt parsing hr_rag.txt
    hr_rag_path = os.path.join(_PROJECT_ROOT, "hr_rag.txt")
    if os.path.exists(hr_rag_path):
        try:
            with open(hr_rag_path, "r", encoding="utf-8") as f:
                content = f.read()
            sections = content.split("[")
            for sec in sections:
                if "]" in sec:
                    header, body = sec.split("]", 1)
                    header_clean = header.lower()
                    lines = [line.strip() for line in body.splitlines() if line.strip() and not line.startswith("=")]
                    cleaned_lines = []
                    for l in lines:
                        if l.startswith("Total items") or l.startswith("(No items"):
                            continue
                        clean_item = re.sub(r'^\d+\.\s*', '', l).strip()
                        if clean_item:
                            cleaned_lines.append(clean_item)

                    if cleaned_lines:
                        if "seniority" in header_clean or "senio" in header_clean:
                            criteria_map["seniority_title"] = "\n".join(cleaned_lines)
                        elif "technical" in header_clean or "tech" in header_clean:
                            criteria_map["technical_skills"] = "\n".join(cleaned_lines)
                        elif "work" in header_clean or "exp" in header_clean:
                            criteria_map["work_experience"] = "\n".join(cleaned_lines)
                        elif "education" in header_clean or "educ" in header_clean:
                            criteria_map["education_certifications"] = "\n".join(cleaned_lines)
                        elif "hidden" in header_clean or "hidd" in header_clean:
                            criteria_map["hidden_culture"] = "\n".join(cleaned_lines)
            print(f"[DSPy Dataset] Loaded RAG criteria from hr_rag.txt file.", file=sys.stderr)
        except Exception as e:
            print(f"[DSPy Dataset Warning] Failed parsing hr_rag.txt ({e}). Using default criteria.", file=sys.stderr)

    return criteria_map


def calculate_category_metric(predicted_score: float, target_category: str) -> float:
    """
    Evaluates metric score (0.0 to 1.0) for a predicted overall score against target category.
    - STRONG_MATCH: score >= 85 (Tier 1)
    - POTENTIAL_MATCH: 70 <= score < 85 (Tier 2)
    - LOW_MATCH: score < 70 (Tier 3)
    """
    strong_thresh = MATCH_THRESHOLDS.get("STRONG", 85)
    potential_thresh = MATCH_THRESHOLDS.get("POTENTIAL", 70)

    if predicted_score >= strong_thresh:
        pred_cat = "STRONG_MATCH"
    elif predicted_score >= potential_thresh:
        pred_cat = "POTENTIAL_MATCH"
    else:
        pred_cat = "LOW_MATCH"

    if pred_cat == target_category:
        return 1.0

    # Partial reward if close to target boundary
    if target_category == "STRONG_MATCH":
        return max(0.0, 1.0 - (strong_thresh - predicted_score) / 30.0)
    elif target_category == "POTENTIAL_MATCH":
        dist = min(abs(predicted_score - potential_thresh), abs(predicted_score - strong_thresh))
        return max(0.0, 1.0 - dist / 20.0)
    else:
        return max(0.0, 1.0 - (predicted_score - potential_thresh) / 30.0)


_DSPY_EVALUATOR_INSTRUCTIONS = """
You are an objective criteria-matching evaluator. Evaluate candidate resume data strictly and neutrally against the explicitly provided job criteria.
1. STRICT LITERAL ADHERENCE: Ground your evaluation exclusively in the stated criteria. Do NOT add unstated requirements, unrequested expectations (such as demanding metrics or numbers unless explicitly specified in the criterion), or personal assumptions.
2. UNBIASED ATOMIC VERIFICATION: Evaluate candidate evidence for each stated criterion independently across 3 discrete verdict levels:
   - Strong Evidence: The resume explicitly states or demonstrates meeting this criterion directly as written.
   - Partial Evidence: The resume demonstrates partial or related match, but does not fully satisfy the criterion as written.
   - No Evidence: The resume contains no mention or evidence matching this criterion.
3. All text in strengths, gaps, and reasoning_summary must be written concisely in Vietnamese (Tiếng Việt).
4. CRITICAL FORMAT RULE: Output strictly the required fields directly. Do NOT include thinking process, preambles, reasoning monologues, conversational remarks, or markdown commentary outside the fields.
""".strip()

# DSPy Program and Signature definitions
try:
    import dspy

    class ResumeDimensionSignature(dspy.Signature):
        """Evaluate candidate resume snippet against HR criteria across the 5 evaluation dimensions."""
        category_name = dspy.InputField(desc="HR evaluation dimension (e.g. Position & Seniority Match, Technical Skills, Work Experience, Education & Certifications, Hidden Culture Fit)")
        job_criteria = dspy.InputField(desc="Verbatim job criteria from HR requirement database")
        resume_snippet = dspy.InputField(desc="Extracted candidate resume text snippet for this specific dimension")

        evidence_quotes = dspy.OutputField(desc="Direct verbatim quotes from resume snippet supporting evaluation (list of maximum 5 items)")
        strengths = dspy.OutputField(desc="2-4 verified strengths grounded strictly in explicit criteria written in Vietnamese (Tiếng Việt)")
        gaps = dspy.OutputField(desc="2-4 verified gaps grounded strictly in explicit criteria written in Vietnamese (Tiếng Việt)")
        reasoning_summary = dspy.OutputField(desc="3-5 analytical sentences in Vietnamese (Tiếng Việt) justifying score via evidence synthesis")
        score = dspy.OutputField(desc="Integer rating strictly from 0 to 100 representing candidate match level")

    # Bind evaluator system prompt instructions & docstring to signature class
    ResumeDimensionSignature.__doc__ = _DSPY_EVALUATOR_INSTRUCTIONS
    if hasattr(ResumeDimensionSignature, "instructions"):
        ResumeDimensionSignature.instructions = _DSPY_EVALUATOR_INSTRUCTIONS

    class DSPyResumeEvaluatorModule(dspy.Module):
        """DSPy Evaluation Module using Predict with median score evaluation."""
        def __init__(self, eval_runs_per_category: int = 1, language: str = "vietnamese"):
            super().__init__()
            self.evaluate_dimension = dspy.Predict(ResumeDimensionSignature)
            self.eval_runs_per_category = max(1, eval_runs_per_category)
            self.language = language

        def forward(
            self,
            category_name: str = "Technical Skills & Competencies",
            job_criteria: str = "Standard HR criteria: payroll calculation, PIT tax filing, social insurance compliance, labor law.",
            resume_snippet: str = "Candidate resume section data",
            **kwargs
        ):
            if self.eval_runs_per_category > 1:
                scores = []
                last_res = None
                for _ in range(self.eval_runs_per_category):
                    res = self.evaluate_dimension(
                        category_name=category_name,
                        job_criteria=job_criteria,
                        resume_snippet=resume_snippet
                    )
                    last_res = res
                    s = extract_score_from_pred(res)
                    scores.append(s if s is not None else 0.0)

                med_score = int(round(float(statistics.median(scores))))
                if last_res:
                    last_res.score = str(med_score)
                return last_res
            else:
                return self.evaluate_dimension(
                    category_name=category_name,
                    job_criteria=job_criteria,
                    resume_snippet=resume_snippet
                )

    HAS_DSPY = True

except ImportError:
    HAS_DSPY = False
    DSPyResumeEvaluatorModule = None


def extract_score_from_pred(pred: Any) -> Optional[float]:
    """Extracts numerical 0-100 score from DSPy prediction object."""
    if pred is None:
        return None
    raw = getattr(pred, "score", None)
    if raw is None:
        return None
    if isinstance(raw, (int, float)):
        return float(raw)

    raw_str = str(raw).strip()
    try:
        return float(raw_str)
    except Exception:
        pass

    match = re.search(r'(\d+(?:\.\d+)?)', raw_str)
    if match:
        try:
            return float(match.group(1))
        except Exception:
            pass

    return None


def dspy_metric_evaluator(example, pred, trace=None) -> float:
    """
    DSPy optimization metric function assessing prediction accuracy.
    Enforces strict numerical 0-100 score evaluation.
    """
    score_val = extract_score_from_pred(pred)
    if score_val is None or not (0.0 <= score_val <= 100.0):
        return 0.0

    target_cat = getattr(example, "target_category", "LOW_MATCH")
    return calculate_category_metric(score_val, target_cat)


def inspect_and_save_dspy_history(
    models: Optional[List[Any]] = None,
    max_tokens: int = DSPY_MAX_TOKENS,
    output_log_dir: Optional[str] = None
):
    """
    Inspects DSPy LM interaction history, identifies truncated responses (finish_reason == 'length'
    or token limit reached), and writes diagnostic details to disk and console for inspection.
    """
    try:
        import dspy
    except ImportError:
        return

    if models is None:
        models = []
    if hasattr(dspy, "settings") and hasattr(dspy.settings, "lm") and dspy.settings.lm not in models:
        models.append(dspy.settings.lm)

    all_history = []
    for m in models:
        hist = getattr(m, "history", None)
        if hist and isinstance(hist, list):
            all_history.extend(hist)

    if not all_history:
        return

    total_calls = len(all_history)
    truncated_calls = []

    for idx, entry in enumerate(all_history):
        if not isinstance(entry, dict):
            continue

        is_truncated = False
        finish_reason = entry.get("finish_reason") or ""
        
        # Check standard finish_reason indicators
        if finish_reason in ("length", "max_tokens"):
            is_truncated = True
        
        # Check nested OpenAI/vLLM response choices
        resp_obj = entry.get("response")
        if isinstance(resp_obj, dict):
            choices = resp_obj.get("choices", [])
            for c in choices:
                if isinstance(c, dict) and c.get("finish_reason") in ("length", "max_tokens"):
                    is_truncated = True
                    if not finish_reason:
                        finish_reason = c.get("finish_reason")
        elif hasattr(resp_obj, "choices"):
            for c in getattr(resp_obj, "choices", []):
                if getattr(c, "finish_reason", None) in ("length", "max_tokens"):
                    is_truncated = True
                    if not finish_reason:
                        finish_reason = getattr(c, "finish_reason")

        # Check token usage against model/entry specific max_tokens
        call_max_tokens = (
            (entry.get("kwargs") or {}).get("max_tokens")
            or entry.get("max_tokens")
            or max_tokens
        )
        usage = entry.get("usage")
        comp_tokens = 0
        if isinstance(usage, dict):
            comp_tokens = usage.get("completion_tokens", 0)
        elif hasattr(usage, "completion_tokens"):
            comp_tokens = getattr(usage, "completion_tokens", 0)
        elif resp_obj:
            resp_usage = getattr(resp_obj, "usage", None) or (resp_obj.get("usage") if isinstance(resp_obj, dict) else None)
            if isinstance(resp_usage, dict):
                comp_tokens = resp_usage.get("completion_tokens", 0)
            elif hasattr(resp_usage, "completion_tokens"):
                comp_tokens = getattr(resp_usage, "completion_tokens", 0)

        if comp_tokens and call_max_tokens and comp_tokens >= call_max_tokens:
            is_truncated = True
            if not finish_reason:
                finish_reason = "max_tokens_limit_reached"

        if is_truncated:
            truncated_calls.append((idx, entry, finish_reason, comp_tokens, call_max_tokens))

    print(f"\n[DSPy Inspection] Analyzed {total_calls} LM interaction(s) during training session.", file=sys.stderr)
    if truncated_calls:
        print(f"[DSPy Inspection WARNING] Found {len(truncated_calls)}/{total_calls} response(s) TRUNCATED due to exceeding token limit!", file=sys.stderr)
        log_dir = output_log_dir or os.path.join(_PROJECT_ROOT, "logs")
        os.makedirs(log_dir, exist_ok=True)
        json_log_path = os.path.join(log_dir, "dspy_truncated_interactions.json")
        txt_log_path = os.path.join(log_dir, "dspy_truncated_interactions.log")

        serialized_data = []
        with open(txt_log_path, "w", encoding="utf-8") as txt_f:
            txt_f.write(f"=== DSPY TRUNCATED LM RESPONSES REPORT ({len(truncated_calls)} truncated of {total_calls} total) ===\n\n")
            for t_idx, (call_idx, entry, reason, comp_tok, max_tok) in enumerate(truncated_calls, 1):
                prompt_str = str(entry.get("prompt") or entry.get("messages") or "")
                resp_str = str(entry.get("response") or entry.get("outputs") or "")
                usage_info = entry.get("usage") or {}

                record = {
                    "call_index": call_idx,
                    "finish_reason": reason or "length",
                    "completion_tokens": comp_tok,
                    "max_tokens_limit": max_tok,
                    "usage": usage_info,
                    "prompt_snippet": prompt_str[:1000] + ("..." if len(prompt_str) > 1000 else ""),
                    "truncated_response": resp_str
                }
                serialized_data.append(record)

                tok_display = f"{comp_tok}" if comp_tok > 0 else f"{comp_tok} (usage omitted by backend)"
                txt_f.write(f"--- [TRUNCATED CALL #{t_idx} (LM Interaction #{call_idx+1})] Reason: {reason or 'length'} (Tokens: {tok_display}/{max_tok}) ---\n")
                txt_f.write(f"Token Usage: {usage_info}\n")
                txt_f.write(f"Prompt (start):\n{prompt_str[:500]}\n...\n")
                txt_f.write(f"Response (tail where truncation occurred):\n...{resp_str[-500:]}\n")
                txt_f.write("="*80 + "\n\n")

        with open(json_log_path, "w", encoding="utf-8") as json_f:
            json.dump(serialized_data, json_f, ensure_ascii=False, indent=2)

        print(f"[DSPy Inspection] Detailed truncated interaction logs written to:\n  • {json_log_path}\n  • {txt_log_path}", file=sys.stderr)
        # Display preview snippet of first truncated response
        first_call_idx, first_entry, first_reason, _, _ = truncated_calls[0]
        first_resp = str(first_entry.get("response") or first_entry.get("outputs") or "")
        print(f"[DSPy Inspection Preview] Sample truncated tail (Call #{first_call_idx+1}):\n... {first_resp[-200:]}\n", file=sys.stderr)
    else:
        print("[DSPy Inspection] All LM responses completed normally without truncation.", file=sys.stderr)


def run_dspy_optimization(
    model_name: str = DEFAULT_LLM_MODEL,
    vllm_url: str = DEFAULT_VLLM_URL,
    dataset_path: str = GROUND_TRUTH_DATASET_PATH,
    output_jsons_dir: Optional[str] = None,
    output_compiled_path: str = os.path.join(_PROJECT_ROOT, "prompts", "dspy_compiled_prompt.json"),
    teleprompter_type: str = "mipro",
    auto_preset: str = "medium",
    num_threads: int = 8,
    eval_runs_per_category: int = 1,
    max_tokens: int = DSPY_MAX_TOKENS,
    language: str = "vietnamese",
    prompt_temp: float = 0.35,
    prompt_rep_penalty: float = 1.15
):
    """
    Executes DSPy Teleprompter compilation loop to train and save optimized system instructions & exemplars.
    Types:
      - 'mipro': MIPROv2 (jointly optimizes System Prompt Text paragraphs AND Few-Shot Exemplars)
      - 'copro': COPRO (optimizes & rewrites System Prompt Text paragraphs)
      - 'bootstrap': BootstrapFewShot (optimizes Few-Shot Exemplars)
    """
    if not HAS_DSPY:
        print("[DSPy Error] dspy-ai package is not installed. Install via `pip install dspy-ai` to run training.", file=sys.stderr)
        return False

    effective_dataset_path = dataset_path or GROUND_TRUTH_DATASET_PATH
    print(f"[DSPy Optimization] Loading candidate dataset from {effective_dataset_path}...", file=sys.stderr)
    gt_data = load_candidate_ground_truth(effective_dataset_path)
    candidates = gt_data.get("candidates", [])

    rag_criteria = load_rag_criteria_by_category()
    effective_output_jsons = output_jsons_dir or os.path.join(_PROJECT_ROOT, "output_jsons")

    # Helper to build 5-Category DSPy Examples list for a given list of candidates
    def _build_candidate_examples(cands_list: List[Dict[str, Any]]) -> List[Any]:
        examples = []
        for cand in cands_list:
            fn = cand.get("filename", "")
            base_name = os.path.splitext(fn)[0] if fn else ""
            sanitized_name = base_name.replace(" ", "_")
            
            # Resilient candidate JSON lookup across potential naming variations
            candidate_paths = [
                os.path.join(effective_output_jsons, f"{base_name}.json"),
                os.path.join(effective_output_jsons, f"{sanitized_name}.json"),
                os.path.join(effective_output_jsons, f"{base_name}_extracted.json"),
                os.path.join(effective_output_jsons, f"{sanitized_name}_extracted.json"),
            ]
            r_data = {}
            for p in candidate_paths:
                if os.path.exists(p):
                    try:
                        with open(p, "r", encoding="utf-8") as f:
                            r_data = json.load(f)
                        if r_data:
                            break
                    except Exception:
                        pass

            # Generate examples across all 5 HR categories
            for cat_key, cat_name in CATEGORY_LABELS.items():
                job_crit = rag_criteria.get(cat_key, "Standard HR criteria for resume evaluation.")
                relevant_data = extract_relevant_resume_field(cat_key, r_data) if r_data else {}
                snippet_text = json.dumps(relevant_data, ensure_ascii=False) if relevant_data else f"Candidate File: {fn}. Email: {cand.get('email') or 'N/A'}"

                ex = dspy.Example(
                    category_name=cat_name,
                    job_criteria=job_crit,
                    resume_snippet=snippet_text,
                    email=cand.get("email"),
                    filename=cand.get("filename"),
                    target_category=cand.get("target_category"),
                    target_label=cand.get("target_label")
                ).with_inputs("category_name", "job_criteria", "resume_snippet")
                examples.append(ex)
        return examples

    # Partition by candidate first to ensure whole candidate dimension suites stay together
    train_cands = [cand for i, cand in enumerate(candidates) if i % 2 == 0]
    val_cands = [cand for i, cand in enumerate(candidates) if i % 2 != 0]

    train_set = _build_candidate_examples(train_cands)
    val_set = _build_candidate_examples(val_cands)
    total_examples = len(train_set) + len(val_set)

    print(f"[DSPy Optimization] Partitioned Candidates: {len(candidates)} total (Train: {len(train_cands)} cands / {len(train_set)} ex | Val: {len(val_cands)} cands / {len(val_set)} ex)", file=sys.stderr)

    # Configure DSPy LM backend matching production vLLM reasoning settings & multi-threaded concurrency
    dspy_stop_tokens = ["\n\n---", "--- END EXEMPLAR", "\n\nCategory Name:", "\n\nJob Criteria:", "\n\nResume Snippet:", "\n---"]
    print(f"[DSPy Optimization] Configuring LM backend '{model_name}' at {vllm_url} (task temp=0.1, prompt temp={prompt_temp}, max_tokens={max_tokens}, num_threads={num_threads})...", file=sys.stderr)
    try:
        task_model = dspy.LM(
            f"openai/{model_name}",
            api_base=vllm_url,
            api_key="EMPTY",
            max_tokens=max_tokens,
            temperature=0.2,
            top_p=0.95,
            stop=dspy_stop_tokens,
            extra_body={
                "repetition_penalty": prompt_rep_penalty,
                "chat_template_kwargs": {"enable_reasoning": False}
            }
        )
        prompt_model = dspy.LM(
            f"openai/{model_name}",
            api_base=vllm_url,
            api_key="EMPTY",
            max_tokens=max_tokens,
            temperature=prompt_temp,
            top_p=0.95,
            stop=dspy_stop_tokens,
            extra_body={
                "repetition_penalty": prompt_rep_penalty,
                "chat_template_kwargs": {"enable_reasoning": False}
            }
        )
    except Exception:
        # Fallback: vLLM endpoints that don't support chat_template_kwargs or extra_body
        try:
            task_model = dspy.LM(
                f"openai/{model_name}",
                api_base=vllm_url,
                api_key="EMPTY",
                max_tokens=max_tokens,
                temperature=0.1,
                top_p=0.95,
                stop=dspy_stop_tokens,
                extra_body={"repetition_penalty": prompt_rep_penalty}
            )
            prompt_model = dspy.LM(
                f"openai/{model_name}",
                api_base=vllm_url,
                api_key="EMPTY",
                max_tokens=max_tokens,
                temperature=prompt_temp,
                top_p=0.95,
                stop=dspy_stop_tokens,
                extra_body={"repetition_penalty": prompt_rep_penalty}
            )
        except Exception:
            task_model = dspy.LM(
                f"openai/{model_name}",
                api_base=vllm_url,
                api_key="EMPTY",
                max_tokens=max_tokens,
                temperature=0.1,
                top_p=0.95
            )
            prompt_model = dspy.LM(
                f"openai/{model_name}",
                api_base=vllm_url,
                api_key="EMPTY",
                max_tokens=max_tokens,
                temperature=prompt_temp,
                top_p=0.95
            )

    # Global DSPy LM settings — num_threads is controlled at teleprompter level, not here
    dspy.settings.configure(lm=task_model)

    student = DSPyResumeEvaluatorModule(eval_runs_per_category=eval_runs_per_category, language=language)
    tp_type = (teleprompter_type or "mipro").lower()
    eval_kwargs = {"num_threads": num_threads}

    try:
        # Multi-Threaded Teleprompter Selection
        if tp_type == "mipro":
            from dspy.teleprompt import MIPROv2
            print(f"[DSPy Optimization] Executing MIPROv2 Joint Optimization (Prompt Directives + Few-Shot Exemplars, preset='{auto_preset}', Step 3 eval_threads={num_threads}, eval_runs={eval_runs_per_category})...", file=sys.stderr)
            
            # Step 1 (Propose Instructions) & Step 2 (Propose Demos) execute standard library procedures.
            # Step 3 (Optuna Evaluation Search) executes concurrently using eval_kwargs / num_threads.
            mipro_init_kwargs = {
                "metric": dspy_metric_evaluator,
                "prompt_model": prompt_model,
                "task_model": task_model,
                "auto": auto_preset,
                "max_bootstrapped_demos": 3,
                "max_labeled_demos": 3,
            }
            try:
                teleprompter = MIPROv2(num_threads=num_threads, **mipro_init_kwargs)
            except TypeError:
                try:
                    teleprompter = MIPROv2(**mipro_init_kwargs)
                except Exception:
                    teleprompter = MIPROv2(metric=dspy_metric_evaluator, auto=auto_preset)

            def _compile_mipro(tp, s, train, val=None):
                compile_attempts = [
                    lambda: tp.compile(s, trainset=train, valset=val, eval_kwargs=eval_kwargs) if val else tp.compile(s, trainset=train, eval_kwargs=eval_kwargs),
                    lambda: tp.compile(s, trainset=train, valset=val, num_threads=num_threads) if val else tp.compile(s, trainset=train, num_threads=num_threads),
                    lambda: tp.compile(s, trainset=train, valset=val) if val else tp.compile(s, trainset=train),
                ]
                for attempt in compile_attempts:
                    try:
                        return attempt()
                    except TypeError:
                        continue
                return tp.compile(s, trainset=train)

            try:
                compiled_program = _compile_mipro(teleprompter, student, train_set, val_set)
            except Exception as compile_err:
                print(f"[DSPy Optimization Warning] MIPROv2 compilation with valset failed ({compile_err}). Retrying with trainset only...", file=sys.stderr)
                try:
                    compiled_program = _compile_mipro(teleprompter, student, train_set)
                except Exception as compile_err2:
                    print(f"[DSPy Optimization Error] MIPROv2 compilation failed ({compile_err2}). Falling back to standard BootstrapFewShot...", file=sys.stderr)
                    from dspy.teleprompt import BootstrapFewShot
                    bootstrapper = BootstrapFewShot(
                        metric=dspy_metric_evaluator,
                        max_bootstrapped_demos=3,
                        max_labeled_demos=3
                    )
                    compiled_program = bootstrapper.compile(student, trainset=train_set)

        elif tp_type == "copro":
            from dspy.teleprompt import COPRO
            print(f"[DSPy Optimization] Executing COPRO Prompt Directives Optimization (Step 3 eval_threads={num_threads})...", file=sys.stderr)
            try:
                teleprompter = COPRO(
                    metric=dspy_metric_evaluator,
                    breadth=5,
                    depth=3,
                    prompt_model=prompt_model
                )
            except Exception:
                teleprompter = COPRO(metric=dspy_metric_evaluator, breadth=5, depth=3)

            try:
                compiled_program = teleprompter.compile(
                    student,
                    trainset=train_set,
                    eval_kwargs=eval_kwargs
                )
            except (TypeError, Exception):
                compiled_program = teleprompter.compile(student, trainset=train_set)

        elif tp_type == "bootstrap":
            from dspy.teleprompt import BootstrapFewShot
            print(f"[DSPy Optimization] Executing standard BootstrapFewShot Exemplar Optimization...", file=sys.stderr)
            teleprompter = BootstrapFewShot(
                metric=dspy_metric_evaluator,
                max_bootstrapped_demos=3,
                max_labeled_demos=3
            )
            compiled_program = teleprompter.compile(student, trainset=train_set)

        else:
            raise ValueError(f"Unsupported teleprompter type: '{teleprompter_type}'")

    finally:
        inspect_and_save_dspy_history([task_model, prompt_model], max_tokens=max_tokens)

    # Save compiled prompt state
    os.makedirs(os.path.dirname(output_compiled_path), exist_ok=True)
    compiled_program.save(output_compiled_path)

    # Post-process JSON to ensure top-level system_instruction and demos are populated
    try:
        extracted_instruction = None
        eval_module = getattr(compiled_program, "evaluate_dimension", None)
        if eval_module:
            sig = getattr(eval_module, "signature", None) or getattr(getattr(eval_module, "predict", None), "signature", None)
            if sig and hasattr(sig, "instructions"):
                extracted_instruction = sig.instructions
            elif hasattr(eval_module, "instructions"):
                extracted_instruction = eval_module.instructions

        if os.path.exists(output_compiled_path):
            with open(output_compiled_path, "r", encoding="utf-8") as f:
                data = json.load(f)

            if isinstance(data, dict):
                # Search for predict sub-dictionary across common key names
                pred_data = data.get("evaluate_dimension.predict") or data.get("evaluate_dimension") or data.get("predict") or {}
                if not isinstance(pred_data, dict):
                    # Find any nested dictionary that has instructions or signature
                    for k, v in data.items():
                        if isinstance(v, dict) and ("instructions" in v or "signature" in v or "demos" in v):
                            pred_data = v
                            break

                if not extracted_instruction and isinstance(pred_data, dict):
                    extracted_instruction = pred_data.get("instructions")
                    if not extracted_instruction and isinstance(pred_data.get("signature"), dict):
                        extracted_instruction = pred_data["signature"].get("instructions")
                    if not extracted_instruction and isinstance(pred_data.get("extended_signature"), dict):
                        extracted_instruction = pred_data["extended_signature"].get("instructions")

                if extracted_instruction:
                    cleaned_inst = str(extracted_instruction).strip()
                    cleaned_inst = re.sub(r'^(#\s*\]\]\s*|\[\[\s*##\s*instructions\s*##\s*\]\]\s*)', '', cleaned_inst, flags=re.IGNORECASE).strip()
                    data["system_instruction"] = cleaned_inst

                # Extract and clean demos
                raw_demos = data.get("demos")
                if not raw_demos and isinstance(pred_data, dict):
                    raw_demos = pred_data.get("demos", [])
                if not raw_demos and eval_module:
                    raw_demos = getattr(eval_module, "demos", None) or getattr(getattr(eval_module, "predict", None), "demos", None)

                clean_demos = []
                if isinstance(raw_demos, list):
                    for d in raw_demos:
                        if hasattr(d, "toDict"):
                            clean_demos.append(d.toDict())
                        elif isinstance(d, dict):
                            clean_demos.append(d)
                        elif hasattr(d, "__dict__"):
                            clean_demos.append({k: v for k, v in d.__dict__.items() if not k.startswith("_")})

                data["demos"] = clean_demos

                with open(output_compiled_path, "w", encoding="utf-8") as f:
                    json.dump(data, f, ensure_ascii=False, indent=2)
    except Exception as e:
        print(f"[DSPy Warning] Post-processing compiled prompt file failed: {e}", file=sys.stderr)

    print(f"[DSPy Optimization] Compiled prompt instructions successfully saved to: {output_compiled_path}", file=sys.stderr)
    return True


if __name__ == "__main__":
    print("DSPy Evaluator Optimization Module Initialized.")
