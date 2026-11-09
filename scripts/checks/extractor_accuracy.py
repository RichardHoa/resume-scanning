#!/usr/bin/env python3
"""
Extractor Accuracy Check — extracts every resume that has a Ground Truth Extraction 5 times and compares each
value against it (.scratch/extractor-accuracy/spec.md).

Run once, with RUN_DIR set to runs/extractor-accuracy (scripts/checks/extractor_accuracy.sh does both). Extracts the
CnB resumes, then the Tech ones, each set under its own Reference Date. Writes extraction_json/<resume>/run-<n>.json
and accuracy_report.md / .json to the run folder.
"""
import os
import sys
import json
import re
import argparse
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
from difflib import SequenceMatcher

# Ensure repository root is in sys.path for 'src' package imports and set CWD
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
os.chdir(_PROJECT_ROOT)

from src.core.config import DEFAULT_LLM_MODEL, DEFAULT_VLLM_URL, RUN_DIR, EXTRACTION_JSON_DIR
from src.core.reference_date import set_reference_date, TECH_REFERENCE_DATE
from src.pipelines.extractor import ResumeExtractor
from extraction_runs import is_scanned_pdf, run_extraction

RUNS_PER_RESUME = 20
GROUND_TRUTH_DIR = os.path.join(_PROJECT_ROOT, "data", "extraction_ground_truth")
DATASET_DIR = os.path.join(_PROJECT_ROOT, "Vietnamese-dataset")
# Each resume set and its Reference Date, in run order (CnB: today)
RESUME_SETS = (("CnB", ""), ("Tech", TECH_REFERENCE_DATE))
# Two list entries are paired only at this similarity or above; below it they are a missed and an extra entry
PAIR_THRESHOLD = 0.5
OUTCOMES = ("correct", "wrong", "missed", "invented")
# Shown for an AI value at a path where that run had nothing to compare (both empty, or no such entry)
NO_VALUE = "(empty or missing)"


def parse_args():
    parser = argparse.ArgumentParser(description="Extractor Accuracy Check: every resume with a Ground Truth Extraction "
                                                 "extracted 5 times and compared against it")
    parser.add_argument("--model-name", type=str, default=DEFAULT_LLM_MODEL, help="Model name served by the vLLM server")
    parser.add_argument("--vllm-url", type=str, default=DEFAULT_VLLM_URL, help="vLLM server URL")
    parser.add_argument("--workers", type=int, default=10, help="Extractions running at once")
    return parser.parse_args()


def find_ground_truths() -> dict[str, list[tuple[str, str, str]]]:
    """
    {resume set: [(resume, PDF path, ground-truth path)]}: each Ground Truth Extraction with the PDF of the same
    name, in the set whose folder holds it. Exits when a ground truth has no PDF.
    """
    if not os.path.isdir(GROUND_TRUTH_DIR):
        print(f"[Error] Ground truth directory not found: {GROUND_TRUTH_DIR}", file=sys.stderr)
        sys.exit(1)
    by_set = {name: [] for name, _ in RESUME_SETS}
    missing = []
    for fname in sorted(f for f in os.listdir(GROUND_TRUTH_DIR) if f.lower().endswith(".json")):
        resume = os.path.splitext(fname)[0]
        found = [s for s in by_set if os.path.isfile(os.path.join(DATASET_DIR, s, f"{resume}.pdf"))]
        if not found:
            missing.append(fname)
            continue
        by_set[found[0]].append(
            (resume, os.path.join(DATASET_DIR, found[0], f"{resume}.pdf"), os.path.join(GROUND_TRUTH_DIR, fname))
        )
    if missing:
        print(f"[Error] No PDF in {DATASET_DIR}/{{CnB,Tech}} for ground truth: {', '.join(missing)}", file=sys.stderr)
        sys.exit(1)
    return by_set


# -----------------------------------------------------------------------------
# Comparison against the ground truth
# -----------------------------------------------------------------------------
def normalize(value):
    """A value with every string trimmed and its inner whitespace (line breaks too) collapsed; nothing else changes."""
    if isinstance(value, str):
        return " ".join(value.split())
    if isinstance(value, list):
        return [normalize(v) for v in value]
    if isinstance(value, dict):
        return {k: normalize(v) for k, v in value.items()}
    return value


def show(value) -> str:
    return json.dumps(value, ensure_ascii=False)


def is_empty(value) -> bool:
    return value is None or value == "" or value == [] or value == {}


def similarity(a, b) -> float:
    return SequenceMatcher(None, show(a), show(b), autojunk=False).ratio()


