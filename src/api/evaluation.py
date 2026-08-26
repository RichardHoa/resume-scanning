"""
Candidate Evaluation & Evaluation Results FastAPI Router
"""
import os
import sys
import json
import time
import asyncio
from datetime import datetime
from typing import List, Optional
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from src.core.config import APPROVED_DIR, OUTPUT_DIR, EVAL_RESULTS_DIR, LOGGING_DIR
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
    num_evaluations: Optional[int] = Field(default=1, ge=1, le=100, description="Number of evaluation iterations per category")
    language: Optional[str] = Field(default="vietnamese", description="Output language for evaluation reasoning, strengths, and gaps ('vietnamese' or 'english')")
    use_existing_rag: Optional[bool] = Field(default=False, description="Whether to use already verified and stored RAG criteria")


@router.post("/evaluate_batch")
async def evaluate_batch(payload: EvaluationBatchRequest):
    """
    Evaluates scanned resumes against HR Standard & Hidden Requirements strictly in secret evaluation_order.
    Logs execution timings per requirement decomposition, per resume, and per dimension category.
    Outputs all raw prompt context & response logs into a structured web_evaluations folder hierarchy.
    Runs evaluation in worker thread via asyncio.to_thread to prevent blocking the FastAPI event loop.
    """
    import re
    import traceback

    try:
        os.environ["DISABLE_PROMPT_LOGGING"] = "0"
        start_batch_time = time.time()
        standard_req = payload.standard_requirements or ""
        hidden_req = payload.hidden_requirements or ""
        filenames = payload.resume_filenames or []
        num_evaluations = payload.num_evaluations or 1
        eval_language = payload.language or "vietnamese"
        use_existing_rag = payload.use_existing_rag

        if not filenames:
            raise HTTPException(status_code=400, detail="No resume filenames selected for evaluation.")

        if not state.evaluator:
            raise HTTPException(status_code=500, detail="Resume Evaluator model is not initialized on the server.")

        # If not using existing RAG and new requirements are given, pre-ingest them once for batch
        if not use_existing_rag and (standard_req or hidden_req):
            print("[SERVER EVALUATION] Pre-ingesting new HR requirements into RAG vector store...", file=sys.stderr)
            await asyncio.to_thread(
                state.evaluator.rag.ingest_requirements,
                standard_req,
                hidden_req,
                llm_decomposer_func=lambda s, h: state.evaluator._decompose_requirements_with_llm(s, h, "batch_init"),
                force_reingest=True
            )

        # Create structured logging folder hierarchy for web evaluation batch session
        batch_timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        web_batch_log_dir = os.path.join(LOGGING_DIR, "web_evaluations", f"batch_{batch_timestamp}")
        os.makedirs(web_batch_log_dir, exist_ok=True)

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
                # Fallback check for .json extension if pdf filename was passed
                if not fname.endswith(".json"):
                    alt_name = os.path.splitext(fname)[0] + ".json"
                    candidate_alt_path = os.path.join(sdir, alt_name)
                    if os.path.exists(candidate_alt_path):
                        fpath = candidate_alt_path
                        fname = alt_name
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

        if not candidate_items:
            raise HTTPException(status_code=400, detail=f"Selected resume file(s) [{', '.join(filenames[:3])}] were not found in scanned candidate directories ({APPROVED_DIR}, {OUTPUT_DIR}). Please run Step 1 Extraction first.")

        candidate_items.sort(key=lambda c: (c["tier"], c["tier_order"], c["fname"]))

        print(f"\n================================================================================", file=sys.stderr)
        print(f"[SERVER EVALUATION] Starting evaluation of {len(candidate_items)} candidate resume(s) with up to 20 concurrent workers in evaluation order...", file=sys.stderr)
        print(f"[SERVER EVALUATION] Output prompt logs directory: {web_batch_log_dir}", file=sys.stderr)
        print(f"================================================================================", file=sys.stderr)

        semaphore = asyncio.Semaphore(20)

        async def _evaluate_single_candidate(item):
            async with semaphore:
                fname = item["fname"]
                resume_data = item["data"]
                base_name = os.path.splitext(fname)[0]
                safe_base_name = re.sub(r'[^a-zA-Z0-9_-]', '_', base_name or "candidate")
                cand_log_dir = os.path.join(web_batch_log_dir, safe_base_name)
                os.makedirs(cand_log_dir, exist_ok=True)

                try:
                    eval_result = await asyncio.to_thread(
                        state.evaluator.evaluate_resume,
                        resume_data,
                        standard_req,
                        hidden_req,
                        resume_name=base_name,
                        output_dir=EVAL_RESULTS_DIR,
                        num_evaluations=num_evaluations,
                        language=eval_language,
                        log_dir=cand_log_dir
                    )
                    eval_result["candidate_email"] = item["email"]
                    eval_result["tier"] = item["tier"]
                    eval_result["tier_name"] = item["tier_name"]
                    eval_result["tier_order"] = item["tier_order"]
                    eval_result["prompt_log_dir"] = cand_log_dir
                    return eval_result
                except Exception as e:
                    print(f"Error evaluating {fname}: {e}\n{traceback.format_exc()}", file=sys.stderr)
                    return {
                        "resume_name": fname,
                        "error": str(e),
                        "overall_score": 0,
                        "match_recommendation": "ERROR",
                        "candidate_email": item["email"],
                        "tier": item["tier"],
                        "tier_name": item["tier_name"],
                        "tier_order": item["tier_order"],
                        "prompt_log_dir": cand_log_dir
                    }

        # Run candidate evaluations concurrently up to 20 at a time, preserving order in results
        results = list(await asyncio.gather(*[_evaluate_single_candidate(item) for item in candidate_items]))

        total_batch_time = time.time() - start_batch_time

        # Write manifest summary into the structured web batch prompt logs directory
        manifest_path = os.path.join(web_batch_log_dir, "batch_prompt_logs_manifest.json")
        manifest_data = {
            "batch_timestamp": datetime.now().isoformat(),
            "web_batch_log_dir": web_batch_log_dir,
            "total_candidates": len(candidate_items),
            "num_evaluations_per_category": num_evaluations,
            "language": eval_language,
            "candidates": [item["fname"] for item in candidate_items]
        }
        try:
            with open(manifest_path, "w", encoding="utf-8") as f:
                json.dump(manifest_data, f, ensure_ascii=False, indent=2)
        except Exception as e:
            print(f"Warning: Failed to write prompt logs manifest to {manifest_path}: {e}", file=sys.stderr)

        # Output formatted server log summary
        print(f"\n================================================================================", file=sys.stderr)
        print(f"[SERVER EVALUATION TIMING SUMMARY] Total Batch Elapsed Time: {total_batch_time:.2f}s", file=sys.stderr)
        print(f"[SERVER EVALUATION PROMPT LOGS] Saved to: {web_batch_log_dir}", file=sys.stderr)
        print(f"--------------------------------------------------------------------------------", file=sys.stderr)
        for res in results:
            rname = res.get("resume_name", "unknown")
            timings = res.get("execution_timings", {}) if isinstance(res.get("execution_timings"), dict) else {}
            t_decomp = timings.get("requirement_decomposition_seconds", 0.0)
            t_resume = timings.get("total_resume_evaluation_seconds", 0.0)
            print(f"Resume: '{rname}' (Tier {res.get('tier', 3)})", file=sys.stderr)
            print(f"  ├─ HR Requirement Categorization: {t_decomp:.2f}s", file=sys.stderr)
            print(f"  ├─ Total Resume Evaluation:       {t_resume:.2f}s", file=sys.stderr)
            cat_t = timings.get("category_timings_seconds", {}) if isinstance(timings.get("category_timings_seconds"), dict) else {}
            for cat_k, cat_v in cat_t.items():
                print(f"  │   ├─ Dimension [{cat_k}]: {cat_v:.2f}s", file=sys.stderr)
        print(f"================================================================================\n", file=sys.stderr)

        return {
            "results": results,
            "total_evaluated": len(results),
            "batch_execution_time_seconds": round(total_batch_time, 2),
            "prompt_logs_dir": web_batch_log_dir,
            "prompt_logs_manifest": manifest_path
        }
    except HTTPException:
        raise
    except Exception as main_err:
        import traceback
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Evaluation failed: {str(main_err)}")


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
