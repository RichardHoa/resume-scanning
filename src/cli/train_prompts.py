"""
CLI Entrypoint for DSPy Evaluator Prompt Training & Optimization (Technique A)
"""
import os
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import json
import argparse
from src.core.config import DEFAULT_LLM_MODEL, DEFAULT_VLLM_URL, DSPY_MAX_TOKENS
from src.optimization.dspy_evaluator import (
    load_candidate_ground_truth,
    calculate_category_metric,
    run_dspy_optimization,
    HAS_DSPY
)


def parse_args():
    parser = argparse.ArgumentParser(description="DSPy Prompt Training & Accuracy Optimizer for Resume Evaluator")
    parser.add_argument("--dataset", type=str, default=os.path.join(_PROJECT_ROOT, "data", "candidate_ground_truth.json"),
                        help="Path to candidate ground truth dataset JSON")
    parser.add_argument("--model-name", type=str, default=DEFAULT_LLM_MODEL,
                        help="LLM model name or HF repository")
    parser.add_argument("--vllm-url", type=str, default=DEFAULT_VLLM_URL,
                        help="vLLM server endpoint URL")
    parser.add_argument("--output-jsons", type=str, default=os.path.join(_PROJECT_ROOT, "output_jsons"),
                        help="Path to extracted candidate resume JSONs directory (default: output_jsons)")
    parser.add_argument("--eval-dir", type=str, default=os.path.join(_PROJECT_ROOT, "evaluation_results"),
                        help="Path to candidate evaluation reports directory for scoring (default: evaluation_results)")
    parser.add_argument("--output-prompt", type=str, default=os.path.join(_PROJECT_ROOT, "prompts", "dspy_compiled_prompt.json"),
                        help="Output path for compiled DSPy prompt artifact")
    parser.add_argument("--mode", type=str, choices=["train", "eval-dataset", "summary", "view-prompt"], default="summary",
                        help="Operation mode: 'summary' (view dataset breakdown), 'eval-dataset' (score existing output against dataset), 'train' (run DSPy teleprompter), 'view-prompt' (inspect full compiled evaluator system prompt)")
    parser.add_argument("--teleprompter", type=str, choices=["bootstrap", "copro", "mipro"], default="mipro",
                        help="DSPy teleprompter optimizer algorithm: 'mipro' (jointly optimizes prompt directives & exemplars, default), 'copro' (rewrites system prompt directives), 'bootstrap' (optimizes few-shot exemplars)")
    parser.add_argument("--auto-preset", type=str, choices=["light", "medium", "heavy"], default="heavy",
                        help="MIPROv2 auto tuning preset: 'light' (~10 trials), 'medium' (~30 trials), 'heavy' (~50+ trials, default)")
    parser.add_argument("--num-threads", "--max-threads", type=int, default=8,
                        help="Number of concurrent parallel worker threads for vLLM request evaluation (default: 8)")
    parser.add_argument("--eval-runs-per-category", type=int, default=1,
                        help="Number of evaluation runs per category during DSPy training to compute median score (default: 1)")
    parser.add_argument("--max-tokens", type=int, default=DSPY_MAX_TOKENS,
                        help=f"Max output tokens for DSPy LM completions (default: {DSPY_MAX_TOKENS})")
    parser.add_argument("--language", type=str, default="vietnamese", choices=["vietnamese", "english"],
                        help="Language for system prompt output directives")
    parser.add_argument("--prompt-temp", type=float, default=0.35,
                        help="Sampling temperature for prompt instruction model (default: 0.35 to prevent looping)")
    parser.add_argument("--prompt-rep-penalty", type=float, default=1.15,
                        help="Repetition penalty for prompt instruction model (default: 1.15)")
    return parser.parse_args()