def filled_leaves(value, path: str):
    """(path, value) of every leaf of value that has a value."""
    if isinstance(value, dict):
        for key, val in value.items():
            yield from filled_leaves(val, f"{path}.{key}" if path else key)
    elif isinstance(value, list):
        for idx, item in enumerate(value):
            yield from filled_leaves(item, f"{path}[{idx}]")
    elif not is_empty(value):
        yield path, value


def align(gt: list, ai: list) -> tuple[list[tuple[int, int]], list[int], list[int]]:
    """
    The order-preserving pairing of ground-truth and AI entries with the highest total similarity, a pair needing
    PAIR_THRESHOLD. Returns the pairs (ground-truth index, AI index), the unpaired ground-truth and AI indexes.
    """
    n, m = len(gt), len(ai)
    sim = [[similarity(g, a) for a in ai] for g in gt]
    best = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        for j in range(1, m + 1):
            best[i][j] = max(best[i - 1][j], best[i][j - 1])
            if sim[i - 1][j - 1] >= PAIR_THRESHOLD:
                best[i][j] = max(best[i][j], best[i - 1][j - 1] + sim[i - 1][j - 1])
    pairs, i, j = [], n, m
    while i and j:
        if sim[i - 1][j - 1] >= PAIR_THRESHOLD and best[i][j] == best[i - 1][j - 1] + sim[i - 1][j - 1]:
            pairs.append((i - 1, j - 1))
            i, j = i - 1, j - 1
        elif best[i][j] == best[i - 1][j]:
            i -= 1
        else:
            j -= 1
    pairs.reverse()
    paired_gt, paired_ai = {p[0] for p in pairs}, {p[1] for p in pairs}
    return pairs, [i for i in range(n) if i not in paired_gt], [j for j in range(m) if j not in paired_ai]


def is_warning(path: str, key: str) -> bool:
    """The top-level warning field, which is never compared."""
    return not path and key == "warning"


def compare(gt, ai, path: str, leaves: list, entries: list):
    """
    Appends to leaves one {"path", "outcome", "gt", "ai"[, "similarity"]} per ground-truth leaf with a value or AI
    leaf with a value (a leaf both leave empty is not counted), and to entries one {"path", "kind", "entry"} per
    missed or extra list entry. gt and ai are normalized; ai is None where the AI has nothing.
    """
    # An AI value of another shape than the ground truth's (a string where a list is expected) is invented
    if isinstance(gt, (dict, list)) and not isinstance(ai, type(gt)) and not is_empty(ai):
        _invent(ai, path, leaves)
    if isinstance(gt, dict):
        ai_dict = ai if isinstance(ai, dict) else {}
        for key, val in gt.items():
            if is_warning(path, key):
                continue
            compare(val, ai_dict.get(key), f"{path}.{key}" if path else key, leaves, entries)
        for key, val in ai_dict.items():
            if key not in gt and not is_warning(path, key):
                _invent(val, f"{path}.{key}" if path else key, leaves)
    elif isinstance(gt, list):
        ai_list = ai if isinstance(ai, list) else []
        pairs, missed, extra = align(gt, ai_list)
        for g, a in pairs:
            compare(gt[g], ai_list[a], f"{path}[{g}]", leaves, entries)
        for g in missed:
            entries.append({"path": path, "kind": "missed", "entry": gt[g]})
            for leaf_path, val in filled_leaves(gt[g], f"{path}[{g}]"):
                leaves.append({"path": leaf_path, "outcome": "missed", "gt": val, "ai": None})
        for a in extra:
            entries.append({"path": path, "kind": "extra", "entry": ai_list[a]})
            _invent(ai_list[a], f"{path}[extra {a}]", leaves)
    elif not is_empty(gt):
        if ai == gt:
            leaves.append({"path": path, "outcome": "correct", "gt": gt, "ai": ai})
        elif is_empty(ai):
            leaves.append({"path": path, "outcome": "missed", "gt": gt, "ai": ai})
        else:
            leaves.append({"path": path, "outcome": "wrong", "gt": gt, "ai": ai, "similarity": round(similarity(gt, ai), 2)})
    elif not is_empty(ai):
        _invent(ai, path, leaves)


def _invent(ai, path: str, leaves: list):
    for leaf_path, val in filled_leaves(ai, path):
        leaves.append({"path": leaf_path, "outcome": "invented", "gt": "", "ai": val})


def field_shape(path: str) -> str:
    """A path with its list positions replaced, so work_experience[0].duration and [3] count as one field."""
    return re.sub(r"\[[^\]]*\]", "[*]", path)


def section_of(path: str) -> str:
    return re.split(r"[.\[]", path, maxsplit=1)[0]


