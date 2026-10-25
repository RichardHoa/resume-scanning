"""
Resume Extractor Pipeline — PDF text extraction (PyMuPDF4LLM) + LLM structured JSON generation
"""
import os
import sys

# Ensure repository root is in sys.path for 'src' package imports
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import base64
import html
import json
import re
import unicodedata
from typing import Optional
from src.core.config import DEFAULT_VLLM_URL, EXTRACTION_MARKDOWN_DIR, COMBINED_IMAGE_DPI, COMBINED_MAX_PAGES
from src.core.logger import log_llm_call, log_broken_json, EXTRACTION_LOG_CATEGORY
from src.core.json_utils import extract_json_substring, repair_truncated_json, clean_and_parse_json
from src.providers.llm_backend import (
    PageImage, extraction_messages, prompt_log_text, run_vllm_inference, run_mock_extraction
)
from src.providers import vllm_client
from src.pipelines.evaluator_utils import SCANNED_RESUME_KEY


# Every Fidelity Warning starts with this; the other entries in an extraction's "warning" list are PDF Notes, or the
# Repaired Extraction warning below
FIDELITY_WARNING_PREFIX = "Extraction text at "
# Added to a Repaired Extraction: every retry gave broken JSON and the last answer was patched, so fields may be missing
REPAIRED_EXTRACTION_WARNING = (
    "Repaired Extraction: every retry gave broken JSON and the model's last answer was patched; "
    "fields after the cut may be missing."
)

# Fidelity check thresholds, chosen on the 2026-10-25 consistency runs (see docs/research/extractor-consistency-2026-10-25.md).
# A segment shorter than this (in tokens) is only accepted if the whole value also passes the ordered window
FIDELITY_SHORT_SEGMENT_TOKENS = 3
# The ordered window spans value length + max(value length, this) markdown tokens
FIDELITY_WINDOW_BASE_SPREAD = 10
# Values shorter than this (in tokens) never pass by the ordered window alone
FIDELITY_WINDOW_MIN_TOKENS = 5
# A language name the model infers from a certificate (ADR 0003) is accepted when the markdown names one of these
FIDELITY_LANGUAGE_CERTIFICATES = {
    "english": ("TOEIC", "IELTS", "TOEFL", "Cambridge", "APTIS", "VSTEP"),
    "japanese": ("JLPT", "日本語能力試験"),
    "chinese": ("HSK", "TOCFL"),
    "korean": ("TOPIK",),
}

# A real HTML tag: '<', optional '/', a tag name starting with a letter, bounded attributes, '>'. A bare '<' or '>'
# ("< 50 employees", ">90%") is ordinary punctuation
_HTML_TAG = re.compile(r'</?[A-Za-z][A-Za-z0-9-]*(?:\s[^<>]{0,200})?\s*/?>')
_MARKDOWN_LINK = re.compile(r'\[([^\]]+)\]\([^\)]+\)')
_NON_WORD = re.compile(r'[\W_]+')
# Kana, CJK ideographs and Hangul: each character is its own token, since these scripts don't separate words by spaces
_CJK_CHAR = re.compile(
    r'([\u1100-\u11ff\u3040-\u30ff\u3130-\u318f\u31f0-\u31ff\u3400-\u4dbf\u4e00-\u9fff\uac00-\ud7af\uf900-\ufaff'
    r'\U00020000-\U0002fa1f])'
)
# Where a value splits into segments: line breaks, bullet markers, ' / ' and spaced range dashes
_SEGMENT_SPLIT = re.compile(r'\n|\s/\s|\s[-–—]\s|(?:^|(?<=\s))[-+•]\s')
_LANGUAGE_FIELD_PATH = re.compile(r'^languages\[\d+\]\.language$')


def fidelity_tokens(text: str) -> list[str]:
    """Normalises text for the fidelity check and splits it into tokens; values and markdown go through the same steps."""
    if not text:
        return []
    text = html.unescape(text)
    text = unicodedata.normalize("NFKC", text)
    text = _HTML_TAG.sub(' ', text)
    text = _MARKDOWN_LINK.sub(r'\1', text)
    text = _NON_WORD.sub(' ', text.lower())
    text = _CJK_CHAR.sub(r' \1 ', text)
    return text.split()


