"""
Per-model bias report page (HTML).

Renders bias-result/<MODEL_KEY>/report.html from the bias_summary.csv and report.txt that src/bias/summary.py
writes: one bar chart per category showing how many points each shuffle kind moved the score from the Baseline,
plus the raw report.txt and bias_summary.csv as tabs. The page is self-contained (no network), so it opens offline.

Rebuild from an existing summary without re-running:
  python3 -m src.bias.report_html bias-result/<MODEL_KEY>
"""
import os
import sys
import csv
import json
from typing import Dict, List, Any, Optional

SUMMARY_FILENAME = "bias_summary.csv"
REPORT_FILENAME = "report.txt"
HTML_FILENAME = "report.html"
TEMPLATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "report_template.html")
DATA_MARKER = "/*__REPORT_DATA__*/null"

PCT_FIELDS = ["changed_pct", "moved_0_pct", "moved_1_30_pct", "moved_31_60_pct", "moved_61_100_pct", "went_up_pct", "went_down_pct"]


def _num(value: str, cast) -> Optional[Any]:
    return cast(value) if value not in ("", None) else None


def load_summary_categories(csv_path: str) -> List[Dict[str, Any]]:
    """Groups bias_summary.csv rows by category (in file order), with numbers parsed and blanks as None."""
    categories: Dict[str, Dict[str, Any]] = {}
    with open(csv_path, "r", encoding="utf-8") as f:
        for raw in csv.DictReader(f):
            row = {
                "shuffle_kind": raw["shuffle_kind"],
                "runs": int(raw["runs"]),
                "failed": int(raw["failed"]),
                "biggest_change": _num(raw["biggest_change"], int),
                **{name: _num(raw[name], float) for name in PCT_FIELDS},
            }
            cat = categories.setdefault(raw["category"], {
                "category": raw["category"],
                "baseline_scores": raw["baseline_scores"],
                "rows": [],
            })
            cat["rows"].append(row)
    return list(categories.values())


def write_report_html(model_dir: str) -> Optional[str]:
    """
    Writes <model_dir>/report.html from its bias_summary.csv (and report.txt, if present).
    Returns the HTML path, or None if there is no bias_summary.csv.
    """
    csv_path = os.path.join(model_dir, SUMMARY_FILENAME)
    if not os.path.isfile(csv_path):
        return None
    txt_path = os.path.join(model_dir, REPORT_FILENAME)

    with open(csv_path, "r", encoding="utf-8") as f:
        summary_csv = f.read()
    report_txt = ""
    if os.path.isfile(txt_path):
        with open(txt_path, "r", encoding="utf-8") as f:
            report_txt = f.read()

    data = {
        "model": os.path.basename(os.path.normpath(model_dir)),
        "categories": load_summary_categories(csv_path),
        "report_txt": report_txt,
        "summary_csv": summary_csv,
    }
    # "</" is escaped so file contents can never close the <script> block early
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")

    with open(TEMPLATE_PATH, "r", encoding="utf-8") as f:
        template = f.read()
    out_path = os.path.join(model_dir, HTML_FILENAME)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(template.replace(DATA_MARKER, payload))
    return out_path


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python3 -m src.bias.report_html bias-result/<MODEL_KEY> [bias-result/<MODEL_KEY> ...]", file=sys.stderr)
        sys.exit(1)
    for d in sys.argv[1:]:
        path = write_report_html(d)
        print(path if path else f"[Skip] No {SUMMARY_FILENAME} found in {d}")
