"""
Resume Extractor Pipeline — PDF text extraction (Docling) + LLM structured JSON generation
"""
import os
import sys

# Ensure repository root is in sys.path for 'src' package imports
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import json
import time
from typing import Optional
from src.core.config import DEFAULT_VLLM_URL, ROOT_DIR, EXTRACTION_MARKDOWN_DIR
from src.core.logger import log_broken_json
from src.core.json_utils import extract_json_substring, repair_truncated_json, clean_and_parse_json
from src.providers.llm_backend import (
    load_local_model,
    run_local_inference,
    run_vllm_inference,
    run_mock_extraction,
    vllm_discover_model,
)


def extract_text_from_pdf(pdf_path: str, use_pymupdf: bool = True) -> str:
    """Converts a PDF file to Markdown layout-aware representation using PyMuPDF4LLM (primary) or Docling (fallback)."""
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"File not found: {pdf_path}")

    markdown_content = ""

    # Attempt PyMuPDF4LLM first (fast, layout-aware horizontal line preservation)
    if use_pymupdf:
        try:
            import pymupdf4llm
            print(f"Parsing PDF with PyMuPDF4LLM: {pdf_path}", file=sys.stderr)
            markdown_content = pymupdf4llm.to_markdown(pdf_path)
        except ImportError:
            print("Notice: pymupdf4llm is not installed. Falling back to Docling...", file=sys.stderr)
        except Exception as e:
            print(f"Warning: PyMuPDF4LLM parsing failed ({e}). Falling back to Docling...", file=sys.stderr)

    # Fallback to Docling if PyMuPDF4LLM was disabled, failed, or produced empty output
    if not markdown_content.strip():
        from docling.document_converter import DocumentConverter
        print(f"Parsing PDF with Docling: {pdf_path}", file=sys.stderr)
        converter = DocumentConverter()
        result = converter.convert(pdf_path)
        markdown_content = result.document.export_to_markdown()

    try:
        os.makedirs(EXTRACTION_MARKDOWN_DIR, exist_ok=True)
        pdf_basename = os.path.splitext(os.path.basename(pdf_path))[0]
        md_output_path = os.path.join(EXTRACTION_MARKDOWN_DIR, f"{pdf_basename}.md")
        
        print(f"Saving markdown preview to: {md_output_path}", file=sys.stderr)
        with open(md_output_path, "w", encoding="utf-8") as f:
            f.write(markdown_content)
    except Exception as e:
        print(f"Warning: Could not save markdown to extraction_markdown: {e}", file=sys.stderr)

    return markdown_content


import difflib


def compute_json_similarity(dict_a: dict, dict_b: dict) -> float:
    """Computes normalized sequence similarity between two JSON dictionaries."""
    str_a = json.dumps(dict_a, sort_keys=True, ensure_ascii=False)
    str_b = json.dumps(dict_b, sort_keys=True, ensure_ascii=False)
    return difflib.SequenceMatcher(None, str_a, str_b).ratio()


def select_medoid_json(candidates: list[dict]) -> tuple[dict, float]:
    """
    Selects the Medoid candidate dictionary (the candidate with highest average similarity to all others).
    Returns a tuple of (medoid_dict, average_consensus_score).
    """
    if not candidates:
        raise ValueError("Candidates list cannot be empty for Medoid selection.")
    if len(candidates) == 1:
        return candidates[0], 1.0

    best_medoid = candidates[0]
    highest_avg_score = -1.0

    for i, cand_i in enumerate(candidates):
        sim_sum = sum(
            compute_json_similarity(cand_i, cand_j)
            for j, cand_j in enumerate(candidates) if i != j
        )
        avg_sim = sim_sum / (len(candidates) - 1)
        if avg_sim > highest_avg_score:
            highest_avg_score = avg_sim
            best_medoid = cand_i

    return best_medoid, highest_avg_score


class ResumeExtractor:
    """Unified interface for resume extraction across both inference backends."""

    def __init__(self, model_name: Optional[str] = None, mock: bool = False,
                 backend: str = "transformers", vllm_url: str = DEFAULT_VLLM_URL):
        self.model_name = model_name
        self.mock = mock
        self.backend = backend
        self.vllm_url = vllm_url
        self.model = None
        self.tokenizer_or_processor = None

    def load_model(self):
        if not self.mock and self.backend == "transformers":
            self.model, self.tokenizer_or_processor = load_local_model(self.model_name or "Qwen/Qwen3.5-9B")
        elif self.backend == "vllm" and not self.model_name:
            self.model_name = vllm_discover_model(self.vllm_url)

    def extract_single_pass(self, resume_text: str, pdf_path: str, max_retries: int = 5) -> tuple[Optional[dict], str]:
        """Runs a single LLM extraction pass with retry logic for invalid JSON."""
        last_raw_result = ""

        for attempt in range(1, max_retries + 1):
            if self.mock:
                result = run_mock_extraction(resume_text)
            elif self.backend == "vllm":
                result = run_vllm_inference(resume_text, self.model_name, self.vllm_url)
            else:
                result = run_local_inference(resume_text, self.model, self.tokenizer_or_processor)

            last_raw_result = result
            parsed_dict = clean_and_parse_json(result)
            if parsed_dict is not None and isinstance(parsed_dict, dict) and len(parsed_dict) > 0:
                return parsed_dict, last_raw_result

            print(f"[Extract Retry] Attempt {attempt}/{max_retries} failed to produce valid JSON. Retrying LLM call...", file=sys.stderr)
            pdf_name = os.path.basename(pdf_path) if pdf_path else "resume"
            log_broken_json("Resume Extraction Prompt", result, "step_1_extraction", pdf_name, attempt=attempt, error_reason="Step 1 extraction JSON parse failed")

        return None, last_raw_result

    def extract(self, pdf_path: str, max_retries: int = 5, consensus_runs: int = 5) -> str:
        if self.mock:
            resume_text = "Mock resume content converted from PDF."
        else:
            resume_text = extract_text_from_pdf(pdf_path)

        candidates = []
        last_raw_result = ""

        print(f"[Medoid Consensus] Gathering {consensus_runs} extraction candidates...", file=sys.stderr)
        for run_idx in range(1, consensus_runs + 1):
            parsed_dict, raw_result = self.extract_single_pass(resume_text, pdf_path, max_retries=max_retries)
            if raw_result:
                last_raw_result = raw_result
            if parsed_dict is not None:
                candidates.append(parsed_dict)

        if candidates:
            medoid_dict, consensus_score = select_medoid_json(candidates)
            print(f"[Medoid Consensus] Successfully gathered {len(candidates)}/{consensus_runs} valid candidates. "
                  f"Selected Medoid candidate with consensus score: {consensus_score:.4f}", file=sys.stderr)
            return json.dumps(medoid_dict, ensure_ascii=False, indent=2)

        # Fallback if all consensus runs and retries failed to produce clean JSON
        print(f"Warning: All {consensus_runs} extraction consensus runs failed to produce clean JSON. Attempting auto-repair...", file=sys.stderr)
        clean_result = extract_json_substring(last_raw_result)
        repaired = repair_truncated_json(clean_result)
        try:
            parsed_json = json.loads(repaired)
            return json.dumps(parsed_json, ensure_ascii=False, indent=2)
        except json.JSONDecodeError:
            print("  Auto-repair failed. Returning raw substring.", file=sys.stderr)
            return clean_result

