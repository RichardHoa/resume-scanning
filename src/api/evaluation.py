"""
Candidate Evaluation & Evaluation Results FastAPI Router
"""
import os
import sys
import json
import math
import time
import asyncio
import traceback
from typing import Any, Dict, List, Optional
from urllib.parse import quote
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from src.api.batch import busy_response
from src.core.batch_jobs import (
    EVALUATE_KIND, BatchBusyError, ItemOutcome, create_job, detached_job, finish_job, run_items, set_items
)
from src.core.config import (
    RESUME_JSON_DIRS, EVALUATION_JSON_DIR, VLLM_MAX_CONCURRENT_REQUESTS, DEFAULT_NUM_EVALUATIONS, CATEGORY_LABELS
)
from src.core.state import state
from src.core.durations import record_duration
from src.core.evaluation_order import (
    load_evaluation_order,
    get_candidate_tier,
    get_report_tier,
    get_eval_search_dirs,
    find_eval_file,
    find_source_resume_path
)
from src.core.resume_pdfs import find_resume_pdf
from src.core.run_files import (
    clear_resume_evaluation, extraction_markdown_path, run_dir_of_evaluation, run_dir_of_extraction
)
from src.core.dev_details import resume_dev_details
from src.pipelines.evaluator_backend import evaluation_report_filename
from src.reports.candidate_report import build_candidate_report_pdf

router = APIRouter(prefix="/api", tags=["evaluation"])


class EvaluationBatchRequest(BaseModel):
    standard_requirements: Optional[str] = Field(default="", description="Standard Job Requirements text")
    hidden_requirements: Optional[str] = Field(default="", description="Hidden Job Requirements text")
    resume_filenames: List[str] = Field(..., description="List of candidate resume JSON filenames to evaluate")
    num_evaluations: Optional[int] = Field(default=DEFAULT_NUM_EVALUATIONS, ge=1, le=100, description="Number of evaluation iterations per category")
    language: Optional[str] = Field(default="vietnamese", description="Output language for evaluation reasoning, strengths, and gaps ('vietnamese' or 'english')")
    use_existing_rag: Optional[bool] = Field(default=False, description="Whether to use already verified and stored RAG criteria")


@router.post("/evaluate_batch")
async def evaluate_batch(payload: EvaluationBatchRequest):
    """Runs a batch evaluation synchronously and returns the results (kept for non-UI callers)."""
    return await _run_batch_evaluation(payload, detached_job(EVALUATE_KIND))


def candidates_in_flight(num_evaluations: int) -> int:
    """
    How many candidates a batch evaluation runs at once. Each candidate sends all its Category runs at once, so with
    every candidate started together they all share the request slots and all finish near the end: nothing comes in
    until the last minute and the progress means nothing. Just enough candidates to fill the slots finish one after
    another instead, and one more keeps the slots busy while a candidate is in its Review Panel, which sends fewer.
    """
    requests_per_candidate = len(CATEGORY_LABELS) * max(1, num_evaluations)
    return math.ceil(VLLM_MAX_CONCURRENT_REQUESTS / requests_per_candidate) + 1


