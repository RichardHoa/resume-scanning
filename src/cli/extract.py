"""
CLI Entrypoint for Step 1 Resume Extractor
"""
import os
import sys

# Ensure repository root is in sys.path for 'src' package imports
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import argparse
import time
import re
from src.core.config import DEFAULT_VLLM_URL, APPROVED_DIR
from src.pipelines.extractor import ResumeExtractor


def parse_args():
    parser = argparse.ArgumentParser(description="Vietnamese Resume Extractor (Step 1)")
    parser.add_argument("--pdf", type=str, help="Path to a single PDF resume file")
    parser.add_argument("--dir", type=str, help="Path to a directory containing PDF resumes to scan")
    parser.add_argument("--model-name", type=str, default="Qwen/Qwen3.5-9B",
                        help="Model repository name or local path")
    parser.add_argument("--mock", action="store_true",
                        help="Mock run: performs text extraction and returns mock JSON output without loading the model")
    parser.add_argument("--output", type=str, help="Path to save the JSON output file (or output directory if --dir is used)")
    parser.add_argument("--arr", type=str,
                        help="Comma-separated list of resume numbers to process (e.g., --arr=6,7,8,10)")
    parser.add_argument("--approved", action="store_true",
                        help="Only process PDFs that have a corresponding ground truth JSON in approved_jsons")
    parser.add_argument("--backend", type=str, default="transformers", choices=["transformers", "vllm"],
                        help="Inference backend: 'transformers' (load model locally) or 'vllm' (call a running vLLM server)")
    parser.add_argument("--vllm-url", type=str, default=DEFAULT_VLLM_URL,
                        help="Base URL of the vLLM OpenAI-compatible server (only used with --backend vllm)")
    parser.add_argument("--language", type=str, default="vietnamese", choices=["vietnamese", "english"],
                        help="Target parse language: 'vietnamese' (default) or 'english'")
    return parser.parse_args()


def main():
    args = parse_args()

    if not args.pdf and not args.dir:
        print("Error: You must specify either --pdf or --dir.", file=sys.stderr)
        sys.exit(1)
    if args.pdf and args.dir:
        print("Error: You cannot specify both --pdf and --dir. Please choose one.", file=sys.stderr)
        sys.exit(1)

    extractor = ResumeExtractor(
        model_name=args.model_name, mock=args.mock,
        backend=args.backend, vllm_url=args.vllm_url
    )
    if not args.mock and args.backend == "transformers":
        extractor.load_model()

    if args.pdf:
        if args.approved:
            pdf_basename = os.path.splitext(os.path.basename(args.pdf))[0]
            approved_path = os.path.join(APPROVED_DIR, pdf_basename + ".json")
            if not os.path.exists(approved_path):
                print(f"Skipping {args.pdf} because corresponding approved JSON {approved_path} does not exist.", file=sys.stderr)
                sys.exit(0)

        if args.arr:
            try:
                arr_indices = {int(x.strip()) for x in args.arr.split(",") if x.strip()}
            except ValueError:
                print("Error: --arr must be a comma-separated list of integers.", file=sys.stderr)
                sys.exit(1)
            pdf_basename = os.path.splitext(os.path.basename(args.pdf))[0]
            match = re.search(r'vietnamese_resume_(\d+)', pdf_basename, re.IGNORECASE)
            if not match or int(match.group(1)) not in arr_indices:
                print(f"Error: {args.pdf} does not match the filter in --arr ({args.arr}).", file=sys.stderr)
                sys.exit(1)

        start_time = time.time()
        try:
            formatted_json = extractor.extract(args.pdf, language=args.language)
        except Exception as e:
            print(f"Error during extraction: {e}", file=sys.stderr)
            sys.exit(1)

        if args.output:
            with open(args.output, "w", encoding="utf-8") as f:
                f.write(formatted_json)
            elapsed = time.time() - start_time
            print(f"Successfully saved JSON extraction to {args.output} (took {elapsed:.2f} seconds)", file=sys.stderr)
        else:
            print(formatted_json)
            elapsed = time.time() - start_time
            print(f"Processed in {elapsed:.2f} seconds", file=sys.stderr)

    else:
        if not args.output:
            print("Error: --output is required when scanning a directory using --dir.", file=sys.stderr)
            sys.exit(1)

        if not os.path.isdir(args.dir):
            print(f"Error: Input directory {args.dir} does not exist or is not a directory.", file=sys.stderr)
            sys.exit(1)

        os.makedirs(args.output, exist_ok=True)
        pdf_files = [f for f in os.listdir(args.dir) if f.lower().endswith('.pdf')]

        if args.approved:
            pdf_files = [
                f for f in pdf_files
                if os.path.exists(os.path.join(APPROVED_DIR, os.path.splitext(f)[0] + ".json"))
            ]

        if args.arr:
            try:
                arr_indices = {int(x.strip()) for x in args.arr.split(",") if x.strip()}
            except ValueError:
                print("Error: --arr must be a comma-separated list of integers.", file=sys.stderr)
                sys.exit(1)

            def is_approved_resume(fn):
                m = re.search(r'vietnamese_resume_(\d+)', fn, re.IGNORECASE)
                return m and int(m.group(1)) in arr_indices

            pdf_files = [f for f in pdf_files if is_approved_resume(f)]

        if not pdf_files:
            print(f"No PDF files found in {args.dir}.", file=sys.stderr)
            sys.exit(0)

        pdf_files.sort()
        print(f"Found {len(pdf_files)} PDF files in {args.dir}. Starting batch processing...", file=sys.stderr)

        for idx, filename in enumerate(pdf_files, start=1):
            pdf_path = os.path.join(args.dir, filename)
            output_filename = os.path.splitext(filename)[0] + ".json"
            output_path = os.path.join(args.output, output_filename)

            print(f"\n[{idx}/{len(pdf_files)}] Processing {filename}...", file=sys.stderr)
            start_time = time.time()
            try:
                formatted_json = extractor.extract(pdf_path, language=args.language)
                with open(output_path, "w", encoding="utf-8") as f:
                    f.write(formatted_json)
                elapsed = time.time() - start_time
                print(f"  Successfully saved JSON extraction to {output_path} (took {elapsed:.2f} seconds)", file=sys.stderr)

            except Exception as e:
                elapsed = time.time() - start_time
                print(f"  Error processing {filename} (failed after {elapsed:.2f} seconds): {e}", file=sys.stderr)

        print("\nBatch processing completed.", file=sys.stderr)


if __name__ == "__main__":
    main()
