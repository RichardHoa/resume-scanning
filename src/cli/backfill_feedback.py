"""
CLI Entrypoint for backfilling Candidate Feedback into a directory of existing evaluation reports.

Runs the Review Panel only where feedback is missing, skipped or failed. Scores are never re-computed or
changed: the requirement text and the resume path come from each report, and only `candidate_feedback` is
written back. Failed Evaluations are left untouched and listed at the end for a full re-evaluation.
"""
import os
import sys

# Ensure repository root is in sys.path for 'src' package imports
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import argparse
import json
import time
from concurrent.futures import ThreadPoolExecutor

from src.core.config import DEFAULT_LLM_MODEL, DEFAULT_VLLM_URL, VLLM_MAX_CONCURRENT_REQUESTS
from src.pipelines.review_panel import create_review_panel


def parse_args():
    parser = argparse.ArgumentParser(description="Backfill Candidate Feedback into existing evaluation reports")
    parser.add_argument("--dir", type=str, required=True, help="Directory of evaluation report JSON files")
    parser.add_argument("--model-name", type=str, default=DEFAULT_LLM_MODEL, help="Model served by the vLLM server")
    parser.add_argument("--vllm-url", type=str, default=DEFAULT_VLLM_URL, help="Base URL of the vLLM OpenAI-compatible server")
    parser.add_argument("--mock", action="store_true", help="Write canned Candidate Feedback without contacting vLLM")
    parser.add_argument("--language", type=str, default="vietnamese", choices=["vietnamese", "english"], help="Feedback language for reports that don't record their evaluation language")
    parser.add_argument("--workers", type=int, default=VLLM_MAX_CONCURRENT_REQUESTS, help="Max reports reviewed at once (default: the vLLM request limit, which does the throttling)")
    return parser.parse_args()


def _write_report(path: str, report: dict) -> None:
    """Writes the report through a temp file, so an interrupted job never leaves a half-written report."""
    tmp_path = f"{path}.tmp"
    with open(tmp_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    os.replace(tmp_path, path)


def main():
    args = parse_args()
    if not os.path.isdir(args.dir):
        print(f"Error: Directory not found: {args.dir}", file=sys.stderr)
        sys.exit(1)

    failed_evaluations = []   # status "error": need a full re-evaluation
    unusable = []             # (filename, reason): can't be reviewed from the report alone
    already_done = 0
    to_review = []            # (path, report, resume)

    for fname in sorted(os.listdir(args.dir)):
        if not fname.lower().endswith(".json"):
            continue
        path = os.path.join(args.dir, fname)
        try:
            with open(path, "r", encoding="utf-8") as f:
                report = json.load(f)
        except Exception as e:
            unusable.append((fname, f"unreadable JSON: {e}"))
            continue
        if not isinstance(report, dict) or "dimension_scores" not in report:
            continue

        if report.get("status") == "error":
            failed_evaluations.append(fname)
            continue
        # A Scanned Resume was never evaluated and gets no Candidate Feedback
        if report.get("status") == "scanned":
            continue
        feedback = report.get("candidate_feedback")
        if isinstance(feedback, dict) and feedback.get("status") == "ok":
            already_done += 1
            continue

        # Reports written before requirements and resume paths were stored can't be paired safely
        if report.get("status") != "ok":
            unusable.append((fname, "no status field (written before Failed Evaluations were recorded); re-evaluate"))
            continue
        if "standard_requirements" not in report or "hidden_requirements" not in report:
            unusable.append((fname, "no requirement text in the report; re-evaluate"))
            continue
        resume_path = report.get("resume_path")
        if not resume_path or not os.path.isfile(resume_path):
            unusable.append((fname, f"extracted resume not found at {resume_path!r}"))
            continue
        try:
            with open(resume_path, "r", encoding="utf-8") as f:
                resume = json.load(f)
        except Exception as e:
            unusable.append((fname, f"unreadable resume {resume_path}: {e}"))
            continue
        to_review.append((path, report, resume if isinstance(resume, dict) else {}))

    print(
        f"[Feedback Backfill] {len(to_review)} report(s) to review, {already_done} already have feedback, "
        f"{len(failed_evaluations)} Failed Evaluation(s) skipped, {len(unusable)} unusable.",
        file=sys.stderr
    )

    results = {"ok": 0, "failed": 0}
    if to_review:
        panel = create_review_panel(args.mock, args.vllm_url, args.model_name)

        def _review(item):
            path, report, resume = item
            resume_name = report.get("resume_name") or os.path.splitext(os.path.basename(path))[0]
            # Reports older than Criterion Importance have no Missing Must-Haves; the panel reads that as none
            panel_report = {**report, "missing_must_haves": report.get("missing_must_haves") or []}
            feedback = panel.review(
                panel_report, resume, report["standard_requirements"], report["hidden_requirements"],
                language=report.get("language") or args.language, resume_name=resume_name
            )
            # Only candidate_feedback changes; every score stays exactly as the evaluator wrote it
            report["candidate_feedback"] = feedback
            try:
                _write_report(path, report)
            except Exception as e:
                print(f"  [failed] {os.path.basename(path)}: could not write the report: {e}", file=sys.stderr)
                return "failed"
            print(f"  [{feedback['status']}] {os.path.basename(path)}", file=sys.stderr)
            return feedback["status"]

        start = time.time()
        with ThreadPoolExecutor(max_workers=max(1, min(args.workers, len(to_review)))) as executor:
            for status in executor.map(_review, to_review):
                results[status] = results.get(status, 0) + 1
        print(f"[Feedback Backfill] Reviewed {len(to_review)} report(s) in {time.time() - start:.2f}s. Prompt logs: {log_root}", file=sys.stderr)

    print("\n================================================================================")
    print(f"Candidate Feedback backfill: {results['ok']} ok, {results['failed']} failed, {already_done} already had feedback")
    if results["failed"]:
        print("Rerun this script to retry the failed feedback.")
    if unusable:
        print(f"\n{len(unusable)} report(s) could not be reviewed:")
        for fname, reason in unusable:
            print(f"  - {fname}: {reason}")
    if failed_evaluations:
        print(f"\n{len(failed_evaluations)} Failed Evaluation(s) need re-evaluation (no feedback generated):")
        for fname in failed_evaluations:
            print(f"  - {fname}")
    else:
        print("\nNo Failed Evaluations.")
    print("================================================================================")


if __name__ == "__main__":
    main()
