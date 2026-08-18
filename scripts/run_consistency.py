#!/usr/bin/env python3
"""
Consistency Evaluator Script — Runs 20 evaluation rounds on candidates
and generates a CSV matrix (round + 38 candidate emails = 39 columns).
"""
import os
import sys
import json
import csv
import argparse
import time
import re

# Ensure repository root is in sys.path for 'src' package imports and set CWD
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
os.chdir(_PROJECT_ROOT)

from src.core.config import DEFAULT_LLM_MODEL, DEFAULT_VLLM_URL
from src.pipelines.evaluator import ResumeEvaluator
from src.cli.evaluate import load_requirements


def extract_candidate_email(resume_data: dict, filename: str) -> str:
    """Extract candidate email from extracted JSON or fallback to regex / filename."""
    if isinstance(resume_data, dict):
        basic = resume_data.get("basic_information") or resume_data.get("basic_info") or {}
        if isinstance(basic, dict):
            email = basic.get("email")
            if email and isinstance(email, str) and "@" in email and "." in email:
                return email.strip().lower()

        # Fallback: search regex in raw json
        json_str = json.dumps(resume_data)
        matches = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', json_str)
        if matches:
            return matches[0].strip().lower()

    # Fallback to base filename identifier
    base_name = os.path.splitext(filename)[0]
    return f"{base_name}@unknown.com"


def parse_args():
    parser = argparse.ArgumentParser(description="Candidate Evaluation Consistency Test (20 Rounds)")
    parser.add_argument("--dir", type=str, default="output_jsons", help="Directory containing extracted resume JSON files")
    parser.add_argument("--job-req", type=str, default="hr-requirement.txt", help="Path to HR requirements file")
    parser.add_argument("--hidden-req", type=str, default="", help="Path to hidden requirements file")
    parser.add_argument("--hr-req", type=str, default="", help="Path to combined HR requirements file")
    parser.add_argument("--model-name", type=str, default=DEFAULT_LLM_MODEL, help="LLM model name")
    parser.add_argument("--backend", type=str, default="vllm", choices=["transformers", "vllm"], help="Inference backend")
    parser.add_argument("--vllm-url", type=str, default=DEFAULT_VLLM_URL, help="vLLM server URL")
    parser.add_argument("--workers", type=int, default=6, help="Worker threads for parallel evaluation")
    parser.add_argument("--rounds", type=int, default=20, help="Number of consistency test rounds")
    parser.add_argument("--num-evaluations", type=int, default=20, help="Evaluations per category to compute median per evaluation round (default: 20)")
    parser.add_argument("--output", type=str, default="consistency_results.csv", help="Output CSV filepath")
    return parser.parse_args()


