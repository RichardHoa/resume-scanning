#!/usr/bin/env python3
"""
Token Usage Stats — summarizes the active run folder's logs/token_usage.jsonl (RUN_DIR, default runs/batch-cnb)
per pipeline step, to size max_tokens and the context window from measured usage instead of guesses.
"""
import os
import sys
import json
import argparse
from collections import defaultdict

# Ensure repository root is in sys.path for 'src' package imports
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.core.config import TOKEN_USAGE_FILE, VLLM_MAX_MODEL_LEN


def percentile(sorted_values, pct):
    """Nearest-rank percentile of an already sorted list."""
    rank = max(1, -(-len(sorted_values) * pct // 100))
    return sorted_values[int(rank) - 1]


def summarize(values):
    """'p50 / p95 / max' of the known values, or '-' when there are none."""
    known = sorted(v for v in values if v is not None)
    if not known:
        return "-"
    return f"{percentile(known, 50)} / {percentile(known, 95)} / {known[-1]}"


def main():
    parser = argparse.ArgumentParser(description="Summarize vLLM token usage per pipeline step.")
    parser.add_argument("--file", default=TOKEN_USAGE_FILE, help=f"Token usage JSONL file (default: {TOKEN_USAGE_FILE})")
    args = parser.parse_args()

    if not os.path.exists(args.file):
        print(f"[Token Stats] No token usage file at {args.file}")
        return

    by_step = defaultdict(list)
    with open(args.file, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                record = json.loads(line)
                by_step[record["step"]].append(record)

    if not by_step:
        print(f"[Token Stats] {args.file} is empty")
        return

    rows = []
    for step in sorted(by_step):
        records = by_step[step]
        totals = [
            r["prompt_tokens"] + r["completion_tokens"]
            for r in records if r["prompt_tokens"] is not None and r["completion_tokens"] is not None
        ]
        caps = sorted({r["max_tokens"] for r in records})
        # Per request: completion tokens over wall time, which includes the prompt's prefill and any queueing
        speeds = [
            round(r["completion_tokens"] / r["elapsed_s"], 1)
            for r in records if r.get("completion_tokens") is not None and r.get("elapsed_s")
        ]
        rows.append([
            step,
            str(len(records)),
            summarize(r["prompt_tokens"] for r in records),
            summarize(r["completion_tokens"] for r in records),
            str(max(totals)) if totals else "-",
            "/".join(str(c) for c in caps),
            str(sum(1 for r in records if r["finish_reason"] == "length")),
            summarize(r.get("elapsed_s") for r in records),
            summarize(speeds),
            str(sum(1 for r in records if r["finish_reason"] == "error"))
        ])

    headers = ["step", "calls", "prompt p50/p95/max", "completion p50/p95/max", "max total", "max_tokens", "hit cap",
               "seconds p50/p95/max", "tok/s p50/p95/max", "no answer"]
    widths = [max(len(h), *(len(row[i]) for row in rows)) for i, h in enumerate(headers)]
    print("=" * 80)
    print(f"[Token Stats] {args.file} (context window: {VLLM_MAX_MODEL_LEN} tokens)")
    print("  ".join(h.ljust(w) for h, w in zip(headers, widths)))
    for row in rows:
        print("  ".join(cell.ljust(w) for cell, w in zip(row, widths)))
    print("'hit cap' counts responses cut off at max_tokens (finish_reason 'length'); 'seconds' is each request's wall")
    print("time and 'tok/s' its completion tokens over that time; 'no answer' counts requests that failed or timed out")
    print("(their errors are in the file).")
    print("=" * 80)


if __name__ == "__main__":
    main()