# -----------------------------------------------------------------------------
# Aggregation
# -----------------------------------------------------------------------------
def tally(leaves: list) -> dict:
    counts = Counter(leaf["outcome"] for leaf in leaves)
    out = {o: counts.get(o, 0) for o in OUTCOMES}
    scored = out["correct"] + out["wrong"] + out["missed"]
    out["accuracy"] = round(out["correct"] / scored, 4) if scored else None
    return out


def compare_resume(name: str, ground_truth: dict, results: list[dict]) -> dict:
    """One resume's runs against its ground truth: accuracy per run, the leaves not always correct, entries, failures."""
    gt = normalize(ground_truth)
    ok = [r for r in results if "data" in r]
    per_run = {}
    for r in ok:
        leaves, entries = [], []
        compare(gt, normalize(r["data"]), "", leaves, entries)
        per_run[r["run"]] = {"leaves": leaves, "entries": entries}

    accuracies = {run: tally(v["leaves"])["accuracy"] for run, v in per_run.items()}
    scored = [a for a in accuracies.values() if a is not None]

    by_path = {}
    for run, v in per_run.items():
        for leaf in v["leaves"]:
            by_path.setdefault(leaf["path"], {})[run] = leaf
    problem_leaves = []
    for path, runs in by_path.items():
        if all(leaf["outcome"] == "correct" for leaf in runs.values()) and len(runs) == len(per_run):
            continue
        groups = {}
        for run in sorted(per_run):
            leaf = runs.get(run)
            key = show(leaf["ai"]) if leaf and not is_empty(leaf["ai"]) else NO_VALUE
            group = groups.setdefault(key, {"value": key, "outcome": leaf["outcome"] if leaf else None, "runs": []})
            if leaf and "similarity" in leaf:
                group["similarity"] = leaf["similarity"]
            group["runs"].append(run)
        gt_value = next(iter(runs.values()))["gt"]
        problem_leaves.append({
            "path": path,
            "ground_truth": show(gt_value) if not is_empty(gt_value) else NO_VALUE,
            "ai_values": sorted(groups.values(), key=lambda g: (-len(g["runs"]), g["runs"][0])),
        })

    entry_groups = {}
    for run, v in per_run.items():
        for e in v["entries"]:
            key = (e["path"], e["kind"], show(e["entry"]))
            entry_groups.setdefault(key, []).append(run)

    return {
        "resume": name,
        "ok_runs": sorted(per_run),
        "failed_runs": [{"run": r["run"], "error": r["error"]} for r in results if "error" in r],
        "accuracy": {
            "mean": round(sum(scored) / len(scored), 4) if scored else None,
            "min": min(scored) if scored else None,
            "max": max(scored) if scored else None,
            "per_run": accuracies,
        },
        "counts": tally([leaf for v in per_run.values() for leaf in v["leaves"]]),
        "leaves": problem_leaves,
        "entries": [{"path": p, "kind": k, "entry": e, "runs": runs} for (p, k, e), runs in entry_groups.items()],
        # Kept for the set and overall tables, dropped before the report is written
        "_runs": per_run,
    }


def scope_tables(resumes: list[dict]) -> dict:
    """Summary counts, per section and per field shape, over every ok run of the given resumes."""
    leaves = [leaf for c in resumes for v in c["_runs"].values() for leaf in v["leaves"]]
    entries = [e for c in resumes for v in c["_runs"].values() for e in v["entries"]]

    sections = {}
    for leaf in leaves:
        sections.setdefault(section_of(leaf["path"]), []).append(leaf)
    entry_counts = Counter((section_of(e["path"]), e["kind"]) for e in entries)
    # A section can have entries but no leaf with a value, e.g. an extra entry of empty strings
    section_names = list(sections) + sorted({s for s, _ in entry_counts} - set(sections))
    section_rows = [
        {"section": s, **tally(sections.get(s, [])), "missed_entries": entry_counts.get((s, "missed"), 0),
         "extra_entries": entry_counts.get((s, "extra"), 0)}
        for s in section_names
    ]

    fields = {}
    for leaf in leaves:
        fields.setdefault(field_shape(leaf["path"]), []).append(leaf)
    field_rows = [{"field": f, **tally(ls)} for f, ls in fields.items()]

    def worst_first(row):
        return (-(row["wrong"] + row["missed"] + row["invented"]), row.get("section") or row.get("field"))

    return {
        "summary": {
            **tally(leaves),
            "resumes": len(resumes),
            "ok_runs": sum(len(c["ok_runs"]) for c in resumes),
            "failed_runs": sum(len(c["failed_runs"]) for c in resumes),
        },
        "sections": sorted(section_rows, key=worst_first),
        "fields": sorted(field_rows, key=worst_first),
    }


