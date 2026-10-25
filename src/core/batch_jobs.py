"""
Batch jobs on the website: one extraction or evaluation job processing a Batch of resumes together, in parallel.

Jobs live in memory only, so a server restart loses them and the uploaded PDFs they hold. Only one Batch runs at a
time: both kinds share the vLLM request slots, so two at once would slow each other and spoil both time estimates.
Every item ends done, failed or cancelled, and a failed item never stops the rest of its Batch.
"""
import os
import sys
import time
import uuid
import shutil
import asyncio
import traceback
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Callable, Dict, List, Optional, Tuple

from src.core.config import BATCH_JOB_TTL_SECONDS
from src.core.durations import record_duration
from src.core.state import state

EXTRACT_KIND = "extract"
EVALUATE_KIND = "evaluate"

# The duration kind a finished Batch records its seconds per item under, beside each kind's single-item duration
BATCH_ITEM_DURATION_KINDS = {EXTRACT_KIND: "extract_batch_item", EVALUATE_KIND: "evaluate_batch_item"}

ITEM_STATES = ("waiting", "running", "done", "failed", "cancelled")

# What one item's work returns: its result (or None) and, when it failed, why
ItemOutcome = Tuple[Optional[Any], Optional[str]]


class BatchBusyError(Exception):
    """Raised when a Batch is started while another one is still running."""
    def __init__(self, running: Dict[str, Any]):
        super().__init__("Another Batch is running.")
        self.job_id = running["id"]
        self.kind = running["kind"]


def _new_item(name: str) -> Dict[str, Any]:
    return {"name": name, "state": "waiting", "seconds": None, "result": None, "error": None}


def _new_job(kind: str, item_names: List[str], files_dir: Optional[str], item_results_in_status: bool) -> Dict[str, Any]:
    return {
        "id": uuid.uuid4().hex,
        "kind": kind,
        "state": "running",
        "items": [_new_item(name) for name in item_names],
        "started_at": time.time(),
        "items_started_at": None,
        "finished_at": None,
        "cancel_requested": False,
        "result": None,
        "error": None,
        # Uploaded PDFs of a batch extraction, kept until the job expires so failed items can be retried
        "files_dir": files_dir,
        # Extraction item results are small summaries; evaluation item results are whole reports, sent once at the end
        "item_results_in_status": item_results_in_status
    }


def _remove_files(job: Dict[str, Any]) -> None:
    files_dir = job.get("files_dir")
    if files_dir and os.path.isdir(files_dir):
        shutil.rmtree(files_dir, ignore_errors=True)


def drop_expired_jobs() -> None:
    """Removes finished jobs older than BATCH_JOB_TTL_SECONDS, with their uploaded PDFs."""
    now = time.time()
    for job_id, job in list(state.batch_jobs.items()):
        if job["finished_at"] is not None and now - job["finished_at"] > BATCH_JOB_TTL_SECONDS:
            del state.batch_jobs[job_id]
            _remove_files(job)


def running_job() -> Optional[Dict[str, Any]]:
    return next((job for job in state.batch_jobs.values() if job["state"] == "running"), None)


def create_job(
    kind: str,
    item_names: List[str],
    files_dir: Optional[str] = None,
    item_results_in_status: bool = False
) -> Dict[str, Any]:
    """Registers a new running Batch job, or raises BatchBusyError while another one runs."""
    drop_expired_jobs()
    running = running_job()
    if running:
        raise BatchBusyError(running)
    job = _new_job(kind, item_names, files_dir, item_results_in_status)
    state.batch_jobs[job["id"]] = job
    return job


def detached_job(kind: str) -> Dict[str, Any]:
    """A job that is never registered, for a caller that waits on the whole Batch itself."""
    return _new_job(kind, [], None, False)


def get_job(job_id: str) -> Optional[Dict[str, Any]]:
    drop_expired_jobs()
    return state.batch_jobs.get(job_id)