async def _run_batch_evaluation(payload: EvaluationBatchRequest, job: Dict[str, Any]) -> dict:
    """
    Evaluates scanned resumes against HR Standard & Hidden Requirements strictly in secret evaluation_order.
    Logs execution timings per resume and per dimension category.
    Each candidate's earlier evaluation and its prompt logs are cleared first, so the run folder holds only this one.
    The job's items become the candidates, in evaluation order, each with its own state; a cancelled job's
    candidates that never started have no result. Every failure of the Batch itself is raised as an HTTPException.
    """
    try:
        os.environ["DISABLE_PROMPT_LOGGING"] = "0"
        start_batch_time = time.time()
        standard_req = payload.standard_requirements or ""
        hidden_req = payload.hidden_requirements or ""
        filenames = payload.resume_filenames or []
        num_evaluations = payload.num_evaluations or DEFAULT_NUM_EVALUATIONS
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
                llm_decomposer_func=lambda s, h: state.evaluator._decompose_requirements_with_llm(s, h),
                force_reingest=True
            )
        try:
            state.evaluator.rag.require_stored_rag()
        except RuntimeError as e:
            raise HTTPException(status_code=400, detail=str(e))

        order_data = load_evaluation_order()
        candidate_items = []
        for fname in filenames:
            fpath = None
            for sdir in RESUME_JSON_DIRS:
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
            raise HTTPException(status_code=400, detail=f"Selected resume file(s) [{', '.join(filenames[:3])}] were not found in scanned candidate directories ({', '.join(RESUME_JSON_DIRS)}). Please run Step 1 Extraction first.")

        # A resume named twice (or as both its .pdf and .json name) is evaluated once
        candidate_items = list({c["fname"]: c for c in candidate_items}.values())
        candidate_items.sort(key=lambda c: (c["tier"], c["tier_order"], c["fname"]))

        in_flight = candidates_in_flight(num_evaluations)
        print(f"\n================================================================================", file=sys.stderr)
        print(f"[SERVER EVALUATION] Starting evaluation of {len(candidate_items)} candidate resume(s) in evaluation order, {in_flight} at a time within the {VLLM_MAX_CONCURRENT_REQUESTS}-request vLLM limit...", file=sys.stderr)
        print(f"================================================================================", file=sys.stderr)

        candidates_by_name = {item["fname"]: item for item in candidate_items}
        set_items(job, [item["fname"] for item in candidate_items])

        def _evaluate_single_candidate(job_item: Dict[str, Any]) -> ItemOutcome:
            item = candidates_by_name[job_item["name"]]
            fname = item["fname"]
            base_name = os.path.splitext(fname)[0]
            try:
                clear_resume_evaluation(base_name)
                candidate_start_time = time.time()
                eval_result = state.evaluator.evaluate_resume(
                    item["data"],
                    standard_req,
                    hidden_req,
                    resume_name=base_name,
                    output_dir=EVALUATION_JSON_DIR,
                    num_evaluations=num_evaluations,
                    language=eval_language,
                    resume_path=item["fpath"],
                    generate_feedback=True
                )
                # Covers evaluation and the Review Panel, so the waiting-screen estimate includes feedback time
                record_duration("evaluate_candidate", time.time() - candidate_start_time)
                eval_result["candidate_email"] = item["email"]
                eval_result["tier"] = item["tier"]
                eval_result["tier_name"] = item["tier_name"]
                eval_result["tier_order"] = item["tier_order"]
                # As list_eval_results adds them, so the page's report view can link the saved report and resume PDF
                eval_result["filename"] = evaluation_report_filename(base_name)
                eval_result["has_resume_pdf"] = find_resume_pdf(eval_result.get("resume_name") or fname) is not None
                # A Failed Evaluation is a result to show and a failed item to count
                error = (eval_result.get("error") or "Failed Evaluation") if eval_result.get("status") == "error" else None
                return eval_result, error
            except Exception as e:
                print(f"Error evaluating {fname}: {e}\n{traceback.format_exc()}", file=sys.stderr)
                return {
                    "status": "error",
                    "resume_name": fname,
                    "error": str(e),
                    "overall_score": 0,
                    "match_recommendation": "ERROR",
                    "candidate_email": item["email"],
                    "tier": item["tier"],
                    "tier_name": item["tier_name"],
                    "tier_order": item["tier_order"]
                }, str(e)

        await run_items(job, _evaluate_single_candidate, in_flight)
        # In evaluation order; a cancelled candidate that never started has no result
        results = [job_item["result"] for job_item in job["items"] if job_item["result"] is not None]

        total_batch_time = time.time() - start_batch_time

        # Output formatted server log summary
        print(f"\n================================================================================", file=sys.stderr)
        print(f"[SERVER EVALUATION TIMING SUMMARY] Total Batch Elapsed Time: {total_batch_time:.2f}s", file=sys.stderr)
        print(f"--------------------------------------------------------------------------------", file=sys.stderr)
        for res in results:
            rname = res.get("resume_name", "unknown")
            timings = res.get("execution_timings", {}) if isinstance(res.get("execution_timings"), dict) else {}
            t_resume = timings.get("total_resume_evaluation_seconds", 0.0)
            print(f"Resume: '{rname}' (Tier {res.get('tier', 3)})", file=sys.stderr)
            print(f"  ├─ Total Resume Evaluation:       {t_resume:.2f}s", file=sys.stderr)
            cat_t = timings.get("category_timings_seconds", {}) if isinstance(timings.get("category_timings_seconds"), dict) else {}
            for cat_k, cat_v in cat_t.items():
                print(f"  │   ├─ Dimension [{cat_k}]: {cat_v:.2f}s", file=sys.stderr)
        print(f"================================================================================\n", file=sys.stderr)

        return {
            "results": results,
            "total_evaluated": len(results),
            "batch_execution_time_seconds": round(total_batch_time, 2)
        }
    except HTTPException:
        raise
    except Exception as main_err:
        traceback.print_exc()
        raise HTTPException(status_code=500, detail=f"Evaluation failed: {str(main_err)}")