def main():
    args = parse_args()

    # Disable detailed prompt logging to txt files
    os.environ["DISABLE_PROMPT_LOGGING"] = "1"

    input_dir = args.dir
    if not os.path.isdir(input_dir):
        print(f"[Error] Directory not found: {input_dir}", file=sys.stderr)
        sys.exit(1)

    json_files = sorted([f for f in os.listdir(input_dir) if f.lower().endswith('.json')])
    if not json_files:
        print(f"[Error] No JSON resume files found in {input_dir}", file=sys.stderr)
        sys.exit(1)

    print(f"Found {len(json_files)} candidate resume files in '{input_dir}'.", file=sys.stderr)

    # 1. Map candidate JSON files to candidate emails
    candidates = []
    seen_emails = set()
    for fname in json_files:
        fpath = os.path.join(input_dir, fname)
        try:
            with open(fpath, "r", encoding="utf-8") as f:
                rdata = json.load(f)
            email = extract_candidate_email(rdata, fname)
        except Exception:
            base = os.path.splitext(fname)[0]
            email = f"{base}@unknown.com"

        # Disambiguate duplicate emails if needed
        final_email = email
        dup_counter = 1
        while final_email in seen_emails:
            dup_counter += 1
            final_email = f"{email.split('@')[0]}_{dup_counter}@{email.split('@')[1] if '@' in email else 'unknown.com'}"
        seen_emails.add(final_email)

        candidates.append({
            "filename": fname,
            "path": fpath,
            "email": final_email,
            "resume_name": os.path.splitext(fname)[0]
        })

    candidate_emails = [c["email"] for c in candidates]
    csv_headers = ["round"] + candidate_emails
    print(f"[CSV Matrix Setup] Matrix dimensions: {args.rounds} rows x {len(csv_headers)} columns wide.", file=sys.stderr)

    # 2. Load requirements and initialize evaluator
    standard_req, hidden_req = load_requirements(args)

    evaluator = ResumeEvaluator(
        model_name=args.model_name,
        backend=args.backend,
        vllm_url=args.vllm_url,
        mock=False
    )

    evaluator.load_model()

    if standard_req or hidden_req:
        print("[HR Requirements] Pre-ingesting criteria into RAG vector store...", file=sys.stderr)
        evaluator.rag.ingest_requirements(
            standard_req,
            hidden_req,
            llm_decomposer_func=lambda s, h: evaluator._decompose_requirements_with_llm(s, h, "consistency_init")
        )

    # 3. Open CSV and write header
    csv_file_path = args.output
    os.makedirs(os.path.dirname(os.path.abspath(csv_file_path)) or ".", exist_ok=True)

    with open(csv_file_path, "w", newline="", encoding="utf-8") as f_csv:
        writer = csv.writer(f_csv)
        writer.writerow(csv_headers)
        f_csv.flush()

        # 4. Perform evaluation across 20 rounds
        start_total_time = time.time()
        for r in range(1, args.rounds + 1):
            round_start = time.time()
            print(f"\n==================================================================", file=sys.stderr)
            print(f" 🚀 STARTING EVALUATION ROUND {r}/{args.rounds}", file=sys.stderr)
            print(f"==================================================================", file=sys.stderr)

            round_scores = {}

            def _eval_single_candidate(cand_item):
                c_info = cand_item
                fname = c_info["filename"]
                fpath = c_info["path"]
                rname = c_info["resume_name"]

                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        resume_data = json.load(f)

                    result = evaluator.evaluate_resume(
                        resume_data,
                        standard_req,
                        hidden_req,
                        resume_name=rname,
                        num_evaluations=args.num_evaluations
                    )
                    score = result.get("overall_score", 0.0)
                    return c_info["email"], score
                except Exception as e:
                    print(f" Error evaluating {fname} in round {r}: {e}", file=sys.stderr)
                    return c_info["email"], 0.0

            workers = max(1, args.workers)
            if workers > 1 and args.backend == "vllm":
                from concurrent.futures import ThreadPoolExecutor
                with ThreadPoolExecutor(max_workers=workers) as executor:
                    results = executor.map(_eval_single_candidate, candidates)
                    for email, score in results:
                        round_scores[email] = score
            else:
                for cand in candidates:
                    email, score = _eval_single_candidate(cand)
                    round_scores[email] = score

            # Construct row for this round
            row = [r] + [round_scores.get(email, 0.0) for email in candidate_emails]
            writer.writerow(row)
            f_csv.flush()

            round_time = time.time() - round_start
            print(f" Round {r}/{args.rounds} completed in {round_time:.2f}s. Row saved to {csv_file_path}", file=sys.stderr)

    total_time = time.time() - start_total_time
    print(f"\n==================================================================", file=sys.stderr)
    print(f" SUCCESS: All {args.rounds} evaluation rounds completed in {total_time:.2f}s!", file=sys.stderr)
    print(f" Consistency matrix saved to: {os.path.abspath(csv_file_path)}", file=sys.stderr)
    print(f" Total columns: {len(csv_headers)} (1 round + {len(candidate_emails)} candidates)", file=sys.stderr)
    print(f"==================================================================", file=sys.stderr)


if __name__ == "__main__":
    main()
