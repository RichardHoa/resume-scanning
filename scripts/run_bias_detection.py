#!/usr/bin/env python3
"""
CLI entry point for Bias & Positional Order Sensitivity Detection.
Executes exhaustive permutation suites defined in docs/bias_detection_plan.md.

Usage:
  # Run the 3 remaining categories (seniority_title, education_certifications, work_experience):
  python3 scripts/run_bias_detection.py --remaining

  # Run all 4 categories:
  python3 scripts/run_bias_detection.py --all

  # Run one specific category:
  python3 scripts/run_bias_detection.py --technical_skills
  python3 scripts/run_bias_detection.py --seniority_title
  python3 scripts/run_bias_detection.py --education_certifications
  python3 scripts/run_bias_detection.py --work_experience
  python3 scripts/run_bias_detection.py --category seniority_title

  # Dry-run / Validation mode (generates all permutations & checks prompt formatting without LLM calls):
  python3 scripts/run_bias_detection.py --remaining --dry-run
"""
import os
import sys
import json
import argparse
from typing import List, Dict, Any

# Ensure repository root is in sys.path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
os.chdir(_PROJECT_ROOT)

from src.core.config import DEFAULT_LLM_MODEL, DEFAULT_VLLM_URL, RAG_DIR
from src.pipelines.evaluator import ResumeEvaluator
from src.bias import (
    get_bias_builder,
    get_all_category_keys,
    get_remaining_category_keys,
    locate_candidate_resume,
    log_data_provenance_report,
    run_single_category_bias_test
)


def parse_cli_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="ATS Evaluator Bias & Positional Sensitivity Detection Suite",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""Examples:
  python3 scripts/run_bias_detection.py --remaining
  python3 scripts/run_bias_detection.py --all
  python3 scripts/run_bias_detection.py --seniority_title
  python3 scripts/run_bias_detection.py --education_certifications
  python3 scripts/run_bias_detection.py --work_experience
  python3 scripts/run_bias_detection.py --technical_skills
  python3 scripts/run_bias_detection.py --category work_experience
  python3 scripts/run_bias_detection.py --remaining --dry-run