async def _run_eval_job(job: Dict[str, Any], payload: EvaluationBatchRequest) -> None:
    """Background task body: runs the batch on the job and records its results or error."""
    try:
        finish_job(job, result=await _run_batch_evaluation(payload, job))
    except HTTPException as http_err:
        finish_job(job, error=str(http_err.detail))
    except Exception as unexpected_err:
        traceback.print_exc()
        finish_job(job, error=f"Evaluation failed: {str(unexpected_err)}")
    finally:
        job.pop("task", None)


@router.post("/evaluate_batch/jobs")
async def start_evaluation_job(payload: EvaluationBatchRequest):
    """Starts a batch evaluation as a background Batch job and returns its id immediately."""
    if not payload.resume_filenames:
        raise HTTPException(status_code=400, detail="No resume filenames selected for evaluation.")
    if not state.evaluator:
        raise HTTPException(status_code=500, detail="Resume Evaluator model is not initialized on the server.")

    try:
        # The items are the requested names until the candidates are loaded, in evaluation order
        job = create_job(EVALUATE_KIND, list(payload.resume_filenames))
    except BatchBusyError as busy:
        return busy_response(busy)
    # Keep a reference to the task so it isn't garbage-collected while running.
    job["task"] = asyncio.create_task(_run_eval_job(job, payload))
    return {"job_id": job["id"]}


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
                        tinfo = get_report_tier(data, fname, order_data)
                        data["tier"] = tinfo["tier"]
                        data["tier_name"] = tinfo["tier_name"]
                        data["tier_order"] = tinfo["tier_order"]
                        data["candidate_email"] = tinfo["resolved_email"]
                        data["has_resume_pdf"] = find_resume_pdf(data.get("resume_name") or fname) is not None
                        # Results of a pipeline run are shown on the website but never deleted from it
                        data["read_only"] = folder != EVALUATION_JSON_DIR
                        evaluations.append(data)
                except Exception as e:
                    print(f"Warning: Failed to parse evaluation file {fpath}: {e}", file=sys.stderr)

    # Sort evaluations strictly by Tier 1 -> Tier 2 -> Tier 3 and tier_order
    evaluations.sort(key=lambda item: (item.get("tier", 3), item.get("tier_order", 9999), item.get("filename", "")))
    return {
        "evaluations": evaluations,
        "evaluation_order_active": order_data["file_found"],
        "evaluation_order_path": order_data["file_path"],
        "tech_mode": order_data["tech_mode"],
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


def _load_eval_result(filename: str) -> dict:
    fpath = find_eval_file(filename)
    if not fpath:
        raise HTTPException(status_code=404, detail="Evaluation result file not found.")
    try:
        with open(fpath, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read evaluation file: {e}")
    if not isinstance(data, dict):
        raise HTTPException(status_code=500, detail="Evaluation file is not a JSON object.")
    return data


@router.get("/eval_results/{filename}/resume_pdf")
def get_eval_resume_pdf(filename: str):
    """Serves the candidate's original resume PDF inline, so it opens in the browser's PDF viewer."""
    data = _load_eval_result(filename)
    pdf_path = find_resume_pdf(data.get("resume_name") or filename)
    if not pdf_path:
        raise HTTPException(status_code=404, detail="No resume PDF is stored for this candidate.")
    return FileResponse(pdf_path, media_type="application/pdf", content_disposition_type="inline")


@router.get("/eval_results/{filename}/resume_json")
def get_eval_resume_json(filename: str):
    """Developer view: the extracted resume JSON this evaluation was made from, served inline."""
    resume_path = find_source_resume_path(_load_eval_result(filename))
    if not resume_path:
        raise HTTPException(status_code=404, detail="The extracted resume JSON for this candidate is gone.")
    return FileResponse(resume_path, media_type="application/json", content_disposition_type="inline")


@router.get("/eval_results/{filename}/resume_markdown")
def get_eval_resume_markdown(filename: str):
    """Developer view: the markdown text extracted from the resume PDF, served inline as plain text."""
    md_path = _find_extraction_markdown(filename, _load_eval_result(filename))
    if not md_path:
        raise HTTPException(status_code=404, detail="No extraction markdown is stored for this candidate.")
    return FileResponse(md_path, media_type="text/plain; charset=utf-8", content_disposition_type="inline")


def _find_extraction_markdown(filename: str, report: dict) -> Optional[str]:
    """The extraction markdown behind an evaluation, from the run folder that extracted the resume, or None."""
    resume_path = find_source_resume_path(report)
    run_dir = run_dir_of_extraction(resume_path, run_dir_of_evaluation(find_eval_file(filename)))
    names = [os.path.basename(resume_path)] if resume_path else []
    names.append(report.get("resume_name") or filename)
    for name in names:
        md_path = extraction_markdown_path(run_dir, name)
        if os.path.isfile(md_path):
            return md_path
    return None


@router.get("/eval_results/{filename}/dev_details")
def get_eval_dev_details(filename: str):
    """
    Developer view: everything stored for one evaluated resume in its run folder (extraction markdown and JSON,
    the evaluation JSON, every prompt log and its token usage). Run-wide logs are left out.
    """
    fpath = find_eval_file(filename)
    if not fpath:
        raise HTTPException(status_code=404, detail="Evaluation result file not found.")
    report = _load_eval_result(filename)
    run_dir = run_dir_of_evaluation(fpath)
    resume_path = find_source_resume_path(report)
    return resume_dev_details(
        run_dir,
        run_dir_of_extraction(resume_path, run_dir),
        report.get("resume_name") or filename,
        report,
        resume_path,
        _find_extraction_markdown(filename, report)
    )


@router.get("/eval_results/{filename}/report_pdf")
def get_eval_report_pdf(filename: str):
    """The evaluation report as a PDF for HR, with the candidate's resume PDF appended when one is stored."""
    data = _load_eval_result(filename)
    # The email the page shows comes from evaluation_order matching, not from the saved report
    data["candidate_email"] = get_report_tier(data, filename, load_evaluation_order())["resolved_email"]
    try:
        pdf_bytes = build_candidate_report_pdf(data, find_resume_pdf(data.get("resume_name") or filename))
    except Exception as e:
        print(f"Error building report PDF for {filename}: {e}\n{traceback.format_exc()}", file=sys.stderr)
        raise HTTPException(status_code=500, detail=f"Failed to build report PDF: {e}")
    download_name = os.path.splitext(os.path.basename(filename))[0] + "_danh_gia.pdf"
    return Response(
        content=pdf_bytes,
        media_type="application/pdf",
        headers={"Content-Disposition": f"attachment; filename*=UTF-8''{quote(download_name)}"}
    )


@router.delete("/eval_results/{filename}")
def delete_eval_result(filename: str):
    """
    Deletes an evaluation made on the website, with its evaluation prompt logs and token usage (the extraction
    stays). A pipeline run's evaluations are read-only here.
    """
    fpath = find_eval_file(filename)
    if not fpath:
        raise HTTPException(status_code=404, detail="Evaluation file not found.")
    if os.path.dirname(fpath) != EVALUATION_JSON_DIR:
        raise HTTPException(status_code=403, detail="This evaluation comes from a pipeline run and cannot be deleted from the website.")
    resume_name = _load_eval_result(filename).get("resume_name")
    try:
        if resume_name:
            clear_resume_evaluation(resume_name)
        if os.path.isfile(fpath):
            os.remove(fpath)
        return {"success": True, "message": f"Deleted {os.path.basename(fpath)}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
