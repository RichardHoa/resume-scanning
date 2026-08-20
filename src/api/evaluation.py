"""
Candidate Evaluation & Evaluation Results FastAPI Router
"""
import os
import sys
import json
import time
import asyncio
from typing import List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.core.config import APPROVED_DIR, OUTPUT_DIR, EVAL_RESULTS_DIR
from src.core.state import state
from src.core.evaluation_order import (
    load_evaluation_order,
    get_candidate_tier,
    get_eval_search_dirs,
    find_eval_file
)

router = APIRouter(prefix="/api", tags=["evaluation"])


class EvaluationBatchRequest(BaseModel):
    standard_requirements: Optional[str] = Field(default="", description="Standard Job Requirements text")
    hidden_requirements: Optional[str] = Field(default="", description="Hidden Job Requirements text")
    resume_filenames: List[str] = Field(..., description="List of candidate resume JSON filenames to evaluate")
    num_evaluations: Optional[int] = Field(default=20, ge=1, le=100, description="Number of evaluation iterations per category")
    language: Optional[str] = Field(default="vietnamese", description="Output language for evaluation reasoning, strengths, and gaps ('vietnamese' or 'english')")


@router.post("/evaluate_batch")
async def evaluate_batch(payload: EvaluationBatchRequest):
    """
    Evaluates scanned resumes against HR Standard & Hidden Requirements strictly in secret evaluation_order.
    Logs execution timings per requirement decomposition, per resume, and per dimension category.
    Runs evaluation in worker thread via asyncio.to_thread to prevent blocking the FastAPI event loop.
    """
    start_batch_time = time.time()
    standard_req = payload.standard_requirements or ""
    hidden_req = payload.hidden_requirements or ""
    filenames = payload.resume_filenames or []
    num_evaluations = payload.num_evaluations or 20
    eval_language = payload.language or "vietnamese"

    if not filenames:
        raise HTTPException(status_code=400, detail="No resume filenames selected for evaluation.")

    if not state.evaluator:
        raise HTTPException(status_code=500, detail="Resume Evaluator model is not initialized on the server.")

    order_data = load_evaluation_order()
    search_dirs = [
        APPROVED_DIR,
        OUTPUT_DIR
    ]

    candidate_items = []
    for fname in filenames:
        fpath = None
        for sdir in search_dirs:
            candidate_path = os.path.join(sdir, fname)
            if os.path.exists(candidate_path):
                fpath = candidate_path
                break
        if not fpath:
            continue
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                data = json.load(f)
            tinfo = get_candidate_tier(data, fname, order_data)
            candidate_items.append({
                "fname": fname,
                "fpath": fpath,
                "data": data,
                "email": tinfo["resolved_email"],
                "tier": tinfo["tier"],
                "tier_name": tinfo["tier_name"],
                "tier_order": tinfo["tier_order"]
            })
        except Exception as e:
            print(f"Error pre-loading candidate {fname}: {e}", file=sys.stderr)

    candidate_items.sort(key=lambda c: (c["tier"], c["tier_order"], c["fname"]))

    results = []
    print(f"\n================================================================================", file=sys.stderr)
    print(f"[SERVER EVALUATION] Starting evaluation of {len(candidate_items)} candidate resume(s) in evaluation order...", file=sys.stderr)
    print(f"================================================================================", file=sys.stderr)

    for item in candidate_items:
        fname = item["fname"]
        resume_data = item["data"]
        base_name = os.path.splitext(fname)[0]
        try:
            eval_result = await asyncio.to_thread(
                state.evaluator.evaluate_resume,
                resume_data,
                standard_req,
                hidden_req,
                resume_name=base_name,
                output_dir=EVAL_RESULTS_DIR,
                num_evaluations=num_evaluations,
                language=eval_language
            )
            eval_result["candidate_email"] = item["email"]
            eval_result["tier"] = item["tier"]
            eval_result["tier_name"] = item["tier_name"]
            eval_result["tier_order"] = item["tier_order"]

            results.append(eval_result)
        except Exception as e:
            print(f"Error evaluating {fname}: {e}", file=sys.stderr)
            results.append({
                "resume_name": fname,
                "error": str(e),
                "overall_score": 0,
                "match_recommendation": "ERROR",
                "candidate_email": item["email"],
                "tier": item["tier"],
                "tier_name": item["tier_name"],
                "tier_order": item["tier_order"]
            })


    total_batch_time = time.time() - start_batch_time

    # Output formatted server log summary
    print(f"\n================================================================================", file=sys.stderr)
    print(f"[SERVER EVALUATION TIMING SUMMARY] Total Batch Elapsed Time: {total_batch_time:.2f}s", file=sys.stderr)
    print(f"--------------------------------------------------------------------------------", file=sys.stderr)
    for res in results:
        rname = res.get("resume_name", "unknown")
        timings = res.get("execution_timings", {})
        t_decomp = timings.get("requirement_decomposition_seconds", 0.0)
        t_resume = timings.get("total_resume_evaluation_seconds", 0.0)
        print(f"Resume: '{rname}' (Tier {res.get('tier', 3)})", file=sys.stderr)
        print(f"  ├─ HR Requirement Categorization: {t_decomp:.2f}s", file=sys.stderr)
        print(f"  ├─ Total Resume Evaluation:       {t_resume:.2f}s", file=sys.stderr)
        cat_t = timings.get("category_timings_seconds", {})
        for cat_k, cat_v in cat_t.items():
            print(f"  │   ├─ Dimension [{cat_k}]: {cat_v:.2f}s", file=sys.stderr)
    print(f"================================================================================\n", file=sys.stderr)

    return {
        "results": results,
        "total_evaluated": len(results),
        "batch_execution_time_seconds": round(total_batch_time, 2)
    }


