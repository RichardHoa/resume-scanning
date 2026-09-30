"""
Per-model bias summary (CSV + text table).

Rebuilds bias-result/<MODEL_KEY>/bias_summary.csv (and a readable report.txt and report.html of the same numbers)
from every bias_detection_<category>.csv in that folder: one row per (category, shuffle kind) plus an ALL row
per category, answering "what % of runs differ from the Baseline, and by how many points".

Backfill existing results without re-running:
  python3 -m src.bias.summary bias-result/<MODEL_KEY>
"""
import os
import sys
import csv
from typing import Dict, List, Any, Optional

from src.bias.registry import get_all_category_keys
from src.bias.report_html import HTML_FILENAME, write_report_html

SUMMARY_FILENAME = "bias_summary.csv"
REPORT_FILENAME = "report.txt"

# (column name, text-table header, lowest |points changed|, highest |points changed|) — scores are 0-100 integers
CHANGE_BUCKETS = [
    ("moved_0_pct", "0", 0, 0),
    ("moved_1_30_pct", "1-30", 1, 30),
    ("moved_31_60_pct", "31-60", 31, 60),
    ("moved_61_100_pct", "61-100", 61, 100),
]

SUMMARY_FIELDNAMES = [
    "model",
    "category",
    "shuffle_kind",
    "runs",
    "failed",
    "changed_pct",
    *[name for name, _, _, _ in CHANGE_BUCKETS],
    "went_up_pct",
    "went_down_pct",
    "biggest_change",
    "baseline_scores",
]


def _pct(count: int, total: int) -> Optional[float]:
    return round(100.0 * count / total, 1) if total else None


def summarize_shuffle_kind(runs: List[Dict[str, Any]], baseline_valid: Dict[int, bool]) -> Dict[str, Any]:
    """
    Summarizes shuffled runs against the Baseline of the same iteration.
    A run counts as failed if its own output was invalid or its iteration's Baseline was invalid
    (no trustworthy score to compare against). Percentages are over non-failed runs.
    """
    changes = [
        r["overall_score"] - r["baseline_score"]
        for r in runs
        if r["is_valid"] and baseline_valid.get(r["iteration_number"], False)
    ]
    ok = len(changes)
    row: Dict[str, Any] = {
        "runs": len(runs),
        "failed": len(runs) - ok,
        "changed_pct": _pct(sum(1 for c in changes if c != 0), ok),
        "went_up_pct": _pct(sum(1 for c in changes if c > 0), ok),
        "went_down_pct": _pct(sum(1 for c in changes if c < 0), ok),
        "biggest_change": max((abs(c) for c in changes), default=None),
    }
    for name, _, low, high in CHANGE_BUCKETS:
        row[name] = _pct(sum(1 for c in changes if low <= abs(c) <= high), ok)
    return row


def summarize_category_csv(csv_path: str) -> List[Dict[str, Any]]:
    """Returns summary rows (one per shuffle kind, in order of appearance, then ALL) for one category CSV."""
    runs: List[Dict[str, Any]] = []
    with open(csv_path, "r", encoding="utf-8") as f:
        for raw in csv.DictReader(f):
            runs.append({
                "iteration_number": int(raw["iteration_number"]),
                "experiment_type": raw["experiment_type"],
                "overall_score": round(float(raw["overall_score"])),
                "baseline_score": round(float(raw["baseline_score"])),
                "is_valid": raw["is_valid"] in ("1", "True", "true"),
            })

    baselines = sorted((r for r in runs if r["experiment_type"] == "Baseline"), key=lambda r: r["iteration_number"])
    baseline_valid = {r["iteration_number"]: r["is_valid"] for r in baselines}
    baseline_scores = " ".join(str(r["overall_score"]) if r["is_valid"] else "failed" for r in baselines)

    shuffled = [r for r in runs if r["experiment_type"] != "Baseline"]
    shuffle_kinds = list(dict.fromkeys(r["experiment_type"] for r in shuffled))

    rows = []
    for kind in shuffle_kinds + ["ALL"]:
        kind_runs = shuffled if kind == "ALL" else [r for r in shuffled if r["experiment_type"] == kind]
        row = {"shuffle_kind": kind, "baseline_scores": baseline_scores}
        row.update(summarize_shuffle_kind(kind_runs, baseline_valid))
        rows.append(row)
    return rows


