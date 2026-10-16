"""
Candidate Evaluation & Evaluation Results FastAPI Router
"""
import os
import sys
import json
import time
import uuid
import asyncio
import traceback
from concurrent.futures import ThreadPoolExecutor
from typing import Callable, List, Optional
from urllib.parse import quote
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse, Response
from pydantic import BaseModel, Field

from src.core.config import (
    RESUME_JSON_DIRS, EVALUATION_JSON_DIR, EVAL_JOB_TTL_SECONDS, VLLM_MAX_CONCURRENT_REQUESTS
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
from src.reports.candidate_report import build_candidate_report_pdf
from src.providers.rag_engine import NO_HR_RAG_MESSAGE

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
    """Runs a batch evaluation synchronously and returns the results (kept for non-UI callers)."""
    return await _run_batch_evaluation(payload)


async def _run_batch_evaluation(
    payload: EvaluationBatchRequest,
    on_progress: Optional[Callable[[int, int], None]] = None
) -> dict:
    """
    Evaluates scanned resumes against HR Standard & Hidden Requirements strictly in secret evaluation_order.
    Logs execution timings per resume and per dimension category.
    Each candidate's earlier evaluation and its prompt logs are cleared first, so the run folder holds only this one.
    Runs evaluation in worker thread via asyncio.to_thread to prevent blocking the FastAPI event loop.
    Calls on_progress(completed, total) once the candidate list is known and after each candidate
    finishes. Every failure is raised as an HTTPException.
    """
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
                llm_decomposer_func=lambda s, h: state.evaluator._decompose_requirements_with_llm(s, h),
                force_reingest=True
            )
        if not state.evaluator.rag.has_stored_rag():
            raise HTTPException(status_code=400, detail=NO_HR_RAG_MESSAGE)

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

        candidate_items.sort(key=lambda c: (c["tier"], c["tier_order"], c["fname"]))

        print(f"\n================================================================================", file=sys.stderr)
        print(f"[SERVER EVALUATION] Starting evaluation of {len(candidate_items)} candidate resume(s) in evaluation order, throttled by the {VLLM_MAX_CONCURRENT_REQUESTS}-request vLLM limit...", file=sys.stderr)
        print(f"================================================================================", file=sys.stderr)

        # Candidates are scheduled freely; the process-wide vLLM request limit does the throttling. The
        # default asyncio executor is too small for that, so the batch gets its own threads. More candidates
        # in flight than request slots could never add throughput, so that is the thread count.
        loop = asyncio.get_running_loop()
        executor = ThreadPoolExecutor(
            max_workers=min(len(candidate_items), VLLM_MAX_CONCURRENT_REQUESTS),
            thread_name_prefix="eval-candidate"
        )
        total_candidates = len(candidate_items)
        completed_count = 0
        if on_progress:
            on_progress(completed_count, total_candidates)

        def _mark_candidate_done():
            nonlocal completed_count
            completed_count += 1
            if on_progress:
                on_progress(completed_count, total_candidates)

        async def _evaluate_single_candidate(item):
            fname = item["fname"]
            resume_data = item["data"]
            base_name = os.path.splitext(fname)[0]

            try:
                clear_resume_evaluation(base_name)
                candidate_start_time = time.time()
                eval_result = await loop.run_in_executor(
                    executor,
                    lambda: state.evaluator.evaluate_resume(
                        resume_data,
                        standard_req,
                        hidden_req,
                        resume_name=base_name,
                        output_dir=EVALUATION_JSON_DIR,
                        num_evaluations=num_evaluations,
                        language=eval_language,
                        resume_path=item["fpath"],
                        generate_feedback=True
                    )
                )
                # Covers evaluation and the Review Panel, so the waiting-screen estimate includes feedback time
                record_duration("evaluate_candidate", time.time() - candidate_start_time)
                eval_result["candidate_email"] = item["email"]
                eval_result["tier"] = item["tier"]
                eval_result["tier_name"] = item["tier_name"]
                eval_result["tier_order"] = item["tier_order"]
                return eval_result
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
                }
            finally:
                _mark_candidate_done()

        # Run all candidate evaluations concurrently, preserving order in results
        try:
            results = list(await asyncio.gather(*[_evaluate_single_candidate(item) for item in candidate_items]))
        finally:
            executor.shutdown(wait=False)

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


def _drop_expired_eval_jobs() -> None:
    """Removes finished background jobs older than EVAL_JOB_TTL_SECONDS from memory."""
    now = time.time()
    expired = [
        job_id for job_id, job in state.eval_jobs.items()
        if job["finished_at"] is not None and now - job["finished_at"] > EVAL_JOB_TTL_SECONDS
    ]
    for job_id in expired:
        del state.eval_jobs[job_id]


async def _run_eval_job(job: dict, payload: EvaluationBatchRequest) -> None:
    """Background task body: runs the batch and records progress, results or error on the job."""
    def _on_progress(completed: int, total: int) -> None:
        job["completed"] = completed
        job["total"] = total

    try:
        job["result"] = await _run_batch_evaluation(payload, on_progress=_on_progress)
        job["state"] = "done"
    except HTTPException as http_err:
        job["error"] = str(http_err.detail)
        job["state"] = "failed"
    except Exception as unexpected_err:
        traceback.print_exc()
        job["error"] = f"Evaluation failed: {str(unexpected_err)}"
        job["state"] = "failed"
    finally:
        job["finished_at"] = time.time()
        job.pop("task", None)


@router.post("/evaluate_batch/jobs")
async def start_evaluation_job(payload: EvaluationBatchRequest):
    """Starts a batch evaluation as a background job and returns its id immediately."""
    if not payload.resume_filenames:
        raise HTTPException(status_code=400, detail="No resume filenames selected for evaluation.")
    if not state.evaluator:
        raise HTTPException(status_code=500, detail="Resume Evaluator model is not initialized on the server.")

    _drop_expired_eval_jobs()
    job_id = uuid.uuid4().hex
    job = {
        "state": "running",
        "total": len(payload.resume_filenames),
        "completed": 0,
        "started_at": time.time(),
        "finished_at": None,
        "result": None,
        "error": None
    }
    state.eval_jobs[job_id] = job
    # Keep a reference to the task so it isn't garbage-collected while running.
    job["task"] = asyncio.create_task(_run_eval_job(job, payload))
    return {"job_id": job_id}


@router.get("/evaluate_batch/jobs/{job_id}")
def get_evaluation_job(job_id: str):
    """Reports a background batch job's state, progress, elapsed time and final results or error."""
    _drop_expired_eval_jobs()
    job = state.eval_jobs.get(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Evaluation job not found.")
    end_time = job["finished_at"] or time.time()
    return {
        "job_id": job_id,
        "state": job["state"],
        "total": job["total"],
        "completed": job["completed"],
        "elapsed_seconds": round(end_time - job["started_at"], 2),
        "result": job["result"] if job["state"] == "done" else None,
        "error": job["error"] if job["state"] == "failed" else None
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
