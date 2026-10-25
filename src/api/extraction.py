"""
Resume Upload & Batch Extraction FastAPI Router
"""
import os
import sys
import json
import time
import shutil
import asyncio
from typing import List
from fastapi import APIRouter, UploadFile, File, Form, HTTPException

from src.api.batch import busy_response
from src.core.batch_jobs import (
    EXTRACT_KIND, BatchBusyError, ItemOutcome, create_job, discard_job, finish_job, get_job, run_items, set_items
)
from src.core.config import EXTRACTION_JSON_DIR, RESUME_JSON_DIRS, VLLM_MAX_CONCURRENT_REQUESTS, BATCH_MAX_PDF_BYTES
from src.core.state import state
from src.core.durations import record_duration
from src.core.resume_pdfs import store_resume_pdf
from src.core.run_files import base_name, clear_resume
from src.core.evaluation_order import load_evaluation_order, get_candidate_tier
from src.pipelines.evaluator_utils import is_missing_position, is_scanned_resume
from src.pipelines.extractor import FIDELITY_WARNING_PREFIX, REPAIRED_EXTRACTION_WARNING

router = APIRouter(prefix="/api", tags=["extraction"])


def _extraction_summary(data: dict) -> dict:
    """What the batch results table shows for one extracted resume: its outcome and its Missing Position flag."""
    warnings = [w for w in (data.get("warning") or []) if isinstance(w, str)]
    if is_scanned_resume(data):
        outcome = "scanned"
    elif REPAIRED_EXTRACTION_WARNING in warnings:
        outcome = "repaired"
    elif any(w.startswith(FIDELITY_WARNING_PREFIX) for w in warnings):
        outcome = "fidelity_warnings"
    else:
        outcome = "extracted"
    return {"outcome": outcome, "missing_position": is_missing_position(data)}


def _extract_one(pdf_path: str, language: str) -> ItemOutcome:
    """
    Extracts one uploaded PDF of a Batch into the web run folder. A Scanned Resume is kept, so it still reaches the
    results list marked as scanned. The uploaded PDF is removed once stored; a failed one stays for a retry.
    """
    safe_filename = os.path.basename(pdf_path)
    resume_name = os.path.splitext(safe_filename)[0]
    print(f"Processing extraction of {safe_filename} (language: {language})...", file=sys.stderr)

    # Extracting a resume again starts it over: its old extraction, evaluation and every log go first
    clear_resume(safe_filename)
    start_time = time.time()
    formatted_json_str = state.extractor.extract(pdf_path, language=language)
    elapsed_time = time.time() - start_time
    try:
        extracted_data = json.loads(formatted_json_str)
    except json.JSONDecodeError:
        return None, "Failed to parse model output as JSON"
    if not isinstance(extracted_data, dict):
        return None, "The model output is not a JSON object"

    scanned = is_scanned_resume(extracted_data)
    if "error" in extracted_data and not scanned:
        return None, str(extracted_data["error"])

    os.makedirs(EXTRACTION_JSON_DIR, exist_ok=True)
    with open(os.path.join(EXTRACTION_JSON_DIR, f"{resume_name}.json"), "w", encoding="utf-8") as f:
        json.dump(extracted_data, f, ensure_ascii=False, indent=2)
    store_resume_pdf(pdf_path, resume_name)
    if not scanned:
        record_duration("extract", elapsed_time)
    try:
        os.remove(pdf_path)
    except OSError as cleanup_err:
        print(f"Warning: Failed to delete uploaded file {pdf_path}: {cleanup_err}", file=sys.stderr)
    return _extraction_summary(extracted_data), None


def _start_extraction_job(job: dict, language: str) -> None:
    """Runs a registered extraction job's items in the background, up to the vLLM request limit at once."""
    # Kept for a retry of this job's failed items
    job["language"] = language
    async def _run() -> None:
        try:
            # One extraction is one request (plus retries), so the request limit is the only cap needed
            await run_items(
                job,
                lambda item: _extract_one(os.path.join(job["files_dir"], item["name"]), language),
                VLLM_MAX_CONCURRENT_REQUESTS
            )
            finish_job(job)
        except Exception as e:
            print(f"Batch extraction failed: {e}", file=sys.stderr)
            finish_job(job, error=f"Trích xuất hàng loạt thất bại: {e}")
        finally:
            job.pop("task", None)

    # Keep a reference to the task so it isn't garbage-collected while running
    job["task"] = asyncio.create_task(_run())


