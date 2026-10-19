"""
HTML Pages FastAPI Router

Each page is a Jinja template in src/templates/ extending base.html, the shared layout.
active_page marks the page's rail link and names its controller in <body data-page>.
"""
import os
from fastapi import APIRouter, Request
from fastapi.templating import Jinja2Templates

router = APIRouter(tags=["pages"])

templates = Jinja2Templates(directory=os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates"))


def _page(request: Request, active_page: str):
    return templates.TemplateResponse(request, f"{active_page}.html", {"active_page": active_page})


@router.get("/")
@router.get("/extractor")
def read_extractor(request: Request):
    """Serves the Step 1: CV Extractor HTML page."""
    return _page(request, "extractor")


@router.get("/evaluator")
def read_evaluator(request: Request):
    """Serves the Step 2: HR Evaluator HTML page."""
    return _page(request, "evaluator")


@router.get("/rag")
def read_rag(request: Request):
    """Serves the RAG Knowledge Base HTML page."""
    return _page(request, "rag")


@router.get("/candidates")
def read_candidates(request: Request):
    """Serves the Candidate Evaluation Pool HTML page."""
    return _page(request, "candidates")
