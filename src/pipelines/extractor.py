"""
Resume Extractor Pipeline — PDF text extraction (Docling, PyMuPDF4LLM fallback) + LLM structured JSON generation
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
import threading
import unicodedata
from typing import Optional
from src.core.config import DEFAULT_VLLM_URL, EXTRACTION_MARKDOWN_DIR
from src.core.logger import log_broken_json
from src.core.json_utils import extract_json_substring, repair_truncated_json, clean_and_parse_json
from src.providers.llm_backend import run_vllm_inference, run_mock_extraction
from src.providers import vllm_client
from src.pipelines.evaluator_utils import SCANNED_RESUME_KEY


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
    (excluding the 'warning' field).
    Returns a list of warning messages for missing extraction texts.
    """
    norm_markdown = clean_markdown_and_symbols(markdown_content)
    words_markdown = to_words_only(markdown_content)
    warnings = []

    def traverse(obj, path: str):
        if isinstance(obj, dict):
            for key, val in obj.items():
                if key == "warning":
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
    Validates the parsed resume Markdown.
    Checks for replacement/null bytes, invalid control characters and PUA font characters, and returns a list of
    warning messages for any detected issues instead of raising errors.
    """
    warnings = []

    # 1. Check for replacement characters (\ufffd) or null bytes (\x00)
    if '\ufffd' in markdown_content or '\x00' in markdown_content:
        warnings.append("Weird character: Document contains corrupted encoding or replacement characters (\\ufffd/null bytes).")

    # 2. Check for non-printable control characters (excluding standard whitespace \n, \r, \t, \f)
    invalid_control_chars = [c for c in markdown_content if ord(c) < 32 and c not in ('\n', '\r', '\t', '\f')]
    if invalid_control_chars:
        warnings.append(f"Weird character: Document contains invalid control characters ({len(invalid_control_chars)} found).")

    # 3. Check for Private Use Area (PUA) characters (unmappable custom fonts)
    pua_count = sum(
        1 for c in markdown_content
        if 0xE000 <= ord(c) <= 0xF8FF or 0xF0000 <= ord(c) <= 0xFFFFD or 0x100000 <= ord(c) <= 0x10FFFD
    )
    if pua_count > 0:
        warnings.append(f"Weird character: Document contains private use area / unmappable font characters ({pua_count} found).")

    for warn in warnings:
        print(f"Warning: [Markdown Validation] {warn}", file=sys.stderr)

    return warnings


# A Scanned Resume has no page with text; the system never reads text from images, since resumes can be in any
# language. HR sees this message and asks the candidate for a PDF with selectable text.
SCANNED_RESUME_MESSAGE = (
    "CV là bản scan (không có lớp văn bản), hệ thống không đọc được. "
    "Vui lòng yêu cầu ứng viên gửi bản PDF có thể chọn chữ."
)

# Past this, Docling is treated as stuck and PyMuPDF4LLM parses the resume instead
DOCLING_TIMEOUT_SECONDS = 120


class ScannedResumeError(ValueError):
    """A resume PDF in which no page has text: rejected before any parser runs."""


def _has_text(text: str) -> bool:
    return any(c.isalnum() for c in text or "")


def find_textless_pages(pdf_path: str) -> tuple[list[int], int]:
    """The 1-based numbers of the pages with no text layer, and the page count, from a cheap PyMuPDF read."""
    import pymupdf
    with pymupdf.open(pdf_path) as doc:
        textless = [page.number + 1 for page in doc if not _has_text(page.get_text())]
        return textless, doc.page_count


_docling_converter = None
_docling_lock = threading.Lock()


def _parse_with_docling(pdf_path: str) -> str:
    """
    Docling Markdown, built by one shared converter (its models load once). OCR is off: a Scanned Resume never
    reaches here. Raises when Docling fails or runs past DOCLING_TIMEOUT_SECONDS (which Docling reports as a
    partial success, not an error).
    """
    global _docling_converter
    from docling.datamodel.base_models import ConversionStatus, InputFormat
    from docling.datamodel.pipeline_options import PdfPipelineOptions, TableFormerMode
    from docling.document_converter import DocumentConverter, PdfFormatOption

    # One converter, used by one thread at a time: batch extraction runs several workers
    with _docling_lock:
        if _docling_converter is None:
            options = PdfPipelineOptions()
            options.do_ocr = False
            options.do_table_structure = True
            options.table_structure_options.mode = TableFormerMode.ACCURATE
            options.document_timeout = DOCLING_TIMEOUT_SECONDS
            _docling_converter = DocumentConverter(
                format_options={InputFormat.PDF: PdfFormatOption(pipeline_options=options)}
            )
        result = _docling_converter.convert(pdf_path)

    if result.status != ConversionStatus.SUCCESS:
        raise RuntimeError(f"Docling conversion ended with status {result.status} (timed out or partly failed)")
    return result.document.export_to_markdown()


def extract_text_from_pdf(pdf_path: str) -> tuple[str, list[str]]:
    """
    Converts a PDF resume to Markdown with Docling, falling back to PyMuPDF4LLM when Docling fails, times out or
    finds no text. Raises ScannedResumeError for a Scanned Resume (no page has text).
    """
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"File not found: {pdf_path}")

    textless_pages, page_count = find_textless_pages(pdf_path)
    if len(textless_pages) == page_count:
        raise ScannedResumeError(SCANNED_RESUME_MESSAGE)

    parse_warnings = []
    markdown_content = ""
    try:
        print(f"Parsing PDF with Docling: {pdf_path}", file=sys.stderr)
        markdown_content = _parse_with_docling(pdf_path)
        if not _has_text(markdown_content):
            raise RuntimeError("Docling returned no text")
    except Exception as e:
        print(f"Warning: Docling failed on {pdf_path} ({e}). Falling back to PyMuPDF4LLM...", file=sys.stderr)
        parse_warnings.append(f"Parser fallback: Docling failed ({e}); the resume was parsed with PyMuPDF4LLM.")
        try:
            import pymupdf4llm
            markdown_content = pymupdf4llm.to_markdown(pdf_path)
        except Exception as fallback_err:
            raise ValueError(f"PDF parsing error: Docling and PyMuPDF4LLM both failed ({fallback_err}).")
        if not _has_text(markdown_content):
            raise ValueError("PDF parsing error: Docling and PyMuPDF4LLM both returned no text.")

    # Some pages without text (e.g. a scanned certificate attached): the text pages are read, HR checks the rest
    if textless_pages:
        pages = ", ".join(str(n) for n in textless_pages)
        parse_warnings.append(f"Pages without text: page(s) {pages} have no text layer and were not read; HR should check them by hand.")

    warnings = validate_extracted_markdown(markdown_content) + parse_warnings

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


class ResumeExtractor:
    """Extracts a resume PDF into the schema JSON through a vLLM server (or the mock)."""

    def __init__(self, model_name: Optional[str] = None, mock: bool = False, vllm_url: str = DEFAULT_VLLM_URL):
        self.model_name = model_name
        self.mock = mock
        self.vllm_url = vllm_url

    def load_model(self):
        if not self.mock and not self.model_name:
            self.model_name = vllm_client.discover_model(self.vllm_url)

    def extract_single_pass(self, resume_text: str, pdf_path: str, language: str = "vietnamese", max_retries: int = 5) -> tuple[Optional[dict], str]:
        """Runs a single LLM extraction pass with retry logic for invalid JSON."""
        last_raw_result = ""

        for attempt in range(1, max_retries + 1):
            if self.mock:
                result = run_mock_extraction(resume_text, language=language)
            else:
                result = run_vllm_inference(resume_text, self.model_name, self.vllm_url, language=language)

            last_raw_result = result
            parsed_dict = clean_and_parse_json(result)
            if parsed_dict is not None and isinstance(parsed_dict, dict) and len(parsed_dict) > 0:
                return parsed_dict, last_raw_result

            print(f"[Extract Retry] Attempt {attempt}/{max_retries} failed to produce valid JSON. Retrying LLM call...", file=sys.stderr)
            pdf_name = os.path.basename(pdf_path) if pdf_path else "resume"
            log_broken_json("Resume Extraction Prompt", result, "step_1_extraction", pdf_name, attempt=attempt, error_reason="Step 1 extraction JSON parse failed")

        return None, last_raw_result

    def extract(self, pdf_path: str, language: str = "vietnamese", max_retries: int = 5) -> str:
        pdf_warnings = []
        if self.mock:
            resume_text = "Mock resume content converted from PDF."
        else:
            try:
                resume_text, pdf_warnings = extract_text_from_pdf(pdf_path)
            except ScannedResumeError as e:
                print(f"[Extractor Rejected] {pdf_path}: Scanned Resume (no page has text)", file=sys.stderr)
                return json.dumps({"error": str(e), SCANNED_RESUME_KEY: True}, ensure_ascii=False, indent=2)
            except Exception as e:
                error_msg = str(e)
                print(f"[Extractor Rejected] {pdf_path}: {error_msg}", file=sys.stderr)
                return json.dumps({"error": error_msg}, ensure_ascii=False, indent=2)

        final_dict, raw_result = self.extract_single_pass(resume_text, pdf_path, language=language, max_retries=max_retries)
        if final_dict is None:
            # Fallback if every retry failed to produce clean JSON
            print("Warning: Extraction failed to produce clean JSON. Attempting auto-repair...", file=sys.stderr)
            clean_result = extract_json_substring(raw_result)
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
            final_dict["warning"] = warnings

            return json.dumps(final_dict, ensure_ascii=False, indent=2)

        return clean_result
