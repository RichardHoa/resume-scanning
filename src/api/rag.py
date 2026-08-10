"""
RAG Knowledge Base FastAPI Router
"""
from fastapi import APIRouter
from src.core.state import state

router = APIRouter(prefix="/api", tags=["rag"])


@router.get("/rag")
def get_rag_info():
    """Returns stored RAG database info, item breakdown across 5 dimensions, and hr_rag.txt content."""
    return state.evaluator.rag.get_stored_rag_summary()


@router.delete("/rag")
def clear_rag_info():
    """Clears the persistent RAG database so a new requirement set can be categorized."""
    state.evaluator.rag.clear_rag_database()
    return {
        "success": True,
        "message": "Persistent RAG database cleared successfully. Next evaluation run will perform new requirement categorization."
    }