def discard_job(job: Dict[str, Any]) -> None:
    """Forgets a job that never started its items, e.g. when its upload was refused, with its uploaded PDFs."""
    state.batch_jobs.pop(job["id"], None)
    _remove_files(job)


def set_items(job: Dict[str, Any], item_names: List[str]) -> None:
    """Replaces the job's items, for a job whose item list is only known once its work has begun."""
    job["items"] = [_new_item(name) for name in item_names]


def request_cancel(job: Dict[str, Any]) -> None:
    """Items not started yet are cancelled and never start; running items finish and keep their results."""
    if job["state"] == "running":
        job["cancel_requested"] = True


async def run_items(
    job: Dict[str, Any],
    process_item: Callable[[Dict[str, Any]], ItemOutcome],
    max_in_flight: int
) -> None:
    """
    Runs process_item on every item in worker threads, at most max_in_flight at once, starting them in item order.
    An exception from process_item fails only that item.
    """
    items = job["items"]
    if not items:
        return

    def _run(item: Dict[str, Any]) -> None:
        if job["cancel_requested"]:
            item["state"] = "cancelled"
            return
        item["state"] = "running"
        start = time.time()
        try:
            result, error = process_item(item)
        except Exception as e:
            print(f"[Batch] Item '{item['name']}' failed: {e}\n{traceback.format_exc()}", file=sys.stderr)
            result, error = None, str(e)
        item["seconds"] = round(time.time() - start, 2)
        item["result"] = result
        item["error"] = error
        item["state"] = "failed" if error else "done"

    loop = asyncio.get_running_loop()
    executor = ThreadPoolExecutor(
        max_workers=max(1, min(max_in_flight, len(items))),
        thread_name_prefix=f"batch-{job['kind']}"
    )
    job["items_started_at"] = time.time()
    try:
        await asyncio.gather(*[loop.run_in_executor(executor, _run, item) for item in items])
    finally:
        executor.shutdown(wait=False)


def finish_job(job: Dict[str, Any], result: Any = None, error: Optional[str] = None) -> None:
    """
    Ends the job as failed (the Batch itself could not run), cancelled or done. A Batch that ran to the end records
    its seconds per item, for the next Batch's estimate before its first item finishes. A Batch of one is left out:
    its time is one item's whole duration, not a share of the slots.
    """
    job["finished_at"] = time.time()
    job["result"] = result
    if error is not None:
        job["error"] = error
        job["state"] = "failed"
    elif job["cancel_requested"]:
        job["state"] = "cancelled"
    else:
        job["state"] = "done"
        finished = sum(1 for item in job["items"] if item["state"] in ("done", "failed"))
        if finished >= 2 and job["items_started_at"]:
            record_duration(BATCH_ITEM_DURATION_KINDS[job["kind"]], (job["finished_at"] - job["items_started_at"]) / finished)


def item_counts(job: Dict[str, Any]) -> Dict[str, int]:
    counts = {name: 0 for name in ITEM_STATES}
    for item in job["items"]:
        counts[item["state"]] += 1
    return counts


def job_status(job: Dict[str, Any]) -> Dict[str, Any]:
    """The job as the page polls it: state, per-state counts, every item's state and, once finished, its result."""
    end_time = job["finished_at"] or time.time()
    finished = job["state"] != "running"
    items = []
    for item in job["items"]:
        entry = {"name": item["name"], "state": item["state"], "seconds": item["seconds"], "error": item["error"]}
        if job["item_results_in_status"]:
            entry["result"] = item["result"]
        items.append(entry)
    return {
        "job_id": job["id"],
        "kind": job["kind"],
        "state": job["state"],
        "total": len(job["items"]),
        "counts": item_counts(job),
        "items": items,
        "elapsed_seconds": round(end_time - job["started_at"], 2),
        "result": job["result"] if finished else None,
        "error": job["error"]
    }