@router.post("/extract/jobs")
async def start_extraction_job(files: List[UploadFile] = File(...), language: str = Form("vietnamese")):
    """
    Starts a batch extraction of the uploaded PDFs as a background job and returns its id. Files are known by their
    base name, so two with the same name refuse the Batch. Non-PDF and oversized files are skipped and listed.
    """
    if not state.extractor:
        raise HTTPException(status_code=500, detail="Resume Extractor model is not initialized on the server.")
    names = [os.path.basename(f.filename or "") for f in files]
    duplicates = sorted({n for n in names if n and names.count(n) > 1})
    if duplicates:
        raise HTTPException(status_code=400, detail=f"Các tệp trùng tên trong lô: {', '.join(duplicates)}. Hãy đổi tên rồi tải lên lại.")
    try:
        # Registered before the files are saved, so a second Batch is refused from here on
        job = create_job(EXTRACT_KIND, [], files_dir=None, item_results_in_status=True)
    except BatchBusyError as busy:
        return busy_response(busy)

    files_dir = os.path.join(state.temp_dir, f"batch-{job['id']}")
    job["files_dir"] = files_dir
    skipped = []
    item_names = []
    try:
        os.makedirs(files_dir, exist_ok=True)
        for upload, name in zip(files, names):
            if not name.lower().endswith(".pdf"):
                skipped.append({"name": name, "reason": "not_pdf"})
                continue
            content = await upload.read()
            if len(content) > BATCH_MAX_PDF_BYTES:
                skipped.append({"name": name, "reason": "too_large"})
                continue
            with open(os.path.join(files_dir, name), "wb") as buffer:
                buffer.write(content)
            item_names.append(name)
    except Exception as e:
        discard_job(job)
        raise HTTPException(status_code=500, detail=f"Không lưu được tệp tải lên: {e}")
    if not item_names:
        discard_job(job)
        raise HTTPException(status_code=400, detail="Lô không có tệp PDF hợp lệ nào để trích xuất.")

    set_items(job, item_names)
    _start_extraction_job(job, language)
    return {"job_id": job["id"], "skipped": skipped}


@router.post("/extract/jobs/{job_id}/retry")
async def retry_extraction_job(job_id: str):
    """
    Starts a new Batch rerunning a finished extraction job's failed and cancelled items, from the PDFs it still
    holds, so nothing is uploaded again. The PDFs move to the new job, which keeps them until it expires.
    """
    old_job = get_job(job_id)
    if not old_job or old_job["kind"] != EXTRACT_KIND or not old_job["files_dir"]:
        raise HTTPException(status_code=404, detail="Lô cũ đã hết hạn. Vui lòng tải các tệp lên lại.")
    if old_job["state"] == "running":
        raise HTTPException(status_code=400, detail="Lô này vẫn đang chạy.")
    names = [
        item["name"] for item in old_job["items"]
        if item["state"] in ("failed", "cancelled") and os.path.isfile(os.path.join(old_job["files_dir"], item["name"]))
    ]
    if not names:
        raise HTTPException(status_code=400, detail="Không còn CV lỗi nào để thử lại.")
    try:
        job = create_job(EXTRACT_KIND, names, files_dir=None, item_results_in_status=True)
    except BatchBusyError as busy:
        return busy_response(busy)

    job["files_dir"] = os.path.join(state.temp_dir, f"batch-{job['id']}")
    os.makedirs(job["files_dir"], exist_ok=True)
    for name in names:
        shutil.move(os.path.join(old_job["files_dir"], name), os.path.join(job["files_dir"], name))
    _start_extraction_job(job, old_job.get("language") or "vietnamese")
    return {"job_id": job["id"], "skipped": []}


@router.get("/extractions/{name}")
def get_extraction(name: str):
    """
    One resume's extraction JSON as the website made it, for the batch results table. Only the web run folder is
    read: HR's ground truth for the same name would hide the extraction just made.
    """
    fpath = os.path.join(EXTRACTION_JSON_DIR, base_name(name) + ".json")
    if not os.path.isfile(fpath):
        raise HTTPException(status_code=404, detail="Không tìm thấy kết quả trích xuất của CV này.")
    try:
        with open(fpath, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to read extraction file: {e}")


@router.get("/scanned_resumes")
def get_scanned_resumes():
    """Lists all scanned/extracted JSON resumes in approved_jsons and the run folders read, sorted by secret evaluation_order."""
    order_data = load_evaluation_order()
    resumes = []
    seen_names = set()

    for sdir in RESUME_JSON_DIRS:
        if not os.path.exists(sdir):
            continue
        for fname in sorted(os.listdir(sdir)):
            if fname.endswith(".json") and fname not in seen_names:
                seen_names.add(fname)
                fpath = os.path.join(sdir, fname)
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    
                    pos_info = data.get("position_applied", {}) if isinstance(data, dict) else {}
                    skills = data.get("skills", []) if isinstance(data, dict) else []
                    
                    tier_info = get_candidate_tier(data, fname, order_data)
                    
                    resumes.append({
                        "filename": fname,
                        "path": fpath,
                        "title": pos_info.get("title", "N/A"),
                        "missing_position": is_missing_position(data),
                        "scanned_resume": is_scanned_resume(data),
                        "level": pos_info.get("level", "unknown"),
                        "email": tier_info["resolved_email"],
                        "skills_count": len(skills),
                        "skills_preview": skills[:5],
                        "tier": tier_info["tier"],
                        "tier_name": tier_info["tier_name"],
                        "tier_order": tier_info["tier_order"]
                    })
                except Exception as e:
                    print(f"Warning: Failed to load {fpath}: {e}", file=sys.stderr)

    # Sort resumes by Evaluation Order: Tier 1 (exact order) -> Tier 2 (exact order) -> Tier 3
    resumes.sort(key=lambda r: (r["tier"], r["tier_order"], r["filename"]))
    return {
        "resumes": resumes,
        "evaluation_order_active": order_data["file_found"],
        "evaluation_order_path": order_data["file_path"],
        "tech_mode": order_data["tech_mode"],
        "tier1_count": len(order_data["tier1"]),
        "tier2_count": len(order_data["tier2"])
    }
