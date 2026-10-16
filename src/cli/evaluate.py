"""
CLI Entrypoint for Step 2 Resume Evaluator (supports single-file & batch directory processing)
"""
import os
import sys

# Ensure repository root is in sys.path for 'src' package imports
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import json
import argparse
import time
import re
from src.core.config import (
    DEFAULT_LLM_MODEL, DEFAULT_VLLM_URL, VLLM_MAX_CONCURRENT_REQUESTS, HR_CHECK_ITEMS_KEY, EXTRACTION_JSON_DIR, EVALUATION_JSON_DIR
)
from src.core.reference_date import set_reference_date
from src.pipelines.evaluator import ResumeEvaluator


def parse_args():
    parser = argparse.ArgumentParser(description="Vietnamese Resume Evaluator Agent (Step 2)")
    parser.add_argument("--resume-json", type=str, help="Path to single extracted resume JSON file")
    parser.add_argument("--dir", type=str, help="Path to directory containing extracted resume JSON files")
    parser.add_argument("--model-name", type=str, default=DEFAULT_LLM_MODEL, help="Model name served by the vLLM server")
    parser.add_argument("--vllm-url", type=str, default=DEFAULT_VLLM_URL, help="Base URL of the vLLM OpenAI-compatible server")
    parser.add_argument("--mock", action="store_true", help="Mock run without loading model weights")
    parser.add_argument("--output", type=str, help="Path to save evaluation JSON result (file path or output directory for batch mode)")
    parser.add_argument("--arr", type=str, help="Comma-separated list of resume numbers to process (e.g., --arr=6,7,8)")
    parser.add_argument("--workers", type=int, default=VLLM_MAX_CONCURRENT_REQUESTS, help="Max candidates evaluated at once (default: the vLLM request limit, which does the throttling)")
    parser.add_argument("--num-evaluations", "--runs", type=int, default=1, help="Number of evaluation iterations per category to calculate median (default: 1)")
    parser.add_argument("--no-feedback", action="store_true", help="Skip the Review Panel's Candidate Feedback (scores only)")
    parser.add_argument("--language", type=str, default="vietnamese", choices=["vietnamese", "english"], help="Output language for evaluation reasoning, strengths, and gaps ('vietnamese' or 'english')")
    parser.add_argument("--reference-date", type=str, default="", help="Date (YYYY-MM-DD) the prompts treat as today, for old resume sets (default: the real date)")
    return parser.parse_args()


def load_hr_rag_requirements(evaluator):
    """
    HR's Standard and Hidden Requirements text stored with the HR RAG. Exits if HR has not set the HR RAG:
    evaluation never builds or changes it, so HR controls exactly which Criteria count.
    """
    try:
        evaluator.rag.require_stored_rag()
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    summary = evaluator.rag.get_stored_rag_summary()
    counts = ", ".join(f"{cat}: {len(items)}" for cat, items in summary["categories"].items())
    print(f"[HR RAG] Evaluating against the stored HR RAG ({counts}; HR Check Items: {len(summary[HR_CHECK_ITEMS_KEY])})", file=sys.stderr)
    return summary["standard_requirements"], summary["hidden_requirements"]


