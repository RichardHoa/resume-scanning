"""
HTML Pages FastAPI Router
"""
import os
from fastapi import APIRouter
from fastapi.responses import FileResponse
from src.core.state import state

router = APIRouter(tags=["pages"])


@router.get("/")
@router.get("/extractor")
def read_extractor():
    """Serves the Step 1: CV Extractor HTML page."""
    page_path = os.path.join(state.static_dir, "extractor.html")
    if not os.path.exists(page_path):
        page_path = os.path.join(state.static_dir, "index.html")
    return FileResponse(page_path)


@router.get("/evaluator")
def read_evaluator():
    """Serves the Step 2: HR Evaluator HTML page."""
    return FileResponse(os.path.join(state.static_dir, "evaluator.html"))


@router.get("/rag")
def read_rag():
    """Serves the RAG Knowledge Base HTML page."""
    return FileResponse(os.path.join(state.static_dir, "rag.html"))


@router.get("/candidates")
def read_candidates():
    """Serves the Candidate Evaluation Pool HTML page."""
    return FileResponse(os.path.join(state.static_dir, "candidates.html"))
