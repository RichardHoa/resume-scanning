import asyncio
from typing import Dict, List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field
from src.core.state import state

router = APIRouter(prefix="/api", tags=["rag"])


class DecomposeRequirementsRequest(BaseModel):
    standard_requirements: Optional[str] = Field(default="", description="Standard Job Requirements text")
    hidden_requirements: Optional[str] = Field(default="", description="Hidden Job Requirements text")
    language: Optional[str] = Field(default="vietnamese", description="Output language ('vietnamese' or 'english')")


class UpdateRagCriteriaRequest(BaseModel):
    categories: Dict[str, List[str]] = Field(..., description="Map of dimension categories to lists of criteria strings")
    standard_requirements: Optional[str] = Field(default="", description="Raw standard requirements text")
    hidden_requirements: Optional[str] = Field(default="", description="Raw hidden requirements text")


@router.get("/rag")
def get_rag_info():
    """Returns stored RAG database info, item breakdown across 5 dimensions, and hr_rag.txt content."""
    if not state.evaluator:
        raise HTTPException(status_code=500, detail="Resume Evaluator model is not initialized on the server.")
    return state.evaluator.rag.get_stored_rag_summary()


@router.post("/rag/decompose")
async def decompose_requirements_endpoint(payload: DecomposeRequirementsRequest):
    """
    Decomposes HR requirements across 5 RAG dimensions, updates vector store and hr_rag.txt,
    and returns the structured summary without evaluating candidate resumes.
    """
    if not state.evaluator:
        raise HTTPException(status_code=500, detail="Resume Evaluator model is not initialized on the server.")

    std_req = (payload.standard_requirements or "").strip()
    hidden_req = (payload.hidden_requirements or "").strip()

    if not std_req and not hidden_req:
        raise HTTPException(status_code=400, detail="Please provide Standard Job Requirements or Hidden Requirements.")

    try:
        summary = await asyncio.to_thread(
            state.evaluator.decompose_requirements,
            std_req,
            hidden_req
        )
        return {
            "success": True,
            "message": "Requirements successfully categorized and saved into RAG database.",
            **summary
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Requirement categorization failed: {str(e)}")


@router.post("/rag/update")
def update_rag_criteria_endpoint(payload: UpdateRagCriteriaRequest):
    """
    Updates the active RAG vector database with manually adjusted category criteria,
    re-computes embeddings, and updates hr_rag.txt.
    """
    if not state.evaluator:
        raise HTTPException(status_code=500, detail="Resume Evaluator model is not initialized on the server.")

    try:
        summary = state.evaluator.rag.update_criteria_manually(
            payload.categories,
            standard_req=payload.standard_requirements or "",
            hidden_req=payload.hidden_requirements or ""
        )
        return {
            "success": True,
            "message": "RAG criteria and hr_rag.txt updated successfully.",
            **summary
        }
    except Exception as e:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Failed to update RAG criteria: {str(e)}")


@router.delete("/rag")
def clear_rag_info():
    """Clears the persistent RAG database so a new requirement set can be categorized."""
    if not state.evaluator:
        raise HTTPException(status_code=500, detail="Resume Evaluator model is not initialized on the server.")
    state.evaluator.rag.clear_rag_database()
    return {
        "success": True,
        "message": "Persistent RAG database cleared successfully. Next evaluation run will perform new requirement categorization."
    }
