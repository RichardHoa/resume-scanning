"""
Configuration & Tier Order FastAPI Router
"""
from fastapi import APIRouter
from src.core.state import state
from src.core.evaluation_order import load_evaluation_order

router = APIRouter(prefix="/api", tags=["config"])


@router.get("/evaluation_order")
def get_evaluation_order():
    """Exposes tier email ordering from secret evaluation_order file."""
    return load_evaluation_order()


@router.get("/config")
def get_config():
    """Exposes current server configuration to the UI."""
    return {
        "model": state.extractor.model_name if state.extractor else None,
        "backend": state.args.backend if state.args else "vllm",
        "image_mode": False,
        "mock": state.args.mock if state.args else False
    }