def build_report(sets: list[dict]) -> dict:
    all_resumes = [c for s in sets for c in s["resumes"]]
    overall = scope_tables(all_resumes)
    overall["summary"]["scanned_skipped"] = sum(len(s["scanned_resumes"]) for s in sets)
    set_reports = []
    for s in sets:
        tables = scope_tables(s["resumes"])
        tables["summary"]["scanned_skipped"] = len(s["scanned_resumes"])
        resumes = sorted(s["resumes"], key=lambda c: (
            c["accuracy"]["mean"] if c["accuracy"]["mean"] is not None else -1, c["resume"]
        ))
        set_reports.append({
            "resume_set": s["resume_set"],
            "reference_date": s["reference_date"] or "today",
            **tables,
            "scanned_resumes": s["scanned_resumes"],
            "resumes": [{k: v for k, v in c.items() if k != "_runs"} for c in resumes],
        })
    return {
        "mode": "Combined Extraction",
        "runs_per_resume": RUNS_PER_RESUME,
        "pair_threshold": PAIR_THRESHOLD,
        "overall": overall,
        "sets": set_reports,
    }


# -----------------------------------------------------------------------------
# Markdown
# -----------------------------------------------------------------------------
def _pct(value) -> str:
    return "—" if value is None else f"{value * 100:.1f}%"


def _runs(runs: list[int]) -> str:
    return ("run " if len(runs) == 1 else "runs ") + ", ".join(str(r) for r in runs)


def _scope_markdown(scope: dict, heading: str) -> list[str]:
    s = scope["summary"]
    lines = [
        f"{heading} Summary", "",
        f"- Accuracy: **{_pct(s['accuracy'])}** (correct ÷ ground-truth values, over every ok run)",
        f"- Correct: {s['correct']}, wrong: {s['wrong']}, missed: {s['missed']}, invented: {s['invented']}",
        f"- Resumes: {s['resumes']}, ok runs: {s['ok_runs']}, failed runs: {s['failed_runs']}",
        f"- Scanned Resumes skipped: {s['scanned_skipped']}"
        + (f" ({', '.join(scope['scanned_resumes'])})" if scope.get("scanned_resumes") else ""),
        "",
        f"{heading} Per section", "",
        "| Section | Accuracy | Correct | Wrong | Missed | Invented | Missed entries | Extra entries |",
        "|---|---|---|---|---|---|---|---|",
    ]
    lines += [
        f"| `{r['section']}` | {_pct(r['accuracy'])} | {r['correct']} | {r['wrong']} | {r['missed']} | "
        f"{r['invented']} | {r['missed_entries']} | {r['extra_entries']} |"
        for r in scope["sections"]
    ]
    lines += [
        "", f"{heading} Per field", "",
        "| Field | Accuracy | Correct | Wrong | Missed | Invented |", "|---|---|---|---|---|---|",
    ]
    lines += [
        f"| `{r['field']}` | {_pct(r['accuracy'])} | {r['correct']} | {r['wrong']} | {r['missed']} | {r['invented']} |"
        for r in scope["fields"]
    ]
    lines.append("")
    return lines


def _resume_markdown(c: dict) -> list[str]:
    acc = c["accuracy"]
    head = f"#### {c['resume']} — {_pct(acc['mean'])}"
    if acc["min"] is not None and acc["min"] != acc["max"]:
        head += f" (runs {_pct(acc['min'])}–{_pct(acc['max'])})"
    lines = [head, ""]
    if c["failed_runs"]:
        lines += [f"- Run {f['run']} failed: {f['error']}" for f in c["failed_runs"]]
        lines.append("")
    if c["entries"]:
        lines += ["**Missed and extra entries**", ""]
        lines += [f"- {e['kind']} `{e['path']}`: {e['entry']} —{_runs(e['runs'])}" for e in c["entries"]]
        lines.append("")
    if c["leaves"]:
        lines += ["**Values not correct in every run**", ""]
        for leaf in c["leaves"]:
            lines += [f"- `{leaf['path']}`", f"  - ground truth: {leaf['ground_truth']}"]
            for g in leaf["ai_values"]:
                note = g["outcome"] or "nothing to compare"
                if "similarity" in g:
                    note += f", similarity {g['similarity']:.2f}"
                lines.append(f"  - {g['value']} — {note} — {_runs(g['runs'])}")
        lines.append("")
    if not (c["failed_runs"] or c["entries"] or c["leaves"]):
        lines += ["Every value correct in every run.", ""]
    return lines