class _MarkdownIndex:
    """The resume markdown, tokenised once per extraction, with the lookups the matching rules need."""

    def __init__(self, markdown: str):
        self.tokens = fidelity_tokens(markdown)
        self.joined = f" {' '.join(self.tokens)} "
        self.spaceless = "".join(self.tokens)
        self.boundaries = {0}
        self.positions: dict[str, list[int]] = {}
        offset = 0
        for i, token in enumerate(self.tokens):
            offset += len(token)
            self.boundaries.add(offset)
            self.positions.setdefault(token, []).append(i)

    def contiguous(self, tokens: list[str]) -> bool:
        return f" {' '.join(tokens)} " in self.joined

    def spaceless_match(self, tokens: list[str]) -> bool:
        """The tokens joined without spaces equal a run of whole markdown tokens joined without spaces."""
        target = "".join(tokens)
        start = self.spaceless.find(target)
        while start != -1:
            if start in self.boundaries and start + len(target) in self.boundaries:
                return True
            start = self.spaceless.find(target, start + 1)
        return False

    def ordered_window(self, tokens: list[str]) -> bool:
        """All tokens appear in order within a window counted from a match of the first token."""
        span = len(tokens) + max(len(tokens), FIDELITY_WINDOW_BASE_SPREAD)
        for first in self.positions.get(tokens[0], []):
            end = min(first + span, len(self.tokens))
            i = first + 1
            for token in tokens[1:]:
                while i < end and self.tokens[i] != token:
                    i += 1
                if i >= end:
                    break
                i += 1
            else:
                return True
        return False


def _segments_match(val: str, markdown: _MarkdownIndex, tokens: list[str]) -> bool:
    segments = [seg for seg in (fidelity_tokens(part) for part in _SEGMENT_SPLIT.split(val)) if seg]
    if len(segments) < 2:
        return False
    if not all(markdown.contiguous(seg) or markdown.spaceless_match(seg) for seg in segments):
        return False
    # Short pieces (a year, a one-word title) are found almost anywhere: they must also sit near each other
    if any(len(seg) < FIDELITY_SHORT_SEGMENT_TOKENS for seg in segments):
        return markdown.ordered_window(tokens)
    return True


def _language_from_certificate(path: str, tokens: list[str], markdown: _MarkdownIndex) -> bool:
    if not _LANGUAGE_FIELD_PATH.match(path):
        return False
    certificates = FIDELITY_LANGUAGE_CERTIFICATES.get(" ".join(tokens), ())
    return any(markdown.contiguous(fidelity_tokens(cert)) for cert in certificates)


def is_text_in_markdown(val: str, path: str, markdown: _MarkdownIndex) -> bool:
    """Checks whether an extracted value at a field path comes from the resume's text; any one rule accepts it."""
    tokens = fidelity_tokens(val)
    if not tokens:
        return True
    return (
        markdown.contiguous(tokens)
        or markdown.spaceless_match(tokens)
        or _segments_match(val, markdown, tokens)
        or (len(tokens) >= FIDELITY_WINDOW_MIN_TOKENS and markdown.ordered_window(tokens))
        or _language_from_certificate(path, tokens, markdown)
    )


def check_extracted_fields_in_markdown(extracted_dict: dict, markdown_content: str) -> list[str]:
    """
    Traverses extracted JSON and checks all text values against source markdown
    (excluding the 'warning' field).
    Returns a list of warning messages for missing extraction texts.
    """
    markdown = _MarkdownIndex(markdown_content)
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
            if val_str and not is_text_in_markdown(val_str, path, markdown):
                warnings.append(f"{FIDELITY_WARNING_PREFIX}'{path}' ('{val_str}') not found in markdown")

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


