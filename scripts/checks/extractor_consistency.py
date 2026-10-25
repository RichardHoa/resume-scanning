#!/usr/bin/env python3
"""
Extractor Consistency Check — extracts every resume of one resume set 5 times and reports what changes between
the runs, and every Fidelity Warning and failed run (.scratch/extractor-consistency/spec.md).

Run once per resume set with RUN_DIR set to its consistency run folder (scripts/checks/extractor_consistency.sh
does both sets). Writes extraction_json/<resume>/run-<n>.json and consistency_report.md / .json to the run folder.
"""
import os
import sys
import json
import re
import argparse
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED

# Ensure repository root is in sys.path for 'src' package imports and set CWD
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
os.chdir(_PROJECT_ROOT)

from src.core.config import DEFAULT_LLM_MODEL, DEFAULT_VLLM_URL, RUN_DIR, EXTRACTION_JSON_DIR, PROMPT_LOGS_DIR
from src.core.reference_date import set_reference_date
from src.pipelines.extractor import (
    ResumeExtractor, find_textless_pages, FIDELITY_WARNING_PREFIX, REPAIRED_EXTRACTION_WARNING
)
from src.pipelines.evaluator_utils import SCANNED_RESUME_KEY

RUNS_PER_RESUME = 5
MISSING = "(missing)"


def parse_args():
    parser = argparse.ArgumentParser(description="Extractor Consistency Check: every resume extracted 5 times")
    parser.add_argument("--dir", type=str, required=True, help="Directory of the resume set's PDF resumes")
    parser.add_argument("--set-name", type=str, required=True, help="Resume set name shown in the report (CnB, Tech)")
    parser.add_argument("--model-name", type=str, default=DEFAULT_LLM_MODEL, help="Model name served by the vLLM server")
    parser.add_argument("--vllm-url", type=str, default=DEFAULT_VLLM_URL, help="vLLM server URL")
    parser.add_argument("--workers", type=int, default=6, help="Extractions running at once")
    parser.add_argument("--reference-date", type=str, default="",
                        help="Date (YYYY-MM-DD) the prompts treat as today, for old resume sets (default: the real date)")
    parser.add_argument("--combined", action="store_true",
                        help="Combined Extraction: also show the model the page images (needs a vision model)")
    return parser.parse_args()


def is_scanned_pdf(pdf_path: str) -> bool:
    """A Scanned Resume: no page has text. An unreadable PDF is left to the extraction runs to report as failed."""
    try:
        textless, page_count = find_textless_pages(pdf_path)
    except Exception:
        return False
    return len(textless) == page_count


def run_extraction(extractor: ResumeExtractor, pdf_path: str, out_dir: str, run: int) -> dict:
    """
    One extraction run, saved to out_dir, its prompt logs under prompt_logs/run-<n>/ so the runs never overwrite
    each other's. Returns {"run", "data"} or {"run", "error"} for a failed run; "raised" marks a run whose request
    failed (server down, timeout, or rejected, e.g. a prompt over the context length), which says nothing about the
    model's answers.
    """
    try:
        text = extractor.extract(pdf_path, log_dir=os.path.join(PROMPT_LOGS_DIR, f"run-{run}"))
    except Exception as e:
        return {"run": run, "error": f"extraction raised: {e}", "raised": True}
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        with open(os.path.join(out_dir, f"run-{run}.txt"), "w", encoding="utf-8") as f:
            f.write(text or "")
        return {"run": run, "error": "invalid JSON after all retries"}

    with open(os.path.join(out_dir, f"run-{run}.json"), "w", encoding="utf-8") as f:
        f.write(text)
    error = extraction_error(data)
    return {"run": run, "error": error} if error else {"run": run, "data": data}


def extraction_error(data) -> str | None:
    """Why a parsed extraction cannot be used, or None when it can."""
    if not isinstance(data, dict):
        return "extraction is not a JSON object"
    if data.get(SCANNED_RESUME_KEY):
        return "rejected as a Scanned Resume"
    if "error" in data:
        return str(data["error"])
    # A Repaired Extraction is cut off: using it would only show the fields it lost
    if REPAIRED_EXTRACTION_WARNING in (data.get("warning") or []):
        return "invalid JSON after all retries; the last answer was patched (Repaired Extraction)"
    return None


def leaf_values(obj, path: str = "", out: dict = None) -> dict:
    """Every leaf of an extraction by path, strings trimmed with inner whitespace collapsed; the "warning" field is left out."""
    if out is None:
        out = {}
    if isinstance(obj, dict):
        if not obj:
            out[path] = "{}"
        for key, val in obj.items():
            if not path and key == "warning":
                continue
            leaf_values(val, f"{path}.{key}" if path else key, out)
    elif isinstance(obj, list):
        if not obj:
            out[path] = "[]"
        for idx, item in enumerate(obj):
            leaf_values(item, f"{path}[{idx}]", out)
    elif isinstance(obj, str):
        out[path] = json.dumps(" ".join(obj.split()), ensure_ascii=False)
    else:
        out[path] = json.dumps(obj, ensure_ascii=False)
    return out


