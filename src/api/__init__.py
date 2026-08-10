"""
API Routers Package
"""
from fastapi import FastAPI
from src.api.pages import router as pages_router
from src.api.config import router as config_router
from src.api.extraction import router as extraction_router
from src.api.evaluation import router as evaluation_router
from src.api.rag import router as rag_router


def include_api_routers(app: FastAPI) -> None:
    """Registers all modular API routers with the FastAPI application."""
    app.include_router(pages_router)
    app.include_router(config_router)
    app.include_router(extraction_router)
    app.include_router(evaluation_router)
    app.include_router(rag_router)
