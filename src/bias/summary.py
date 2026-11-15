"""
Bias Check summary (CSV + text table).

Rebuilds runs/bias-cnb/bias_summary.csv (and a readable report.txt and report.html of the same numbers)
from every bias_detection_<category>.csv in that folder. Each ordering's runs (one per Bias Repetition) are combined
as production combines a Category's runs (vote_criteria), and each combined score is compared against the Combined
Baseline: one row per (category, shuffle kind) plus an ALL row per category, answering "what % of orderings differ
from the Combined Baseline, and by how many points".

Rebuild from existing results without re-running:
  python3 -m src.bias.summary runs/bias-cnb
"""
import os
import sys
import csv
from typing import Dict, List, Any, Optional

from src.core.config import DEFAULT_LLM_MODEL
from src.pipelines.scoring import vote_criteria
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
    "orderings",
    "failed",
    "changed_pct",
    "verdict_changed_pct",
    *[name for name, _, _, _ in CHANGE_BUCKETS],
    "went_up_pct",
    "went_down_pct",
    "biggest_change",
    "combined_baseline",
    "baseline_scores",
]


def _pct(count: int, total: int) -> Optional[float]:
    return round(100.0 * count / total, 1) if total else None


def load_category_runs(csv_path: str) -> List[Dict[str, Any]]:
    """
    The runs of one bias_detection_<category>.csv, each with its Criteria as {"criterion": "C<i>", "verdict",
    "importance"}: what vote_criteria needs to combine them.
    """
    runs: List[Dict[str, Any]] = []
    with open(csv_path, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        num_criteria = sum(1 for name in reader.fieldnames or [] if name.endswith("_verdict"))
        for raw in reader:
            runs.append({
                "iteration_number": int(raw["iteration_number"]),
                "run_index": int(raw["run_index"]),
                "experiment_type": raw["experiment_type"],
                "condition": raw["condition"],
                "overall_score": round(float(raw["overall_score"])),
                "is_valid": raw["is_valid"] in ("1", "True", "true"),
                "criteria": [
                    {"criterion": f"C{i}", "verdict": raw[f"c{i}_verdict"], "importance": raw[f"c{i}_importance"]}
                    for i in range(1, num_criteria + 1)
                ],
            })
    return runs


def combine_orderings(runs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    One entry per ordering (run_index; the Baseline is 1), in run_index order: its runs across the Bias Repetitions
    combined into one Category Score as production combines a Category's runs. An ordering with an invalid run has no
    score ("failed"), as a failed run fails its Category in production. "verdicts" maps each Criterion id to its voted
    Verdict.
    """
    by_index: Dict[int, List[Dict[str, Any]]] = {}
    for r in sorted(runs, key=lambda r: (r["run_index"], r["iteration_number"])):
        by_index.setdefault(r["run_index"], []).append(r)

    orderings = []
    for run_index, group in by_index.items():
        voted = None
        if all(r["is_valid"] for r in group):
            voted = vote_criteria([{"criteria_evaluations": r["criteria"]} for r in group], is_en=True)
        orderings.append({
            "run_index": run_index,
            "experiment_type": group[0]["experiment_type"],
            "condition": group[0]["condition"],
            "runs": len(group),
            "failed": voted is None,
            "score": voted["score"] if voted else None,
            "verdicts": {c["criterion"]: c["verdict"] for c in voted["criteria_evaluations"]} if voted else {},
        })
    return orderings


def changed_criteria(ordering: Dict[str, Any], baseline: Dict[str, Any]) -> List[str]:
    """The Criterion ids whose voted Verdict differs from the Combined Baseline's."""
    return [c_id for c_id, verdict in ordering["verdicts"].items() if baseline["verdicts"].get(c_id) != verdict]


def summarize_shuffle_kind(orderings: List[Dict[str, Any]], baseline: Dict[str, Any]) -> Dict[str, Any]:
    """
    Summarizes one shuffle kind's combined orderings against the Combined Baseline. An ordering counts as failed if
    it has no combined score or the Combined Baseline has none (no trustworthy score to compare against).
    Percentages are over non-failed orderings.
    """
    ok = [] if baseline["failed"] else [o for o in orderings if not o["failed"]]
    changes = [o["score"] - baseline["score"] for o in ok]
    row: Dict[str, Any] = {
        "orderings": len(orderings),
        "failed": len(orderings) - len(ok),
        "changed_pct": _pct(sum(1 for c in changes if c != 0), len(ok)),
        "verdict_changed_pct": _pct(sum(1 for o in ok if changed_criteria(o, baseline)), len(ok)),
        "went_up_pct": _pct(sum(1 for c in changes if c > 0), len(ok)),
        "went_down_pct": _pct(sum(1 for c in changes if c < 0), len(ok)),
        "biggest_change": max((abs(c) for c in changes), default=None),
    }
    for name, _, low, high in CHANGE_BUCKETS:
        row[name] = _pct(sum(1 for c in changes if low <= abs(c) <= high), len(ok))
    return row


def summarize_category_csv(csv_path: str) -> List[Dict[str, Any]]:
    """Returns summary rows (one per shuffle kind, in order of appearance, then ALL) for one category CSV."""
    runs = load_category_runs(csv_path)
    orderings = combine_orderings(runs)

    # The single-run Baseline scores show how much one run moves with no reordering
    baselines = sorted((r for r in runs if r["experiment_type"] == "Baseline"), key=lambda r: r["iteration_number"])
    baseline_scores = " ".join(str(r["overall_score"]) if r["is_valid"] else "failed" for r in baselines)
    baseline = next(o for o in orderings if o["experiment_type"] == "Baseline")
    combined_baseline = "failed" if baseline["failed"] else str(baseline["score"])

    shuffled = [o for o in orderings if o["experiment_type"] != "Baseline"]
    shuffle_kinds = list(dict.fromkeys(o["experiment_type"] for o in shuffled))

    rows = []
    for kind in shuffle_kinds + ["ALL"]:
        kind_orderings = shuffled if kind == "ALL" else [o for o in shuffled if o["experiment_type"] == kind]
        row = {"shuffle_kind": kind, "combined_baseline": combined_baseline, "baseline_scores": baseline_scores}
        row.update(summarize_shuffle_kind(kind_orderings, baseline))
        rows.append(row)
    return rows


def format_category_table(category: str, rows: List[Dict[str, Any]]) -> str:
    """Renders one category's summary rows as a fixed-width text table (same numbers as the CSV)."""
    def pct(v: Optional[float]) -> str:
        return f"{v:.1f}%" if v is not None else "-"

    bucket_header = " ".join(f"{label:>6s}" for _, label, _, _ in CHANGE_BUCKETS)
    header = (
        f" {'Shuffle kind':<28s} {'Orderings':>9s} {'Failed':>6s} {'Changed':>7s} {'Verdict':>7s} | {bucket_header} |"
        f" {'Up':>6s} {'Down':>6s} | {'Biggest':>7s}"
    )
    width = len(header)
    lines = [
        "=" * width,
        f" 📊 BIAS SUMMARY: [{category}]",
        f" Combined Baseline score: {rows[0]['combined_baseline'] if rows else '-'}",
        f" Single-run Baseline score in each Bias Repetition: {rows[0]['baseline_scores'] if rows else '-'}",
        f" Points each ordering's combined score moved from the Combined Baseline (% of non-failed orderings);",
        f" Verdict: % of orderings with at least one voted Verdict different from the Combined Baseline's:",
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
            f" {r['shuffle_kind']:<28s} {r['orderings']:>9,d} {r['failed']:>6,d} {pct(r['changed_pct']):>7s}"
            f" {pct(r['verdict_changed_pct']):>7s} | {buckets} |"
            f" {pct(r['went_up_pct']):>6s} {pct(r['went_down_pct']):>6s} | {biggest:>7s}"
        )
    lines.append("=" * width)
    return "\n".join(lines)


def write_bias_summary(model_dir: str) -> Optional[str]:
    """
    Rebuilds <model_dir>/bias_summary.csv, report.txt and report.html from all category CSVs in it.
    Returns the CSV path, or None if no category CSV exists. The Bias Check only runs the default model.
    """
    model = DEFAULT_LLM_MODEL
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
        print("Usage: python3 -m src.bias.summary runs/bias-cnb", file=sys.stderr)
        sys.exit(1)
    for d in sys.argv[1:]:
        path = write_bias_summary(d)
        if path:
            print(path)
            print(os.path.join(d, REPORT_FILENAME))
            print(os.path.join(d, HTML_FILENAME))
        else:
            print(f"[Skip] No bias_detection_*.csv found in {d}")
