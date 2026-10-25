#!/usr/bin/env python3
"""
CLI entry point for the Bias Check (.scratch/bias-check/spec.md): whether a Category's score depends on the order its
prompt content is given in. Extracts the one fixed CnB resume from its PDF with Combined Extraction, then runs each
category's Baseline and Shuffle Kinds as production Category runs on the default model, 5 Bias Repetitions each.

The stored HR RAG must be the CnB one. Run through scripts/checks/evaluator_bias.sh, which wipes runs/bias-cnb and
serves the default model with vision on; everything is written to runs/bias-cnb.

Usage:
  # Run all 4 categories (the default):
  python3 scripts/checks/evaluator_bias.py
  python3 scripts/checks/evaluator_bias.py --all

  # Run one specific category:
  python3 scripts/checks/evaluator_bias.py --technical_skills
  python3 scripts/checks/evaluator_bias.py --seniority_title
  python3 scripts/checks/evaluator_bias.py --education_certifications
  python3 scripts/checks/evaluator_bias.py --work_experience
  python3 scripts/checks/evaluator_bias.py --category seniority_title

  # Dry-run / Validation mode (mock extraction, generates all permutations & checks prompt formatting without LLM calls):
  python3 scripts/checks/evaluator_bias.py --dry-run
"""
import os
import sys
import json
import argparse
from typing import List

# Ensure repository root is in sys.path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
os.chdir(_PROJECT_ROOT)

# The Bias Check always writes its own run folder (BIAS_RUN_FOLDER in src/core/config.py). Set before any src import:
# config builds, and creates, every path from RUN_DIR as it is imported
os.environ["RUN_DIR"] = "bias-cnb"

from src.core.config import (
    DEFAULT_LLM_MODEL, DEFAULT_VLLM_URL, RAG_DIR, RUN_DIR, EXTRACTION_JSON_DIR, PROMPT_LOGS_DIR,
    VLLM_MAX_CONCURRENT_REQUESTS
)
from src.pipelines.extractor import ResumeExtractor
from src.pipelines.evaluator import ResumeEvaluator
from src.bias.runner import MAX_EVAL_PER_SHUFFLE_KIND
from src.bias import (
    get_all_category_keys,
    log_data_provenance_report,
    run_single_category_bias_test
)
from extractor_consistency import is_scanned_pdf, extraction_error

# The one resume the Bias Check tests. It never changes, and it is a CnB resume, so the CnB HR RAG must be stored
BIAS_RESUME_NAME = "CnB - Nguyen Ho Mi Sa"
BIAS_RESUME_PDF = os.path.join(_PROJECT_ROOT, "Vietnamese-dataset", "CnB", f"{BIAS_RESUME_NAME}.pdf")


def parse_cli_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="ATS Evaluator Bias Check (default model, one fixed CnB resume)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python3 scripts/checks/evaluator_bias.py
  python3 scripts/checks/evaluator_bias.py --seniority_title
  python3 scripts/checks/evaluator_bias.py --education_certifications
  python3 scripts/checks/evaluator_bias.py --work_experience
  python3 scripts/checks/evaluator_bias.py --technical_skills
  python3 scripts/checks/evaluator_bias.py --category work_experience
  python3 scripts/checks/evaluator_bias.py --dry-run