def format_category_table(category: str, rows: List[Dict[str, Any]]) -> str:
    """Renders one category's summary rows as a fixed-width text table (same numbers as the CSV)."""
    def pct(v: Optional[float]) -> str:
        return f"{v:.1f}%" if v is not None else "-"

    bucket_header = " ".join(f"{label:>6s}" for _, label, _, _ in CHANGE_BUCKETS)
    header = (
        f" {'Shuffle kind':<28s} {'Runs':>6s} {'Failed':>6s} {'Changed':>7s} | {bucket_header} |"
        f" {'Up':>6s} {'Down':>6s} | {'Biggest':>7s}"
    )
    width = len(header)
    lines = [
        "=" * width,
        f" 📊 BIAS SUMMARY: [{category}]",
        f" Baseline score in each repeat: {rows[0]['baseline_scores'] if rows else '-'}",
        f" Points moved from the Baseline (% of non-failed runs):",
        "-" * width,
        header,
        "-" * width,
    ]
    for r in rows:
        if r["shuffle_kind"] == "ALL":
            lines.append("-" * width)
        buckets = " ".join(f"{pct(r[name]):>6s}" for name, _, _, _ in CHANGE_BUCKETS)
        biggest = str(r["biggest_change"]) if r["biggest_change"] is not None else "-"
        lines.append(
            f" {r['shuffle_kind']:<28s} {r['runs']:>6,d} {r['failed']:>6,d} {pct(r['changed_pct']):>7s} | {buckets} |"
            f" {pct(r['went_up_pct']):>6s} {pct(r['went_down_pct']):>6s} | {biggest:>7s}"
        )
    lines.append("=" * width)
    return "\n".join(lines)


def write_model_summary(model_dir: str) -> Optional[str]:
    """
    Rebuilds <model_dir>/bias_summary.csv, report.txt and report.html from all category CSVs in it.
    Returns the CSV path, or None if no category CSV exists.
    """
    model = os.path.basename(os.path.normpath(model_dir))
    known = get_all_category_keys()
    present = [
        f[len("bias_detection_"):-len(".csv")]
        for f in os.listdir(model_dir)
        if f.startswith("bias_detection_") and f.endswith(".csv")
    ]
    categories = [c for c in known if c in present] + sorted(c for c in present if c not in known)
    if not categories:
        return None

    out_rows = []
    tables = [f" MODEL: {model}"]
    for category in categories:
        rows = summarize_category_csv(os.path.join(model_dir, f"bias_detection_{category}.csv"))
        tables.append(format_category_table(category, rows))
        for row in rows:
            out_rows.append({"model": model, "category": category, **row})

    out_path = os.path.join(model_dir, SUMMARY_FILENAME)
    with open(out_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=SUMMARY_FIELDNAMES)
        writer.writeheader()
        writer.writerows(out_rows)
    with open(os.path.join(model_dir, REPORT_FILENAME), "w", encoding="utf-8") as f:
        f.write("\n\n".join(tables) + "\n")
    write_report_html(model_dir)
    return out_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 -m src.bias.summary bias-result/<MODEL_KEY> [bias-result/<MODEL_KEY> ...]", file=sys.stderr)
        sys.exit(1)
    for d in sys.argv[1:]:
        path = write_model_summary(d)
        if path:
            print(path)
            print(os.path.join(d, REPORT_FILENAME))
            print(os.path.join(d, HTML_FILENAME))
        else:
            print(f"[Skip] No bias_detection_*.csv found in {d}")