def render_markdown(report: dict) -> str:
    lines = [
        "# Extractor accuracy", "",
        f"{report['mode']}, {report['runs_per_resume']} runs per resume, list entries paired at similarity "
        f"≥ {report['pair_threshold']}. The `warning` field is not compared.", "",
        "## Overall", "",
    ]
    lines += _scope_markdown(report["overall"], "###")
    for s in report["sets"]:
        lines += [f"## {s['resume_set']}", "", f"Reference Date {s['reference_date']}.", ""]
        lines += _scope_markdown(s, "###")
        lines += ["### Resumes", ""]
        for c in s["resumes"]:
            lines += _resume_markdown(c)
    return "\n".join(lines)


# -----------------------------------------------------------------------------
# Main
# -----------------------------------------------------------------------------
def extract_set(extractor: ResumeExtractor, set_name: str, resumes: list[tuple[str, str, str]], workers: int) -> dict:
    """Every resume of one set extracted RUNS_PER_RESUME times and compared; Scanned Resumes skipped."""
    scanned, to_extract = [], []
    for name, pdf_path, gt_path in resumes:
        if is_scanned_pdf(pdf_path):
            print(f"Skipping {name}: Scanned Resume", file=sys.stderr)
            scanned.append(name)
        else:
            to_extract.append((name, pdf_path, gt_path))

    for name, _, _ in to_extract:
        os.makedirs(os.path.join(EXTRACTION_JSON_DIR, name), exist_ok=True)
    total = len(to_extract) * RUNS_PER_RESUME
    print(f"[{set_name}] {len(to_extract)} resumes x {RUNS_PER_RESUME} runs = {total} extractions.", file=sys.stderr)

    results = {name: [] for name, _, _ in to_extract}
    done = 0

    def _submit(executor, name, pdf_path, run):
        return executor.submit(run_extraction, extractor, pdf_path, os.path.join(EXTRACTION_JSON_DIR, name), run)

    with ThreadPoolExecutor(max_workers=max(1, workers)) as executor:
        # A resume's next run is submitted only when its previous run finishes: one resume's runs are never in
        # flight together, so they never write its extraction markdown at the same time
        pending = {_submit(executor, name, pdf_path, 1): (name, pdf_path) for name, pdf_path, _ in to_extract}
        while pending:
            finished, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in finished:
                name, pdf_path = pending.pop(future)
                result = future.result()
                results[name].append(result)
                done += 1
                status = "ok" if "data" in result else f"FAILED ({result['error']})"
                print(f"[{set_name}] [{done}/{total}] {name} run {result['run']}: {status}", file=sys.stderr)
                if result["run"] < RUNS_PER_RESUME:
                    pending[_submit(executor, name, pdf_path, result["run"] + 1)] = (name, pdf_path)

    compared = []
    for name, _, gt_path in to_extract:
        with open(gt_path, encoding="utf-8") as f:
            ground_truth = json.load(f)
        compared.append(compare_resume(name, ground_truth, sorted(results[name], key=lambda r: r["run"])))
    raised = sum(1 for runs in results.values() for r in runs if r.get("raised"))
    return {"resume_set": set_name, "scanned_resumes": scanned, "resumes": compared, "raised": raised, "total": total}


def main():
    args = parse_args()
    by_set = find_ground_truths()

    extractor = ResumeExtractor(model_name=args.model_name, vllm_url=args.vllm_url)
    extractor.load_model()

    start = time.time()
    sets = []
    for set_name, reference_date in RESUME_SETS:
        if not by_set[set_name]:
            continue
        # The Reference Date is process-wide: one set's extractions all finish before the next set's date is set
        set_reference_date(reference_date)
        result = extract_set(extractor, set_name, by_set[set_name], args.workers)
        result["reference_date"] = reference_date
        sets.append(result)

    report = build_report(sets)
    json_path = os.path.join(RUN_DIR, "accuracy_report.json")
    md_path = os.path.join(RUN_DIR, "accuracy_report.md")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(render_markdown(report))

    s = report["overall"]["summary"]
    print(f"\nDone in {time.time() - start:.1f}s: accuracy {_pct(s['accuracy'])} ({s['correct']} correct, "
          f"{s['wrong']} wrong, {s['missed']} missed, {s['invented']} invented), {s['failed_runs']} failed runs.",
          file=sys.stderr)
    print(f"Report: {md_path}", file=sys.stderr)

    # A run whose request failed measures the server, not the model: the report is kept, the job fails
    raised = sum(s["raised"] for s in sets)
    if raised:
        print(f"[Error] {raised}/{sum(s['total'] for s in sets)} extraction requests failed (server down, timeout, "
              f"or rejected; see the report's failed runs for each error).", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