def display_dataset_summary(dataset_path: str):
    gt = load_candidate_ground_truth(dataset_path)
    info = gt.get("dataset_info", {})
    candidates = gt.get("candidates", [])

    tier_1_cands = [c for c in candidates if c.get("tier") == 1]
    tier_2_cands = [c for c in candidates if c.get("tier") == 2]
    tier_3_cands = [c for c in candidates if c.get("tier") == 3]

    print("\n" + "="*80)
    print(f" CANDIDATE GROUND TRUTH DATASET SUMMARY: {info.get('name', 'Ground Truth')}")
    print("="*80)
    print(f"Total Candidates: {len(candidates)}")
    print(f"  ├── Tier 1 (Highly Match   - STRONG_MATCH   ): {len(tier_1_cands)} candidates")
    print(f"  ├── Tier 2 (Potential Match- POTENTIAL_MATCH): {len(tier_2_cands)} candidates")
    print(f"  └── Tier 3 (Low Match      - LOW_MATCH      ): {len(tier_3_cands)} candidates")
    print("-"*80)

    print("\n[Tier 1: Highly Match Candidates]")
    for c in tier_1_cands:
        print(f"  • Email: {c.get('email') or 'N/A':<35} | File: {c.get('filename')}")

    print("\n[Tier 2: Potential Match Candidates]")
    for c in tier_2_cands:
        print(f"  • Email: {c.get('email') or 'N/A':<35} | File: {c.get('filename')}")

    print(f"\n[Tier 3: Low Match Candidates ({len(tier_3_cands)} total)]")
    for c in tier_3_cands[:5]:
        print(f"  • File: {c.get('filename')}")
    if len(tier_3_cands) > 5:
        print(f"  ... and {len(tier_3_cands) - 5} more files")
    print("="*80 + "\n")