def field_shape(path: str) -> str:
    """A path with its list positions replaced, so work_experience[0].end_date and [3] count as one field."""
    return re.sub(r"\[\d+\]", "[*]", path)


def runs_by_value(values_per_run: dict) -> list[dict]:
    """{run: value} grouped into distinct values with their runs, the most common value first."""
    groups = {}
    for run, value in sorted(values_per_run.items()):
        groups.setdefault(value, []).append(run)
    ordered = sorted(groups.items(), key=lambda item: (-len(item[1]), item[1][0]))
    return [{"value": value, "runs": runs} for value, runs in ordered]


def compare_resume(name: str, results: list[dict]) -> dict:
    """The comparison of one resume's runs: field differences, Fidelity Warnings, PDF Notes and failed runs."""
    ok = [r for r in results if "data" in r]
    failed = [{"run": r["run"], "error": r["error"]} for r in results if "error" in r]

    leaves = {r["run"]: leaf_values(r["data"]) for r in ok}
    paths = []
    for run in sorted(leaves):
        paths.extend(p for p in leaves[run] if p not in paths)

    differences = []
    if len(ok) > 1:
        for path in paths:
            per_run = {run: leaves[run].get(path, MISSING) for run in leaves}
            if len(set(per_run.values())) > 1:
                differences.append({"path": path, "values": runs_by_value(per_run)})

    fidelity, pdf_notes = {}, []
    for r in ok:
        warnings = r["data"].get("warning") or []
        for msg in warnings if isinstance(warnings, list) else [warnings]:
            msg = " ".join(str(msg).split())
            if msg.startswith(FIDELITY_WARNING_PREFIX):
                fidelity.setdefault(msg, []).append(r["run"])
            elif msg not in pdf_notes:
                pdf_notes.append(msg)

    return {
        "resume": name,
        "ok_runs": sorted(leaves),
        "failed_runs": failed,
        "differences": differences,
        "fidelity_warnings": [{"message": m, "runs": runs} for m, runs in fidelity.items()],
        "pdf_notes": pdf_notes,
    }


def build_report(set_name: str, mode: str, reference_date: str, resumes: list[dict], scanned: list[str]) -> dict:
    resumes = sorted(resumes, key=lambda c: (
        not (c["differences"] or c["fidelity_warnings"] or c["failed_runs"]),
        -len(c["differences"]), -len(c["fidelity_warnings"]), -len(c["failed_runs"]), c["resume"],
    ))
    shapes = Counter()
    for c in resumes:
        shapes.update({field_shape(d["path"]) for d in c["differences"]})
    return {
        "resume_set": set_name,
        "mode": mode,
        "reference_date": reference_date or "today",
        "runs_per_resume": RUNS_PER_RESUME,
        "counts": {
            "resumes": len(resumes),
            "identical": sum(1 for c in resumes if not c["differences"] and not c["failed_runs"]),
            "with_differences": sum(1 for c in resumes if c["differences"]),
            "with_errors": sum(1 for c in resumes if c["fidelity_warnings"]),
            "with_failed_run": sum(1 for c in resumes if c["failed_runs"]),
            "scanned_skipped": len(scanned),
        },
        "scanned_resumes": scanned,
        "unstable_fields": [{"field": f, "resumes": n} for f, n in shapes.most_common()],
        "resumes": resumes,
    }


def _runs(runs: list[int]) -> str:
    return ("run " if len(runs) == 1 else "runs ") + ", ".join(str(r) for r in runs)