@router.get("/eval_results")
def list_eval_results():
    """Lists all candidate evaluation JSON results from all candidate folders, sorted by secret evaluation_order."""
    order_data = load_evaluation_order()
    evaluations = []
    seen_filenames = set()

    for folder in get_eval_search_dirs():
        for fname in sorted(os.listdir(folder)):
            if fname.endswith(".json") and fname not in seen_filenames:
                seen_filenames.add(fname)
                fpath = os.path.join(folder, fname)
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if isinstance(data, dict):
                        data["filename"] = fname
                        tinfo = get_candidate_tier(data, fname, order_data)
                        data["tier"] = tinfo["tier"]
                        data["tier_name"] = tinfo["tier_name"]
                        data["tier_order"] = tinfo["tier_order"]
                        data["candidate_email"] = tinfo["resolved_email"]
                        evaluations.append(data)
                except Exception as e:
                    print(f"Warning: Failed to parse evaluation file {fpath}: {e}", file=sys.stderr)

    # Sort evaluations strictly by Tier 1 -> Tier 2 -> Tier 3 and tier_order
    evaluations.sort(key=lambda item: (item.get("tier", 3), item.get("tier_order", 9999), item.get("filename", "")))
    return {
        "evaluations": evaluations,
        "evaluation_order_active": order_data["file_found"],
        "evaluation_order_path": order_data["file_path"],
        "tier1_count": len(order_data["tier1"]),
        "tier2_count": len(order_data["tier2"])
    }


@router.get("/eval_results/{filename}")
def get_eval_result_detail(filename: str):
    """Retrieves full evaluation report JSON for a specific candidate."""
    fpath = find_eval_file(filename)
    if not fpath:
        raise HTTPException(status_code=404, detail="Evaluation result file not found.")
    try:
        with open(fpath, "r", encoding="utf-8") as f:
            data = json.load(f)
        if isinstance(data, dict):
            data["filename"] = os.path.basename(fpath)
        return data
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read evaluation file: {e}")


@router.delete("/eval_results/{filename}")
def delete_eval_result(filename: str):
    """Deletes an evaluation result file from EVAL_RESULTS_DIR or EVALUATION_JSON_DIR."""
    fpath = find_eval_file(filename)
    if not fpath:
        raise HTTPException(status_code=404, detail="Evaluation file not found.")
    try:
        os.remove(fpath)
        return {"success": True, "message": f"Deleted {os.path.basename(fpath)}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