def evaluate_existing_dataset(dataset_path: str, eval_dir: str, output_jsons_dir: str):
    """Evaluates candidate evaluation JSON results against ground truth labels."""
    gt = load_candidate_ground_truth(dataset_path)
    candidates = gt.get("candidates", [])

    print("\n" + "="*80)
    print(f" EVALUATING CANDIDATE RESULTS AGAINST GROUND TRUTH DATASET")
    print("="*80)
    print(f"Dataset Path: {dataset_path} ({len(candidates)} candidates)")
    print(f"Evaluation Search Dirs: {eval_dir}, {output_jsons_dir}")
    print("-"*80)

    matched = 0
    total_evaluated = 0
    metric_scores = []
    results_table = []

    for c in candidates:
        fn = c.get("filename", "")
        base_name = os.path.splitext(fn)[0] if fn else ""
        target_cat = c.get("target_category", "LOW_MATCH")
        target_tier = c.get("tier", 3)

        # Look for evaluation files in eval_dir and output_jsons_dir
        candidate_paths = [
            os.path.join(eval_dir, f"{base_name}_evaluation.json"),
            os.path.join(eval_dir, f"{base_name}.json"),
            os.path.join(output_jsons_dir, f"{base_name}_evaluation.json"),
            os.path.join(output_jsons_dir, f"{base_name}.json"),
        ]
        # Also check sanitized filenames
        sanitized = os.path.splitext(fn)[0].replace(" ", "_")
        candidate_paths.extend([
            os.path.join(eval_dir, f"{sanitized}_evaluation.json"),
            os.path.join(eval_dir, f"{sanitized}.json"),
            os.path.join(output_jsons_dir, f"{sanitized}_evaluation.json"),
            os.path.join(output_jsons_dir, f"{sanitized}.json"),
        ])

        eval_data = None
        for p in candidate_paths:
            if os.path.exists(p):
                try:
                    with open(p, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    if "overall_score" in data or "evaluation_summary" in data:
                        eval_data = data
                        break
                except Exception:
                    pass

        if eval_data:
            total_evaluated += 1
            score = eval_data.get("overall_score", 0.0)
            if isinstance(score, dict):
                score = score.get("overall_score", 0.0)
            try:
                score_val = float(score)
            except (ValueError, TypeError):
                score_val = 0.0

            pred_cat = eval_data.get("match_recommendation", "")
            if not pred_cat:
                if score_val >= 85:
                    pred_cat = "STRONG_MATCH"
                elif score_val >= 70:
                    pred_cat = "POTENTIAL_MATCH"
                else:
                    pred_cat = "LOW_MATCH"

            m_score = calculate_category_metric(score_val, target_cat)
            metric_scores.append(m_score)
            is_match = (pred_cat == target_cat)
            if is_match:
                matched += 1

            results_table.append({
                "filename": fn,
                "target_tier": target_tier,
                "target_cat": target_cat,
                "pred_score": score_val,
                "pred_cat": pred_cat,
                "match": "MATCH" if is_match else "MISMATCH",
                "metric": m_score
            })

    if total_evaluated == 0:
        print(f"[Notice] No evaluation JSON files found in {eval_dir} or {output_jsons_dir}.")
        print("Run batch evaluation first to generate evaluation JSONs.")
        display_dataset_summary(dataset_path)
        return

    accuracy = (matched / total_evaluated) * 100.0
    avg_metric = (sum(metric_scores) / len(metric_scores)) if metric_scores else 0.0

    print(f"\n{'Candidate File':<40} | {'Target':<15} | {'Predicted':<15} | {'Score':<6} | {'Status'}")
    print("-" * 88)
    for r in results_table:
        print(f"{r['filename'][:38]:<40} | {r['target_cat']:<15} | {r['pred_cat']:<15} | {r['pred_score']:<6.1f} | {r['match']}")

    print("="*88)
    print(f"EVALUATION METRIC SUMMARY:")
    print(f"  • Total Candidates Evaluated: {total_evaluated}/{len(candidates)}")
    print(f"  • Exact Category Match Accuracy: {accuracy:.2f}% ({matched}/{total_evaluated})")
    print(f"  • Average Continuous Metric Score: {avg_metric:.4f} (0.0 to 1.0)")
    print("="*88 + "\n")


def display_compiled_prompt(compiled_path: str, language: str = "vietnamese"):
    from src.prompts.evaluator_prompts import load_dspy_compiled_prompt, get_evaluator_system_prompt

    compiled_info = load_dspy_compiled_prompt(compiled_path)
    opt_inst = compiled_info.get("system_instruction")
    demos = compiled_info.get("demos", [])
    few_shot_block = compiled_info.get("few_shot_block", "")

    print("\n" + "="*80)
    print(" DSPY EVALUATOR COMPILED PROMPT INSPECTION")
    print("="*80)
    print(f"Compiled File Location: {compiled_path}")
    print(f"File Exists: {os.path.exists(compiled_path)}")
    print(f"DSPy Optimized System Instruction Present: {opt_inst is not None}")
    if opt_inst:
        print(f"  └── Instruction Length: {len(opt_inst)} characters")
    print(f"Few-Shot Benchmark Exemplars Count: {len(demos)}")
    print("="*80)

    if opt_inst:
        print("\n" + "-"*80)
        print("[STANDALONE DSPY OPTIMIZED SYSTEM INSTRUCTION]:")
        print("-"*80)
        print(opt_inst)

    if few_shot_block:
        print("\n" + "-"*80)
        print("[STANDALONE DSPY FEW-SHOT EXEMPLARS]:")
        print("-"*80)
        print(few_shot_block)

    base_system_prompt = get_evaluator_system_prompt(language=language)
    print("\n" + "-"*80)
    print("[BASE EVALUATOR SYSTEM PROMPT]:")
    print("-"*80)
    print(base_system_prompt)
    print("\n" + "="*80 + "\n")


def main():
    args = parse_args()

    if args.mode == "summary":
        display_dataset_summary(args.dataset)
    elif args.mode == "view-prompt":
        display_compiled_prompt(args.output_prompt, language=args.language)
    elif args.mode == "train":
        if not HAS_DSPY:
            print("[Error] DSPy (dspy-ai) is not installed on this machine.", file=sys.stderr)
            print("Please run DSPy prompt training on your GPU node using:", file=sys.stderr)
            print("  pip install dspy-ai", file=sys.stderr)
            print(f"  python3 src/cli/train_prompts.py --mode train --teleprompter {args.teleprompter} --auto-preset {args.auto_preset} --num-threads {args.num_threads} --model-name {args.model_name} --vllm-url {args.vllm_url}", file=sys.stderr)
            sys.exit(1)
        run_dspy_optimization(
            model_name=args.model_name,
            vllm_url=args.vllm_url,
            dataset_path=args.dataset,
            output_jsons_dir=args.output_jsons,
            output_compiled_path=args.output_prompt,
            teleprompter_type=args.teleprompter,
            auto_preset=args.auto_preset,
            num_threads=args.num_threads,
            eval_runs_per_category=args.eval_runs_per_category,
            max_tokens=args.max_tokens,
            language=args.language,
            prompt_temp=args.prompt_temp,
            prompt_rep_penalty=args.prompt_rep_penalty
        )
    elif args.mode == "eval-dataset":
        evaluate_existing_dataset(args.dataset, args.eval_dir, args.output_jsons)


if __name__ == "__main__":
    main()