def main():
    args = parse_args()
    set_reference_date(args.reference_date)

    input_dir = args.dir
    single_file = args.resume_json

    # Default to the run folder's extractions if neither --resume-json nor --dir is passed
    if not single_file and not input_dir:
        input_dir = EXTRACTION_JSON_DIR

    if single_file and input_dir:
        print("Error: You cannot specify both --resume-json and --dir. Please choose one.", file=sys.stderr)
        sys.exit(1)

    evaluator = ResumeEvaluator(
        model_name=args.model_name,
        vllm_url=args.vllm_url,
        mock=args.mock,
        language=args.language
    )
    standard_req, hidden_req = load_hr_rag_requirements(evaluator)

    # --- Batch Directory Mode ---
    if input_dir:
        if not os.path.isdir(input_dir):
            print(f"Error: Directory not found: {input_dir}", file=sys.stderr)
            sys.exit(1)

        output_dir = args.output or EVALUATION_JSON_DIR
        os.makedirs(output_dir, exist_ok=True)

        json_files = [f for f in os.listdir(input_dir) if f.lower().endswith('.json')]

        if args.arr:
            try:
                arr_indices = {int(x.strip()) for x in args.arr.split(",") if x.strip()}
            except ValueError:
                print("Error: --arr must be a comma-separated list of integers.", file=sys.stderr)
                sys.exit(1)

            def is_match(fn):
                m = re.search(r'(\d+)', fn)
                return m and int(m.group(1)) in arr_indices

            json_files = [f for f in json_files if is_match(f)]

        if not json_files:
            print(f"No JSON resume files found in {input_dir}.", file=sys.stderr)
            sys.exit(0)

        json_files.sort()
        print(f"Found {len(json_files)} JSON resume files in '{input_dir}'. Starting batch evaluation...", file=sys.stderr)
        evaluator.load_model()

        def _process_single_resume(item_info):
            idx, filename = item_info
            file_path = os.path.join(input_dir, filename)
            resume_name = os.path.splitext(filename)[0]

            print(f"\n[{idx}/{len(json_files)}] Evaluating {filename}...", file=sys.stderr)
            try:
                with open(file_path, "r", encoding="utf-8") as f:
                    resume_data = json.load(f)

                result = evaluator.evaluate_resume(
                    resume_data,
                    standard_req,
                    hidden_req,
                    resume_name=resume_name,
                    output_dir=output_dir,
                    num_evaluations=args.num_evaluations,
                    resume_path=file_path,
                    generate_feedback=not args.no_feedback
                )
                out_path = os.path.join(output_dir, f"{resume_name}_evaluation.json")
                print(f"  Saved evaluation result to: {out_path}", file=sys.stderr)
            except Exception as e:
                print(f"  Error evaluating {filename}: {e}", file=sys.stderr)

        batch_start = time.time()
        workers = max(1, args.workers)
        if workers > 1:
            from concurrent.futures import ThreadPoolExecutor
            print(f"Executing batch evaluation with {workers} parallel worker threads...", file=sys.stderr)
            with ThreadPoolExecutor(max_workers=workers) as executor:
                list(executor.map(_process_single_resume, list(enumerate(json_files, start=1))))
        else:
            for item in enumerate(json_files, start=1):
                _process_single_resume(item)

        total_batch_time = time.time() - batch_start
        print(f"\nBatch processing completed in {total_batch_time:.2f} seconds. Output folder: {output_dir}", file=sys.stderr)

    # --- Single File Mode ---
    else:
        if not os.path.exists(single_file):
            print(f"Error: Resume JSON file not found: {single_file}", file=sys.stderr)
            sys.exit(1)

        with open(single_file, "r", encoding="utf-8") as f:
            resume_data = json.load(f)

        resume_name = os.path.splitext(os.path.basename(single_file))[0]
        evaluator.load_model()

        print(f"Evaluating single resume '{resume_name}' against HR criteria...", file=sys.stderr)

        if args.output:
            if os.path.isdir(args.output) or not args.output.endswith('.json'):
                target_dir = args.output
                target_path = os.path.join(args.output, f"{resume_name}_evaluation.json")
            else:
                target_dir = None
                target_path = args.output

            result = evaluator.evaluate_resume(
                resume_data,
                standard_req,
                hidden_req,
                resume_name=resume_name,
                output_dir=target_dir,
                output_path=target_path,
                num_evaluations=args.num_evaluations,
                resume_path=single_file,
                generate_feedback=not args.no_feedback
            )
            print(f"Saved evaluation result to: {target_path}")
        else:
            result = evaluator.evaluate_resume(
                resume_data,
                standard_req,
                hidden_req,
                resume_name=resume_name,
                num_evaluations=args.num_evaluations,
                resume_path=single_file,
                generate_feedback=not args.no_feedback
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))



if __name__ == "__main__":
    main()

