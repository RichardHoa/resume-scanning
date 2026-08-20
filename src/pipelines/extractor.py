"""
Resume Extractor Pipeline — PDF text extraction (Docling) + LLM structured JSON generation
"""
import os
import sys

# Ensure repository root is in sys.path for 'src' package imports
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import html
import json
import re
import time
import unicodedata
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


def clean_markdown_and_symbols(text: str) -> str:
    """
    Decodes HTML entities, removes HTML tags (<br>, <b>, etc.), markdown formatting symbols,
    link URLs, and normalizes text for clean content comparison.
    """
    if not text:
        return ""
    # 1. Decode HTML entities (&amp; -> &, &nbsp; -> space, etc.)
    text = html.unescape(text)
    # 2. Unicode NFC normalization
    text = unicodedata.normalize("NFC", text)
    # 3. Replace HTML tags (e.g. <br>, <br/>, <b>, <span>, <div>, etc.) with spaces
    text = re.sub(r'<[^>]+>', ' ', text)
    # 4. Unwrap Markdown links [Text](URL) -> Text
    text = re.sub(r'\[([^\]]+)\]\([^\)]+\)', r'\1', text)
    # 5. Standardize dashes/hyphens
    text = re.sub(r'[–—−]', '-', text)
    # 6. Strip markdown formatting symbols (*, _, #, `, |, ~, >, bullet symbols like •)
    text = re.sub(r'[\*\_\#\`\|\~\>\•]', ' ', text)
    # 7. Convert to lowercase
    text = text.lower()
    # 8. Normalize all whitespace (newlines, tabs, multiple spaces) to a single space
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def to_words_only(text: str) -> str:
    """Converts text to lowercase NFC normalized alphanumeric words separated by single spaces."""
    if not text:
        return ""
    text = html.unescape(text)
    text = unicodedata.normalize("NFC", text)
    text = text.lower()
    text = re.sub(r'<[^>]+>', ' ', text)
    text = re.sub(r'[^\w\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def is_text_in_markdown(val: str, norm_markdown: str, words_markdown: str) -> bool:
    """Checks if extracted text string exists in source markdown content."""
    norm_val = clean_markdown_and_symbols(val)
    if not norm_val:
        return True

    # 1. Direct normalized substring match
    if norm_val in norm_markdown:
        return True

    # 2. Check using alphanumeric words-only representation (ignores markdown symbols, list numbers, colon spacing)
    words_val = to_words_only(val)
    if not words_val:
        return True

    if words_val in words_markdown:
        return True

    # 3. For multi-line text, check line-by-line / sentence-by-sentence
    lines = [line.strip() for line in val.split('\n') if line.strip()]
    if len(lines) > 1:
        all_lines_found = True
        for line in lines:
            line_words = to_words_only(line)
            if line_words and line_words not in words_markdown:
                all_lines_found = False
                break
        if all_lines_found:
            return True

    return False


def check_extracted_fields_in_markdown(extracted_dict: dict, markdown_content: str) -> list[str]:
    """
    Traverses extracted JSON and checks all text values against source markdown
    (excluding 'skills_and_specialties' and 'warning' fields).
    Returns a list of warning messages for missing extraction texts.
    """
    norm_markdown = clean_markdown_and_symbols(markdown_content)
    words_markdown = to_words_only(markdown_content)
    warnings = []

    def traverse(obj, path: str):
        if isinstance(obj, dict):
            for key, val in obj.items():
                if key in ("skills_and_specialties", "warning"):
                    continue
                current_path = f"{path}.{key}" if path else key
                traverse(val, current_path)
        elif isinstance(obj, list):
            for idx, item in enumerate(obj):
                current_path = f"{path}[{idx}]"
                traverse(item, current_path)
        elif isinstance(obj, str):
            val_str = obj.strip()
            if val_str and not is_text_in_markdown(val_str, norm_markdown, words_markdown):
                warnings.append(f"Extraction text at '{path}' ('{val_str}') not found in markdown")

    traverse(extracted_dict, "")
    return warnings


def validate_extracted_markdown(markdown_content: str) -> list[str]:
    """
    Validates extracted markdown text from PyMuPDF.
    Checks all failure conditions (scanned PDF, replacement/null bytes, invalid control characters, PUA font characters)
    and returns a list of warning messages for any detected issues instead of raising errors.
    """
    cleaned_text = markdown_content.strip()
    warnings = []

    # 1. Check for scanned PDF (no text or whitespace-only / no alphanumeric characters)
    if not cleaned_text or len(re.sub(r'\s+', '', cleaned_text)) == 0 or not any(c.isalnum() for c in cleaned_text):
        warnings.append("Scanned PDF: Document contains no extractable text.")

    # 2. Check for replacement characters (\ufffd) or null bytes (\x00)
    if '\ufffd' in markdown_content or '\x00' in markdown_content:
        warnings.append("Weird character: Document contains corrupted encoding or replacement characters (\\ufffd/null bytes).")

    # 3. Check for non-printable control characters (excluding standard whitespace \n, \r, \t, \f)
    invalid_control_chars = [c for c in markdown_content if ord(c) < 32 and c not in ('\n', '\r', '\t', '\f')]
    if invalid_control_chars:
        warnings.append(f"Weird character: Document contains invalid control characters ({len(invalid_control_chars)} found).")

    # 4. Check for Private Use Area (PUA) characters (unmappable custom fonts)
    pua_count = sum(
        1 for c in markdown_content
        if 0xE000 <= ord(c) <= 0xF8FF or 0xF0000 <= ord(c) <= 0xFFFFD or 0x100000 <= ord(c) <= 0x10FFFD
    )
    if pua_count > 0:
        warnings.append(f"Weird character: Document contains private use area / unmappable font characters ({pua_count} found).")

    for warn in warnings:
        print(f"Warning: [Markdown Validation] {warn}", file=sys.stderr)

    return warnings


def perform_ocr_fallback(pdf_path: str) -> tuple[str, list[str]]:
    """
    Attempts OCR extraction on a scanned PDF using available OCR engines (Docling, PyMuPDF OCR, RapidOCR).
    Supports Vietnamese and English text extraction and returns (ocr_text, ocr_warnings).
    """
    ocr_warnings = ["OCR Applied: Document contained no extractable text layer. OCR was used. Intensive HR Review Required."]
    ocr_text = ""

    # Attempt 1: Docling DocumentConverter
    try:
        from docling.document_converter import DocumentConverter
        converter = DocumentConverter()
        result = converter.convert(pdf_path)
        doc_md = result.document.export_to_markdown()
        if doc_md and any(c.isalnum() for c in doc_md):
            print(f"[OCR Fallback] Docling successfully extracted text from {pdf_path}", file=sys.stderr)
            return doc_md, ocr_warnings
    except Exception as e:
        print(f"[OCR Fallback] Docling OCR attempt skipped/failed: {e}", file=sys.stderr)

    # Attempt 2: PyMuPDF (fitz) page text / OCR / pixmap
    try:
        import fitz
        doc = fitz.open(pdf_path)
        page_texts = []
        for page in doc:
            try:
                tp = page.get_textpage_ocr(language="vie+eng")
                txt = tp.extractTEXT()
                if txt and any(c.isalnum() for c in txt):
                    page_texts.append(txt)
                    continue
            except Exception:
                pass

            txt = page.get_text()
            if txt and any(c.isalnum() for c in txt):
                page_texts.append(txt)

        doc.close()
        combined_text = "\n\n".join(page_texts).strip()
        if combined_text and any(c.isalnum() for c in combined_text):
            print(f"[OCR Fallback] PyMuPDF OCR successfully extracted text from {pdf_path}", file=sys.stderr)
            return combined_text, ocr_warnings
    except Exception as e:
        print(f"[OCR Fallback] PyMuPDF OCR attempt failed: {e}", file=sys.stderr)

    # Attempt 3: RapidOCR on rendered page images
    try:
        import fitz
        doc = fitz.open(pdf_path)
        rendered_texts = []

        rapid_ocr = None
        try:
            from rapidocr_onnxruntime import RapidOCR
            rapid_ocr = RapidOCR()
        except Exception:
            try:
                from rapidocr import RapidOCR
                rapid_ocr = RapidOCR()
            except Exception:
                pass

        for page in doc:
            pix = page.get_pixmap(dpi=150)
            img_bytes = pix.tobytes("png")
            if rapid_ocr:
                res, _ = rapid_ocr(img_bytes)
                if res:
                    page_str = "\n".join([line[1] for line in res if len(line) >= 2])
                    if page_str:
                        rendered_texts.append(page_str)

        doc.close()
        combined_rapid = "\n\n".join(rendered_texts).strip()
        if combined_rapid and any(c.isalnum() for c in combined_rapid):
            print(f"[OCR Fallback] RapidOCR successfully extracted text from {pdf_path}", file=sys.stderr)
            return combined_rapid, ocr_warnings
    except Exception as e:
        print(f"[OCR Fallback] RapidOCR image extraction attempt failed: {e}", file=sys.stderr)

    print(f"[OCR Fallback] All OCR engines exhausted for {pdf_path}", file=sys.stderr)
    return ocr_text, ocr_warnings


def extract_text_from_pdf(pdf_path: str, use_pymupdf: bool = True) -> tuple[str, list[str]]:
    """Converts a PDF file to Markdown representation using PyMuPDF4LLM with OCR fallback."""
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"File not found: {pdf_path}")

    # Attempt PyMuPDF4LLM parsing
    try:
        import pymupdf4llm
        print(f"Parsing PDF with PyMuPDF4LLM: {pdf_path}", file=sys.stderr)
        markdown_content = pymupdf4llm.to_markdown(pdf_path)
    except Exception as e:
        raise ValueError(f"PyMuPDF parsing error: PyMuPDF failed to parse PDF file ({e}).")

    # Validate extracted text
    warnings = validate_extracted_markdown(markdown_content)

    # Check if scanned PDF / no extractable text characters found
    is_scanned = any("Scanned PDF" in w for w in warnings) or not any(c.isalnum() for c in markdown_content)
    if is_scanned:
        print(f"[OCR Fallback Triggered] {pdf_path} contains no text layer. Running OCR fallback...", file=sys.stderr)
        ocr_text, ocr_warns = perform_ocr_fallback(pdf_path)
        if ocr_text:
            markdown_content = ocr_text
        warnings.extend(ocr_warns)

    try:
        os.makedirs(EXTRACTION_MARKDOWN_DIR, exist_ok=True)
        pdf_basename = os.path.splitext(os.path.basename(pdf_path))[0]
        md_output_path = os.path.join(EXTRACTION_MARKDOWN_DIR, f"{pdf_basename}.md")
        
        print(f"Saving markdown preview to: {md_output_path}", file=sys.stderr)
        with open(md_output_path, "w", encoding="utf-8") as f:
            f.write(markdown_content)
    except Exception as e:
        print(f"Warning: Could not save markdown to extraction_markdown: {e}", file=sys.stderr)

    return markdown_content, warnings


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


