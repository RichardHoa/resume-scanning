"""
Batch Job FastAPI Router: the status and cancelling shared by batch extraction and batch evaluation jobs
"""
from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from src.core.batch_jobs import BatchBusyError, get_job, job_status, request_cancel

router = APIRouter(prefix="/api", tags=["batch"])


def busy_response(err: BatchBusyError) -> JSONResponse:
    """The refusal of a second Batch, naming the running one so the page can reconnect to it."""
    return JSONResponse(
        status_code=409,
        content={"detail": "Đang có một lô khác chạy.", "running_job_id": err.job_id, "running_kind": err.kind}
    )


@router.get("/batch_jobs/{job_id}")
def get_batch_job(job_id: str):
    """Reports a Batch job's state, per-state counts, every item's state and, once finished, its result or error."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Không tìm thấy lô này (có thể đã hết hạn).")
    return job_status(job)


@router.post("/batch_jobs/{job_id}/cancel")
def cancel_batch_job(job_id: str):
    """Stops a running Batch: items not started are cancelled, running items finish and are kept."""
    job = get_job(job_id)
    if not job:
        raise HTTPException(status_code=404, detail="Không tìm thấy lô này (có thể đã hết hạn).")
    request_cancel(job)
    return job_status(job)
