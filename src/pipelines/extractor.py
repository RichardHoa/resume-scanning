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
from src.core.config import DEFAULT_VLLM_URL, ROOT_DIR
from src.core.logger import log_broken_json
from src.core.json_utils import extract_json_substring, repair_truncated_json, clean_and_parse_json
from src.providers.llm_backend import (
    load_local_model,
    run_local_inference,
    run_local_inference_nuextract,
    run_vllm_inference,
    run_vllm_inference_nuextract,
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
        pdf_basename = os.path.splitext(os.path.basename(pdf_path))[0]
        md_output_path = os.path.join(ROOT_DIR, f"{pdf_basename}.md")
        
        print(f"Saving markdown preview to: {md_output_path}", file=sys.stderr)
        with open(md_output_path, "w", encoding="utf-8") as f:
            f.write(markdown_content)
    except Exception as e:
        print(f"Warning: Could not save markdown to root: {e}", file=sys.stderr)

    return markdown_content


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

    def extract(self, pdf_path: str, max_retries: int = 5) -> str:
        if self.mock:
            resume_text = "Mock resume content converted from PDF."
        else:
            resume_text = extract_text_from_pdf(pdf_path)

        is_nuextract = self.model_name and "nuextract" in self.model_name.lower()
        last_raw_result = ""

        for attempt in range(1, max_retries + 1):
            if self.mock:
                result = run_mock_extraction(resume_text)
            elif self.backend == "vllm":
                if is_nuextract:
                    result = run_vllm_inference_nuextract(resume_text, self.model_name, self.vllm_url)
                else:
                    result = run_vllm_inference(resume_text, self.model_name, self.vllm_url)
            else:
                if is_nuextract:
                    result = run_local_inference_nuextract(resume_text, self.model, self.tokenizer_or_processor)
                else:
                    result = run_local_inference(resume_text, self.model, self.tokenizer_or_processor)

            last_raw_result = result
            parsed_dict = clean_and_parse_json(result)
            if parsed_dict is not None and isinstance(parsed_dict, dict) and len(parsed_dict) > 0:
                return json.dumps(parsed_dict, ensure_ascii=False, indent=2)

            print(f"[Extract Retry] Attempt {attempt}/{max_retries} failed to produce valid JSON. Retrying LLM call...", file=sys.stderr)
            pdf_name = os.path.basename(pdf_path) if pdf_path else "resume"
            log_broken_json("Resume Extraction Prompt", result, "step_1_extraction", pdf_name, attempt=attempt, error_reason="Step 1 extraction JSON parse failed")

        # Fallback if all retries failed
        print(f"Warning: All {max_retries} LLM extraction attempts failed to produce clean JSON. Attempting auto-repair...", file=sys.stderr)
        clean_result = extract_json_substring(last_raw_result)
        repaired = repair_truncated_json(clean_result)
        try:
            parsed_json = json.loads(repaired)
            return json.dumps(parsed_json, ensure_ascii=False, indent=2)
        except json.JSONDecodeError:
            print("  Auto-repair failed. Returning raw substring.", file=sys.stderr)
            return clean_result