"""
    )

    # Category Selection Group
    cat_group = parser.add_argument_group("Category Selection")
    cat_group.add_argument(
        "--remaining",
        action="store_true",
        help="Run the 3 remaining categories except technical_skills (seniority_title, education_certifications, work_experience)"
    )
    cat_group.add_argument(
        "--all",
        action="store_true",
        help="Run all 4 evaluation categories tracked in bias_detection_plan.md"
    )
    cat_group.add_argument(
        "--technical_skills", "--technical-skills",
        action="store_true",
        dest="technical_skills",
        help="Run technical_skills category (5,587 iterations)"
    )
    cat_group.add_argument(
        "--seniority_title", "--seniority-title",
        action="store_true",
        dest="seniority_title",
        help="Run seniority_title category (5,491 iterations)"
    )
    cat_group.add_argument(
        "--education_certifications", "--education-certifications",
        action="store_true",
        dest="education_certifications",
        help="Run education_certifications category (549 to 667 iterations)"
    )
    cat_group.add_argument(
        "--work_experience", "--work-experience",
        action="store_true",
        dest="work_experience",
        help="Run work_experience category (5,589 iterations)"
    )
    cat_group.add_argument(
        "--category", "-c",
        type=str,
        default=None,
        help="Run a specific category by name (e.g. seniority_title, technical_skills, etc.)"
    )

    # Execution & Environment Configuration
    exec_group = parser.add_argument_group("Execution & Model Configuration")
    exec_group.add_argument(
        "--resume-path", "-r",
        type=str,
        default=None,
        help="Explicit path to candidate resume JSON file (default: auto-detected in output_jsons/)"
    )
    exec_group.add_argument(
        "--concurrency",
        type=int,
        default=int(os.environ.get("CONCURRENCY", "70")),
        help="Number of concurrent worker threads (default: 70 or CONCURRENCY env var)"
    )
    exec_group.add_argument(
        "--model", "-m",
        type=str,
        default=os.environ.get("MODEL_NAME", DEFAULT_LLM_MODEL),
        help=f"Target LLM model name (default: {DEFAULT_LLM_MODEL})"
    )
    exec_group.add_argument(
        "--backend", "-b",
        type=str,
        default=os.environ.get("BACKEND", "vllm"),
        choices=["vllm", "transformers"],
        help="Model inference backend (default: vllm)"
    )
    exec_group.add_argument(
        "--vllm-url",
        type=str,
        default=os.environ.get("VLLM_URL", DEFAULT_VLLM_URL),
        help=f"vLLM server API endpoint (default: {DEFAULT_VLLM_URL})"
    )
    exec_group.add_argument(
        "--seed",
        type=int,
        default=int(os.environ.get("BASE_SEED", "42")),
        help="Random seed for deterministic atomic sampling (default: 42)"
    )
    exec_group.add_argument(
        "--atomic-sample-size",
        type=int,
        default=int(os.environ.get("ATOMIC_SAMPLE_SIZE", "300")),
        help="Sample size for atomic item-level interleaving (default: 300)"
    )
    exec_group.add_argument(
        "--max-eval-per-shuffle-kind", "--max-eval-per-shuffle",
        type=int,
        default=int(os.environ.get("MAX_EVAL_PER_SHUFFLE_KIND", "100")),
        dest="max_eval_per_shuffle_kind",
        help="Maximum evaluations for any shuffle kind / permutation group (default: 100)"
    )
    exec_group.add_argument(
        "--dry-run",
        action="store_true",
        help="Dry run mode: validates permutation generation and prompt rendering without sending LLM requests"
    )

    return parser.parse_args()


def resolve_categories(args: argparse.Namespace) -> List[str]:
    """Resolves target categories list based on CLI flags."""
    categories: List[str] = []

    if args.all:
        return get_all_category_keys()

    if args.remaining:
        return get_remaining_category_keys()

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
        elif env_cat == "remaining":
            return get_remaining_category_keys()
        elif env_cat:
            categories.append(env_cat)

    # Default fallback: If zero flags specified, run --remaining as requested
    if not categories:
        print("[Notice] No category flag specified. Defaulting to '--remaining' (seniority_title, education_certifications, work_experience).", file=sys.stderr)
        return get_remaining_category_keys()

    return categories


def main():
    os.environ["DISABLE_PROMPT_LOGGING"] = "1"
    args = parse_cli_args()
    categories_to_run = resolve_categories(args)

    # 1. Locate and Load Candidate Resume JSON
    target_resume_path = locate_candidate_resume(_PROJECT_ROOT, args.resume_path)
    with open(target_resume_path, "r", encoding="utf-8") as f:
        resume_data = json.load(f)

    # 2. Initialize Evaluator & RAG
    evaluator = ResumeEvaluator(
        model_name=args.model,
        backend=args.backend,
        vllm_url=args.vllm_url,
        mock=args.dry_run
    )
    if not args.dry_run:
        evaluator.load_model()

    rag_db_path = os.path.join(RAG_DIR, "chroma_db")
    rag_status = "Collection loaded from persistent ChromaDB" if evaluator.rag.has_stored_rag() else "Empty (auto-ingesting from hr-requirement.txt)"

    if not evaluator.rag.has_stored_rag():
        hr_req_file = os.path.join(_PROJECT_ROOT, "hr-requirement.txt")
        if os.path.isfile(hr_req_file):
            print(f"[RAG Ingestion] Ingesting requirements from {hr_req_file}...", file=sys.stderr)
            with open(hr_req_file, "r", encoding="utf-8") as f:
                standard_req = f.read()
            evaluator.rag.ingest_requirements(
                standard_req,
                "",
                llm_decomposer_func=lambda s, h: evaluator._decompose_requirements_with_llm(s, h, "bias_init")
            )
            rag_status = f"Ingested from {hr_req_file}"

    # 3. Transparent Provenance Logging
    log_data_provenance_report(
        resume_path=target_resume_path,
        resume_data=resume_data,
        rag_dir=rag_db_path,
        rag_status=rag_status,
        categories_to_run=categories_to_run
    )

    # 4. Execute Selected Categories
    overall_summaries = []
    for cat_key in categories_to_run:
        summary = run_single_category_bias_test(
            category_key=cat_key,
            evaluator=evaluator,
            resume_data=resume_data,
            resume_path=target_resume_path,
            project_root=_PROJECT_ROOT,
            concurrency=args.concurrency,
            seed=args.seed,
            atomic_sample_size=args.atomic_sample_size,
            max_eval_per_shuffle_kind=args.max_eval_per_shuffle_kind,
            dry_run=args.dry_run
        )
        overall_summaries.append(summary)

    # 5. Combined Suite Report if multiple categories tested
    if len(categories_to_run) > 1:
        print("\n" + "#" * 86, file=sys.stderr)
        print(" 🏆 OVERALL BIAS DETECTION MULTI-CATEGORY SUITE REPORT", file=sys.stderr)
        print("#" * 86, file=sys.stderr)
        print(f" {'Category':<28s} | {'Iterations':<10s} | {'Baseline':<8s} | {'Score Range':<14s} | {'Spread (Δ)':<10s}", file=sys.stderr)
        print("-" * 86, file=sys.stderr)
        for s in overall_summaries:
            cat_name = s.get("category_name", s.get("category_key", "N/A"))
            tot_runs = s.get("total_runs", 0)
            if s.get("dry_run"):
                print(f" {cat_name:<28s} | {tot_runs:<10,d} | {'DRY-RUN':<8s} | {'[N/A]':<14s} | {'[DRY-RUN]':<10s}", file=sys.stderr)
            else:
                base_sc = s.get("baseline_score", 0)
                min_sc = s.get("min_score", 0)
                max_sc = s.get("max_score", 0)
                spread = s.get("total_spread_delta", 0)
                print(f" {cat_name:<28s} | {tot_runs:<10,d} | {base_sc:<8d} | [{min_sc:3d} - {max_sc:3d}]     | Δ = {spread:2d} pts", file=sys.stderr)
        print("#" * 86, file=sys.stderr)


if __name__ == "__main__":
    main()