def render_page_images(pdf_path: str) -> tuple[list[PageImage], list[int]]:
    """
    Renders a PDF's text pages as JPEG page images for Combined Extraction, at most COMBINED_MAX_PAGES in page order.
    Returns the images and the 1-based numbers of the text pages left out past that cap. A page without text is
    never shown: nothing could check what the model read from it (ADR 0007).
    """
    import pymupdf
    images, left_out = [], []
    with pymupdf.open(pdf_path) as doc:
        for page in doc:
            if not _has_text(page.get_text()):
                continue
            if len(images) >= COMBINED_MAX_PAGES:
                left_out.append(page.number + 1)
                continue
            jpeg = page.get_pixmap(dpi=COMBINED_IMAGE_DPI).tobytes("jpeg")
            images.append(PageImage(page.number + 1, "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("ascii")))
    return images, left_out


def extract_text_from_pdf(pdf_path: str) -> tuple[str, list[str]]:
    """Converts a PDF resume to Markdown with PyMuPDF4LLM. Raises ScannedResumeError for a Scanned Resume (no page has text)."""
    if not os.path.exists(pdf_path):
        raise FileNotFoundError(f"File not found: {pdf_path}")

    textless_pages, page_count = find_textless_pages(pdf_path)
    if len(textless_pages) == page_count:
        raise ScannedResumeError(SCANNED_RESUME_MESSAGE)

    # PyMuPDF4LLM only: Docling was tried and could not detect tables at all, do not switch back (ADR 0008)
    try:
        import pymupdf4llm
        print(f"Parsing PDF with PyMuPDF4LLM: {pdf_path}", file=sys.stderr)
        markdown_content = pymupdf4llm.to_markdown(pdf_path)
    except Exception as e:
        raise ValueError(f"PyMuPDF parsing error: PyMuPDF failed to parse PDF file ({e}).")
    if not _has_text(markdown_content):
        raise ValueError("PDF parsing error: PyMuPDF4LLM returned no text.")

    parse_warnings = []

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
    """
    Extracts a resume PDF into the schema JSON through a vLLM server (or the mock), always with Combined Extraction:
    the model also sees the page images, which needs a vision model served with images allowed.
    """

    def __init__(self, model_name: Optional[str] = None, mock: bool = False, vllm_url: str = DEFAULT_VLLM_URL):
        self.model_name = model_name
        self.mock = mock
        self.vllm_url = vllm_url

    def load_model(self):
        if not self.mock and not self.model_name:
            self.model_name = vllm_client.discover_model(self.vllm_url)

    def extract_single_pass(
        self, resume_text: str, pdf_path: str, language: str = "vietnamese", max_retries: int = 5,
        page_images: Optional[list[PageImage]] = None, log_dir: Optional[str] = None
    ) -> tuple[Optional[dict], str]:
        """
        Runs a single LLM extraction pass with retry logic for invalid JSON, with the page images when given.
        Prompt logs go under log_dir when given, else under the run folder's prompt_logs/.
        """
        last_raw_result = ""
        # Named like the extraction JSON and the evaluation, so all of one resume's logs sit together
        resume_name = os.path.splitext(os.path.basename(pdf_path))[0] if pdf_path else "resume"
        full_prompt = prompt_log_text(extraction_messages(resume_text, language, page_images))

        for attempt in range(1, max_retries + 1):
            if self.mock:
                result = run_mock_extraction(resume_text, language=language)
            else:
                result = run_vllm_inference(
                    resume_text, self.model_name, self.vllm_url, language=language, resume_name=resume_name,
                    page_images=page_images
                )

            last_raw_result = result
            log_llm_call(full_prompt, result, EXTRACTION_LOG_CATEGORY, resume_name, run_index=attempt, log_dir=log_dir)
            # Strict: a cut-off answer is retried, then patched and marked as a Repaired Extraction by extract()
            parsed_dict = clean_and_parse_json(result, strict=True)
            if parsed_dict is not None and isinstance(parsed_dict, dict) and len(parsed_dict) > 0:
                return parsed_dict, last_raw_result

            print(f"[Extract Retry] Attempt {attempt}/{max_retries} failed to produce valid JSON. Retrying LLM call...", file=sys.stderr)
            log_broken_json(
                full_prompt, result, EXTRACTION_LOG_CATEGORY, resume_name, attempt=attempt,
                error_reason="Step 1 extraction JSON parse failed", log_dir=log_dir
            )

        return None, last_raw_result

    def extract(self, pdf_path: str, language: str = "vietnamese", max_retries: int = 5, log_dir: Optional[str] = None) -> str:
        pdf_warnings = []
        repaired = False
        page_images = None
        if self.mock:
            # The mock has no server to send page images to, so it gets none
            resume_text = "Mock resume content converted from PDF."
        else:
            try:
                resume_text, pdf_warnings = extract_text_from_pdf(pdf_path)
                page_images, left_out = render_page_images(pdf_path)
                if left_out:
                    pages = ", ".join(str(n) for n in left_out)
                    pdf_warnings.append(
                        f"Pages not shown as images: page(s) {pages} were read from text only; "
                        f"Combined Extraction shows at most {COMBINED_MAX_PAGES} pages."
                    )
            except ScannedResumeError as e:
                print(f"[Extractor Rejected] {pdf_path}: Scanned Resume (no page has text)", file=sys.stderr)
                return json.dumps({"error": str(e), SCANNED_RESUME_KEY: True}, ensure_ascii=False, indent=2)
            except Exception as e:
                error_msg = str(e)
                print(f"[Extractor Rejected] {pdf_path}: {error_msg}", file=sys.stderr)
                return json.dumps({"error": error_msg}, ensure_ascii=False, indent=2)

        final_dict, raw_result = self.extract_single_pass(
            resume_text, pdf_path, language=language, max_retries=max_retries, page_images=page_images, log_dir=log_dir
        )
        if final_dict is None:
            # Fallback if every retry failed to produce clean JSON
            print("Warning: Extraction failed to produce clean JSON. Attempting auto-repair...", file=sys.stderr)
            clean_result = extract_json_substring(raw_result)
            repaired_json = repair_truncated_json(clean_result)
            try:
                final_dict = json.loads(repaired_json)
                repaired = True
            except json.JSONDecodeError:
                print("  Auto-repair failed. Returning raw substring.", file=sys.stderr)
                return clean_result

        if isinstance(final_dict, dict):
            if "error" in final_dict:
                return json.dumps(final_dict, ensure_ascii=False, indent=2)
            warnings = check_extracted_fields_in_markdown(final_dict, resume_text)
            if pdf_warnings:
                warnings.extend(pdf_warnings)
            if repaired:
                warnings.append(REPAIRED_EXTRACTION_WARNING)
            final_dict["warning"] = warnings

            return json.dumps(final_dict, ensure_ascii=False, indent=2)

        return clean_result
