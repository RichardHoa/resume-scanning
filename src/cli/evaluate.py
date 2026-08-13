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
from src.core.config import DEFAULT_LLM_MODEL, DEFAULT_VLLM_URL
from src.pipelines.evaluator import ResumeEvaluator


def parse_args():
    parser = argparse.ArgumentParser(description="Vietnamese Resume Evaluator Agent (Step 2)")
    parser.add_argument("--resume-json", type=str, help="Path to single extracted resume JSON file")
    parser.add_argument("--dir", type=str, help="Path to directory containing extracted resume JSON files")
    parser.add_argument("--job-req", type=str, default="", help="Standard Job Requirements text or file path (splits on '---' if file contains hidden reqs)")
    parser.add_argument("--hidden-req", type=str, default="", help="Hidden Job Requirements text or file path")
    parser.add_argument("--hr-req", type=str, default="", help="Path to HR requirement file containing normal and hidden requirements separated by '---'")
    parser.add_argument("--model-name", type=str, default=DEFAULT_LLM_MODEL, help="LLM model repository or local path")
    parser.add_argument("--backend", type=str, default="transformers", choices=["transformers", "vllm"], help="Inference backend")
    parser.add_argument("--vllm-url", type=str, default=DEFAULT_VLLM_URL, help="Base URL of the vLLM OpenAI-compatible server (only used with --backend vllm)")
    parser.add_argument("--mock", action="store_true", help="Mock run without loading model weights")
    parser.add_argument("--output", type=str, help="Path to save evaluation JSON result (file path or output directory for batch mode)")
    parser.add_argument("--arr", type=str, help="Comma-separated list of resume numbers to process (e.g., --arr=6,7,8)")
    parser.add_argument("--workers", type=int, default=1, help="Number of concurrent worker threads for candidate evaluation (useful with vLLM backend)")
    parser.add_argument("--num-evaluations", "--runs", type=int, default=20, help="Number of evaluation iterations per category to calculate median (default: 20)")
    parser.add_argument("--force-reingest", action="store_true", help="Force re-ingesting HR requirements into RAG vector database")
    return parser.parse_args()



def load_requirements(args):
    """
    Loads and splits HR requirements into standard and hidden requirements.
    Supports splitting by '---' if combined in a single file like hr-requirement.txt.
    """
    standard_req = ""
    hidden_req = ""

    hr_source = args.hr_req or args.job_req

    if not hr_source:
        cwd_hr = os.path.join(os.getcwd(), "hr-requirement.txt")
        root_hr = os.path.join(_PROJECT_ROOT, "hr-requirement.txt")
        if os.path.isfile(cwd_hr):
            hr_source = cwd_hr
        elif os.path.isfile(root_hr):
            hr_source = root_hr

    if hr_source:
        raw_text = ""
        if os.path.isfile(hr_source):
            with open(hr_source, "r", encoding="utf-8") as f:
                raw_text = f.read()
        else:
            raw_text = hr_source

        if "---" in raw_text:
            parts = raw_text.split("---", 1)
            standard_req = parts[0].strip()
            hidden_req = parts[1].strip()
        else:
            standard_req = raw_text.strip()

    if args.hidden_req:
        if os.path.isfile(args.hidden_req):
            with open(args.hidden_req, "r", encoding="utf-8") as f:
                hidden_req = f.read().strip()
        else:
            hidden_req = args.hidden_req.strip()

    return standard_req, hidden_req


def main():
    args = parse_args()

    input_dir = args.dir
    single_file = args.resume_json

    # Default fallback to output_jsons if neither --resume-json nor --dir is passed
    if not single_file and not input_dir:
        cwd_output = os.path.join(os.getcwd(), "output_jsons")
        root_output = os.path.join(_PROJECT_ROOT, "output_jsons")
        if os.path.isdir(cwd_output):
            input_dir = cwd_output
        elif os.path.isdir(root_output):
            input_dir = root_output
        else:
            print("Error: You must specify either --resume-json or --dir.", file=sys.stderr)
            sys.exit(1)

    if single_file and input_dir:
        print("Error: You cannot specify both --resume-json and --dir. Please choose one.", file=sys.stderr)
        sys.exit(1)

    standard_req, hidden_req = load_requirements(args)
    if standard_req or hidden_req:
        print(f"[HR Requirements Loaded] Standard length: {len(standard_req)} chars | Hidden length: {len(hidden_req)} chars", file=sys.stderr)
    else:
        print("[HR Requirements Warning] No HR requirements file or text found. Evaluation will proceed with baseline criteria.", file=sys.stderr)

    evaluator = ResumeEvaluator(
        model_name=args.model_name,
        backend=args.backend,
        vllm_url=args.vllm_url,
        mock=args.mock
    )

    if args.force_reingest:
        evaluator.rag.clear_rag_database()

    # --- Batch Directory Mode ---
    if input_dir:
        if not os.path.isdir(input_dir):
            print(f"Error: Directory not found: {input_dir}", file=sys.stderr)
            sys.exit(1)

        output_dir = args.output or "evaluation_json"
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

        if standard_req or hidden_req:
            print("[HR Requirements] Pre-ingesting criteria into RAG vector store...", file=sys.stderr)
            evaluator.rag.ingest_requirements(
                standard_req,
                hidden_req,
                llm_decomposer_func=lambda s, h: evaluator._decompose_requirements_with_llm(s, h, "batch_init"),
                force_reingest=args.force_reingest
            )

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
                    num_evaluations=args.num_evaluations
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
                num_evaluations=args.num_evaluations
            )
            print(f"Saved evaluation result to: {target_path}")
        else:
            result = evaluator.evaluate_resume(
                resume_data,
                standard_req,
                hidden_req,
                resume_name=resume_name,
                num_evaluations=args.num_evaluations
            )
            print(json.dumps(result, ensure_ascii=False, indent=2))



if __name__ == "__main__":
    main()