def detect_resume_language_status(text: str) -> str:
    """
    Detects language status of resume text.
    Returns: 'vietnamese', 'english', or 'bilingual'.
    """
    if not text:
        return "unknown"

    vn_diacritics_pattern = re.compile(r'[áàảãạăắằẳẵặâấầẩẫậđéèẻẽẹêếềểễệíìỉĩịóòỏõọôốồổỗộơớờởỡợúùủũụưứừửữựýỳỷỹỵ]', re.IGNORECASE)
    words = re.findall(r'\b[a-zA-Záàảãạăắằẳẵặâấầẩẫậđéèẻẽẹêếềểễệíìỉĩịóòỏõọôốồổỗộơớờởỡợúùủũụưứừửữựýỳỷỹỵ]+\b', text)
    total_words = len(words)
    if total_words == 0:
        return "unknown"

    vn_words_count = sum(1 for w in words if vn_diacritics_pattern.search(w))
    vn_ratio = vn_words_count / total_words

    if vn_words_count == 0:
        return "english"

    if vn_words_count >= 2:
        if vn_ratio >= 0.15:
            return "vietnamese"
        else:
            return "bilingual"

    return "english"


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

    def extract_single_pass(self, resume_text: str, pdf_path: str, language: str = "vietnamese", max_retries: int = 5) -> tuple[Optional[dict], str]:
        """Runs a single LLM extraction pass with retry logic for invalid JSON."""
        last_raw_result = ""

        for attempt in range(1, max_retries + 1):
            if self.mock:
                result = run_mock_extraction(resume_text, language=language)
            elif self.backend == "vllm":
                result = run_vllm_inference(resume_text, self.model_name, self.vllm_url, language=language)
            else:
                result = run_local_inference(resume_text, self.model, self.tokenizer_or_processor, language=language)

            last_raw_result = result
            parsed_dict = clean_and_parse_json(result)
            if parsed_dict is not None and isinstance(parsed_dict, dict) and len(parsed_dict) > 0:
                return parsed_dict, last_raw_result

            print(f"[Extract Retry] Attempt {attempt}/{max_retries} failed to produce valid JSON. Retrying LLM call...", file=sys.stderr)
            pdf_name = os.path.basename(pdf_path) if pdf_path else "resume"
            log_broken_json("Resume Extraction Prompt", result, "step_1_extraction", pdf_name, attempt=attempt, error_reason="Step 1 extraction JSON parse failed")

        return None, last_raw_result

    def extract(self, pdf_path: str, language: str = "vietnamese", max_retries: int = 5, consensus_runs: int = 5) -> str:
        pdf_warnings = []
        if self.mock:
            resume_text = "Mock resume content converted from PDF."
        else:
            try:
                resume_text, pdf_warnings = extract_text_from_pdf(pdf_path)
            except Exception as e:
                error_msg = str(e)
                print(f"[Extractor Rejected] {pdf_path}: {error_msg}", file=sys.stderr)
                return json.dumps({"error": error_msg}, ensure_ascii=False, indent=2)

        target_lang_normalized = "english" if language.lower() in ("english", "en") else "vietnamese"
        if not self.mock:
            lang_status = detect_resume_language_status(resume_text)
            print(f"[Extractor Language] Detected resume language status: '{lang_status}' (Target tag language: '{target_lang_normalized}')", file=sys.stderr)

        candidates = []
        last_raw_result = ""

        print(f"[Medoid Consensus] Gathering {consensus_runs} extraction candidates (target language: {target_lang_normalized})...", file=sys.stderr)
        for run_idx in range(1, consensus_runs + 1):
            parsed_dict, raw_result = self.extract_single_pass(resume_text, pdf_path, language=language, max_retries=max_retries)
            if raw_result:
                last_raw_result = raw_result
            if parsed_dict is not None:
                candidates.append(parsed_dict)

        final_dict = None
        consensus_score = 0.0
        if candidates:
            medoid_dict, consensus_score = select_medoid_json(candidates)
            print(f"[Medoid Consensus] Successfully gathered {len(candidates)}/{consensus_runs} valid candidates. "
                  f"Selected Medoid candidate with consensus score: {consensus_score:.4f}", file=sys.stderr)
            final_dict = medoid_dict
        else:
            # Fallback if all consensus runs and retries failed to produce clean JSON
            print(f"Warning: All {consensus_runs} extraction consensus runs failed to produce clean JSON. Attempting auto-repair...", file=sys.stderr)
            clean_result = extract_json_substring(last_raw_result)
            repaired = repair_truncated_json(clean_result)
            try:
                final_dict = json.loads(repaired)
            except json.JSONDecodeError:
                print("  Auto-repair failed. Returning raw substring.", file=sys.stderr)
                return clean_result

        if isinstance(final_dict, dict):
            if "error" in final_dict:
                return json.dumps(final_dict, ensure_ascii=False, indent=2)
            warnings = check_extracted_fields_in_markdown(final_dict, resume_text)
            if pdf_warnings:
                warnings.extend(pdf_warnings)
            if not candidates or consensus_score < 0.8:
                score_str = f"{consensus_score:.4f}" if candidates else "0.0000 (No candidates matched)"
                warnings.insert(0, f"Low consensus score: Extraction consensus score ({score_str}) is below threshold 0.8.")
            final_dict["warning"] = warnings

            ocr_triggered = any("OCR Applied" in w for w in pdf_warnings)
            if ocr_triggered:
                final_dict["ocr_applied"] = True
                final_dict["intensive_hr_review_required"] = True

            return json.dumps(final_dict, ensure_ascii=False, indent=2)

        return clean_result