def render_markdown(report: dict) -> str:
    counts = report["counts"]
    lines = [
        f"# Extractor consistency: {report['resume_set']}",
        "",
        f"{report['mode']}, {report['runs_per_resume']} runs per resume, Reference Date {report['reference_date']}.",
        "",
        "## Summary",
        "",
        f"- Resumes compared: {counts['resumes']}",
        f"- Identical across all runs: {counts['identical']}",
        f"- With field differences: {counts['with_differences']}",
        f"- With errors (Fidelity Warnings): {counts['with_errors']}",
        f"- With a failed run: {counts['with_failed_run']}",
        f"- Scanned Resumes skipped: {counts['scanned_skipped']}"
        + (f" ({', '.join(report['scanned_resumes'])})" if report["scanned_resumes"] else ""),
        "",
    ]
    if report["unstable_fields"]:
        lines += ["### Most unstable fields", "", "| Field | Resumes where it differs |", "|---|---|"]
        lines += [f"| `{u['field']}` | {u['resumes']} |" for u in report["unstable_fields"]]
        lines.append("")

    lines += ["## Resumes", ""]
    for c in report["resumes"]:
        flags = []
        if c["differences"]:
            flags.append(f"{len(c['differences'])} differing field(s)")
        if c["fidelity_warnings"]:
            flags.append(f"{len(c['fidelity_warnings'])} error(s)")
        if c["failed_runs"]:
            flags.append(f"{len(c['failed_runs'])} failed run(s)")
        lines += [f"### {c['resume']} — {', '.join(flags) or 'identical'}", ""]

        if c["differences"]:
            lines += ["**Field differences**", ""]
            for d in c["differences"]:
                lines.append(f"- `{d['path']}`")
                lines += [f"  - {v['value']} — {_runs(v['runs'])}" for v in d["values"]]
            lines.append("")
        if c["fidelity_warnings"] or c["failed_runs"]:
            lines += ["**Errors**", ""]
            lines += [f"- {w['message']} — {_runs(w['runs'])}" for w in c["fidelity_warnings"]]
            lines += [f"- Run {f['run']} failed: {f['error']}" for f in c["failed_runs"]]
            lines.append("")
        if c["pdf_notes"]:
            lines += [f"PDF Notes: {' '.join(c['pdf_notes'])}", ""]
    return "\n".join(lines)


def main():
    args = parse_args()
    set_reference_date(args.reference_date)

    if not os.path.isdir(args.dir):
        print(f"[Error] Directory not found: {args.dir}", file=sys.stderr)
        sys.exit(1)
    pdf_files = sorted(f for f in os.listdir(args.dir) if f.lower().endswith(".pdf"))
    if not pdf_files:
        print(f"[Error] No PDF resumes found in {args.dir}", file=sys.stderr)
        sys.exit(1)

    scanned, to_extract = [], []
    for fname in pdf_files:
        name = os.path.splitext(fname)[0]
        if is_scanned_pdf(os.path.join(args.dir, fname)):
            print(f"Skipping {fname}: Scanned Resume", file=sys.stderr)
            scanned.append(name)
        else:
            to_extract.append((name, os.path.join(args.dir, fname)))

    extractor = ResumeExtractor(model_name=args.model_name, vllm_url=args.vllm_url, combined=args.combined)
    extractor.load_model()

    for name, _ in to_extract:
        os.makedirs(os.path.join(EXTRACTION_JSON_DIR, name), exist_ok=True)
    total = len(to_extract) * RUNS_PER_RESUME
    print(f"[{args.set_name}] {len(to_extract)} resumes x {RUNS_PER_RESUME} runs = {total} extractions.", file=sys.stderr)

    results = {name: [] for name, _ in to_extract}
    done = 0
    start = time.time()

    def _submit(executor, name, pdf_path, run):
        return executor.submit(run_extraction, extractor, pdf_path, os.path.join(EXTRACTION_JSON_DIR, name), run)

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        # A resume's next run is submitted only when its previous run finishes: one resume's runs are never in
        # flight together, so they never write its extraction markdown at the same time
        pending = {_submit(executor, name, pdf_path, 1): (name, pdf_path) for name, pdf_path in to_extract}
        while pending:
            finished, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in finished:
                name, pdf_path = pending.pop(future)
                result = future.result()
                results[name].append(result)
                done += 1
                status = "ok" if "data" in result else f"FAILED ({result['error']})"
                print(f"[{done}/{total}] {name} run {result['run']}: {status}", file=sys.stderr)
                if result["run"] < RUNS_PER_RESUME:
                    pending[_submit(executor, name, pdf_path, result["run"] + 1)] = (name, pdf_path)

    mode = "Combined Extraction" if args.combined else "Text-only extraction"
    compared = [compare_resume(name, sorted(runs, key=lambda r: r["run"])) for name, runs in results.items()]
    report = build_report(args.set_name, mode, args.reference_date, compared, scanned)

    json_path = os.path.join(RUN_DIR, "consistency_report.json")
    md_path = os.path.join(RUN_DIR, "consistency_report.md")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(render_markdown(report))

    counts = report["counts"]
    print(f"\n[{args.set_name}] Done in {time.time() - start:.1f}s: {counts['identical']}/{counts['resumes']} identical, "
          f"{counts['with_differences']} with differences, {counts['with_errors']} with errors, "
          f"{counts['with_failed_run']} with a failed run.", file=sys.stderr)
    print(f"[{args.set_name}] Report: {md_path}", file=sys.stderr)

    # A run whose request failed measures the server, not the model: the report is kept, the job fails
    raised = sum(1 for runs in results.values() for r in runs if r.get("raised"))
    if raised:
        print(f"[{args.set_name}] [Error] {raised}/{total} extraction requests failed (server down, timeout, or "
              f"rejected; see the report's failed runs for each error).", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
