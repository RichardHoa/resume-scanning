"""
Original resume PDFs, kept at extraction under the same base name as the extraction JSON (and so the same
`resume_name` the evaluation report carries).
"""
import os
import shutil
from typing import Optional

from src.core.config import RESUME_PDF_DIR


def _pdf_path(resume_name: str) -> Optional[str]:
    """The stored PDF path for a resume name or file name, or None when the name is empty."""
    base_name = os.path.splitext(os.path.basename(resume_name or ""))[0]
    return os.path.join(RESUME_PDF_DIR, base_name + ".pdf") if base_name else None


def store_resume_pdf(pdf_path: str, resume_name: str) -> None:
    """Copies an extracted resume's PDF into RESUME_PDF_DIR, replacing any earlier copy."""
    target = _pdf_path(resume_name)
    if target and os.path.abspath(pdf_path) != os.path.abspath(target):
        os.makedirs(RESUME_PDF_DIR, exist_ok=True)
        shutil.copyfile(pdf_path, target)


def find_resume_pdf(resume_name: str) -> Optional[str]:
    """The stored PDF for a resume name or file name, or None when none was kept."""
    path = _pdf_path(resume_name)
    return path if path and os.path.isfile(path) else None
