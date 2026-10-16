"""
Original resume PDFs, kept at extraction under the same base name as the extraction JSON (and so the same
`resume_name` the evaluation report carries).
"""
import os
import shutil
from typing import Optional

from src.core.config import RESUME_PDF_DIR, SOURCE_RUN_DIRS
from src.core.run_files import base_name, resume_pdf_path


def store_resume_pdf(pdf_path: str, resume_name: str) -> None:
    """Copies an extracted resume's PDF into the active run folder's RESUME_PDF_DIR, replacing any earlier copy."""
    if not base_name(resume_name):
        return
    target = os.path.join(RESUME_PDF_DIR, base_name(resume_name) + ".pdf")
    if os.path.abspath(pdf_path) != os.path.abspath(target):
        os.makedirs(RESUME_PDF_DIR, exist_ok=True)
        shutil.copyfile(pdf_path, target)


def find_resume_pdf(resume_name: str) -> Optional[str]:
    """The stored PDF for a resume name or file name, from the run folders read (the active one first), or None."""
    if not base_name(resume_name):
        return None
    for run_dir in SOURCE_RUN_DIRS:
        path = resume_pdf_path(run_dir, resume_name)
        if os.path.isfile(path):
            return path
    return None