"""
    )

    # Category Selection Group
    cat_group = parser.add_argument_group("Category Selection (default: all 4)")
    cat_group.add_argument(
        "--all",
        action="store_true",
        help="Run all 4 categories the Bias Check covers"
    )
    cat_group.add_argument(
        "--technical_skills", "--technical-skills",
        action="store_true",
        dest="technical_skills",
        help="Run technical_skills category"
    )
    cat_group.add_argument(
        "--seniority_title", "--seniority-title",
        action="store_true",
        dest="seniority_title",
        help="Run seniority_title category"
    )
    cat_group.add_argument(
        "--education_certifications", "--education-certifications",
        action="store_true",
        dest="education_certifications",
        help="Run education_certifications category"
    )
    cat_group.add_argument(
        "--work_experience", "--work-experience",
        action="store_true",
        dest="work_experience",
        help="Run work_experience category"
    )
    cat_group.add_argument(
        "--category", "-c",
        type=str,
        default=None,
        help="Run a specific category by name (e.g. seniority_title, technical_skills, etc.)"
    )

    # Execution Configuration
    exec_group = parser.add_argument_group("Execution Configuration")
    exec_group.add_argument(
        "--vllm-url",
        type=str,
        default=os.environ.get("VLLM_URL", DEFAULT_VLLM_URL),
        help=f"vLLM server API endpoint (default: {DEFAULT_VLLM_URL})"
    )
    exec_group.add_argument(
        "--seed",
        type=int,
        default=42,
        help="Random seed for deterministic atomic sampling (default: 42)"
    )
    exec_group.add_argument(
        "--atomic-sample-size",
        type=int,
        default=300,
        help="Sample size for atomic item-level interleaving (default: 300)"
    )
    exec_group.add_argument(
        "--max-eval-per-shuffle-kind", "--max-eval-per-shuffle",
        type=int,
        default=MAX_EVAL_PER_SHUFFLE_KIND,
        dest="max_eval_per_shuffle_kind",
        help=f"Maximum evaluations for any shuffle kind / permutation group (default: {MAX_EVAL_PER_SHUFFLE_KIND})"
    )
    exec_group.add_argument(
        "--dry-run",
        action="store_true",
        help="Dry run mode: mock extraction, validates permutation generation and prompt rendering without sending LLM requests"
    )

    return parser.parse_args()


def resolve_categories(args: argparse.Namespace) -> List[str]:
    """Resolves target categories list based on CLI flags; no flag runs all 4."""
    categories: List[str] = []

    if args.all:
        return get_all_category_keys()

    if args.technical_skills:
        categories.append("technical_skills")
    if args.seniority_title:
        categories.append("seniority_title")
    if args.education_certifications:
        categories.append("education_certifications")
    if args.work_experience:
        categories.append("work_experience")
    if args.category:
        norm_cat = args.category.strip().lower().replace("-", "_")
        if norm_cat not in categories:
            categories.append(norm_cat)

    # Check environment variable CATEGORY_KEY if no CLI category provided
    if not categories and os.environ.get("CATEGORY_KEY"):
        env_cat = os.environ.get("CATEGORY_KEY", "").strip().lower().replace("-", "_")
        if env_cat == "all":
            return get_all_category_keys()
        elif env_cat:
            categories.append(env_cat)

    return categories or get_all_category_keys()


def extract_bias_resume(extractor: ResumeExtractor) -> tuple:
    """
    Extracts the Bias Check's resume from its PDF, saved as extraction_json/<resume>.json in the run folder.
    Returns (json_path, data); exits non-zero when it cannot be used, since no category can run without it.
    """
    def fail(reason: str):
        print(f"[Error] Cannot extract the Bias Check resume '{BIAS_RESUME_NAME}': {reason}", file=sys.stderr)
        sys.exit(1)

    if not os.path.isfile(BIAS_RESUME_PDF):
        fail(f"its PDF is missing: {BIAS_RESUME_PDF}")
    if is_scanned_pdf(BIAS_RESUME_PDF):
        fail("it is a Scanned Resume")

    try:
        text = extractor.extract(BIAS_RESUME_PDF, log_dir=os.path.join(PROMPT_LOGS_DIR, "extraction"))
    except Exception as e:
        fail(f"extraction raised: {e}")
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        fail("invalid JSON after all retries")

    json_path = os.path.join(EXTRACTION_JSON_DIR, f"{BIAS_RESUME_NAME}.json")
    with open(json_path, "w", encoding="utf-8") as f:
        f.write(text)
    error = extraction_error(data)
    if error:
        fail(error)
    return json_path, data


def main():
    args = parse_cli_args()
    categories_to_run = resolve_categories(args)

    # 1. Extract the resume from scratch, so the check always tests what production extracts today
    extractor = ResumeExtractor(model_name=DEFAULT_LLM_MODEL, vllm_url=args.vllm_url, mock=args.dry_run)
    extractor.load_model()
    target_resume_path, resume_data = extract_bias_resume(extractor)

    # 2. Initialize Evaluator & RAG
    evaluator = ResumeEvaluator(
        model_name=DEFAULT_LLM_MODEL,
        vllm_url=args.vllm_url,
        mock=args.dry_run
    )
    evaluator.load_model()

    rag_db_path = os.path.join(RAG_DIR, "chroma_db")
    # Evaluation never builds or changes the HR RAG: HR sets it on the RAG page first
    try:
        evaluator.rag.require_stored_rag()
    except RuntimeError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    rag_status = "Collection loaded from persistent ChromaDB (must be the CnB HR RAG)"

    # 3. Transparent Provenance Logging
    log_data_provenance_report(
        resume_path=target_resume_path,
        resume_data=resume_data,
        rag_dir=rag_db_path,
        rag_status=rag_status,
        categories_to_run=categories_to_run
    )

    # 4. Execute Selected Categories; a failed category is reported and the rest still run
    overall_summaries = []
    failed_categories = []
    for cat_key in categories_to_run:
        try:
            summary = run_single_category_bias_test(
                category_key=cat_key,
                evaluator=evaluator,
                resume_data=resume_data,
                resume_path=target_resume_path,
                concurrency=VLLM_MAX_CONCURRENT_REQUESTS,
                seed=args.seed,
                atomic_sample_size=args.atomic_sample_size,
                max_eval_per_shuffle_kind=args.max_eval_per_shuffle_kind,
                dry_run=args.dry_run
            )
        except RuntimeError as e:
            print(f"[Error] Category '{cat_key}' failed: {e}", file=sys.stderr)
            failed_categories.append(cat_key)
            continue
        overall_summaries.append(summary)

    # 5. Combined Suite Report if multiple categories tested
    if len(categories_to_run) > 1:
        print("\n" + "#" * 86, file=sys.stderr)
        print(" 🏆 OVERALL BIAS CHECK MULTI-CATEGORY REPORT", file=sys.stderr)
        print("#" * 86, file=sys.stderr)
        print(f" {'Category':<28s} | {'Runs':<10s} | {'Baseline':<8s} | {'Score Range':<14s} | {'Spread (Δ)':<10s}", file=sys.stderr)
        print("-" * 86, file=sys.stderr)
        for s in overall_summaries:
            cat_name = s.get("category_name", s.get("category_key", "N/A"))
            if s.get("not_applicable"):
                print(f" {cat_name:<28s} | {'-':<10s} | {'-':<8s} | {'-':<14s} | Not Applicable", file=sys.stderr)
                continue
            tot_runs = s.get("total_runs", s.get("total_iterations", 0))
            if s.get("dry_run"):
                print(f" {cat_name:<28s} | {tot_runs:<10,d} | {'DRY-RUN':<8s} | {'[N/A]':<14s} | {'[DRY-RUN]':<10s}", file=sys.stderr)
            else:
                base_sc = s.get("baseline_score", 0)
                min_sc = s.get("min_score", 0)
                max_sc = s.get("max_score", 0)
                spread = s.get("total_spread_delta", 0)
                print(f" {cat_name:<28s} | {tot_runs:<10,d} | {base_sc:<8d} | [{min_sc:3d} - {max_sc:3d}]     | Δ = {spread:2d} pts", file=sys.stderr)
        for cat_key in failed_categories:
            print(f" {cat_key:<28s} | FAILED (see the error above)", file=sys.stderr)
        print("#" * 86, file=sys.stderr)

    print(f"Results: {RUN_DIR}", file=sys.stderr)
    if failed_categories:
        sys.exit(1)


if __name__ == "__main__":
    main()
