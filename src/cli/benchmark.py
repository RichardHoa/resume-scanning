"""
CLI Entrypoint for Ground Truth Accuracy Evaluation Benchmark
"""
import os
import sys

# Ensure repository root is in sys.path for 'src' package imports
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import json
import argparse
import numpy as np
from src.metrics.embedding import HAS_TORCH_TRANSFORMERS, EmbeddingEvaluator, LexicalEvaluator
from src.metrics.lexical import evaluate_json_pair


def main():
    parser = argparse.ArgumentParser(description="Structured JSON Accuracy Evaluator for Resume Extraction")
    parser.add_argument("--gt-dir", type=str, default="approved_jsons",
                        help="Path to directory containing ground truth JSON files")
    parser.add_argument("--pred-dir", type=str, default="output_jsons",
                        help="Path to directory containing generated predicted JSON files")
    parser.add_argument("--model-name", type=str, default="AITeamVN/Vietnamese_Embedding",
                        help="Hugging Face embedding model or local directory path")
    args = parser.parse_args()

    if not os.path.exists(args.gt_dir):
        print(f"Error: Ground truth directory '{args.gt_dir}' does not exist.", file=sys.stderr)
        sys.exit(1)
        
    if not os.path.exists(args.pred_dir):
        print(f"Error: Predictions directory '{args.pred_dir}' does not exist.", file=sys.stderr)
        sys.exit(1)

    if HAS_TORCH_TRANSFORMERS:
        evaluator = EmbeddingEvaluator(args.model_name)
    else:
        evaluator = LexicalEvaluator()

    gt_files = [f for f in os.listdir(args.gt_dir) if f.lower().endswith('.json')]
    if not gt_files:
        print(f"No JSON files found in ground truth directory '{args.gt_dir}'.", file=sys.stderr)
        sys.exit(0)

    gt_files.sort()
    file_scores = {}
    missing_predictions = []

    print("\nComparing predicted JSONs against ground truth...", file=sys.stderr)
    
    for filename in gt_files:
        gt_path = os.path.join(args.gt_dir, filename)
        pred_path = os.path.join(args.pred_dir, filename)
        
        try:
            with open(gt_path, 'r', encoding='utf-8') as f:
                gt_data = json.load(f)
        except Exception as e:
            print(f"Error reading ground truth '{filename}': {e}", file=sys.stderr)
            continue
            
        if not os.path.exists(pred_path):
            missing_predictions.append(filename)
            file_scores[filename] = {
                "position_applied": 0.0, "self_evaluation": 0.0, "basic_information": 0.0,
                "skills_and_specialties": 0.0, "certifications": 0.0, "languages": 0.0,
                "work_experience": 0.0, "education_background": 0.0, "projects": 0.0, "overall": 0.0
            }
            continue

        try:
            with open(pred_path, 'r', encoding='utf-8') as f:
                pred_data = json.load(f)
        except Exception as e:
            print(f"Warning: Failed to parse prediction '{filename}' as JSON: {e}", file=sys.stderr)
            file_scores[filename] = {
                "position_applied": 0.0, "self_evaluation": 0.0, "basic_information": 0.0,
                "skills_and_specialties": 0.0, "certifications": 0.0, "languages": 0.0,
                "work_experience": 0.0, "education_background": 0.0, "projects": 0.0, "overall": 0.0
            }
            continue

        scores = evaluate_json_pair(gt_data, pred_data, evaluator)
        file_scores[filename] = scores
        print(f"  Processed {filename}: Overall Score = {scores['overall']:.4f}", file=sys.stderr)

    categories = [
        "position_applied", "self_evaluation", "basic_information",
        "skills_and_specialties", "certifications", "languages",
        "work_experience", "education_background", "projects", "overall"
    ]
    
    aggregates = {cat: [] for cat in categories}
    for filename, scores in file_scores.items():
        for cat in categories:
            aggregates[cat].append(scores[cat])

    print("\n" + "="*80)
    print(" DETAILED PER-FILE SCORES")
    print("="*80)
    for filename in sorted(file_scores.keys()):
        scores = file_scores[filename]
        print(f"File: {filename}")
        print(f"  Overall Score: {scores['overall']:.4f}")
        for cat in categories[:-1]:
            display_name = cat.replace("_", " ").title()
            print(f"    - {display_name:<25}: {scores[cat]:.4f}")
        print("-" * 50)

    print("\n" + "="*80)
    print(" EVALUATION RESULTS SUMMARY")
    print("="*80)
    print(f"Total Ground Truth Files : {len(gt_files)}")
    print(f"Matched Predictions      : {len(gt_files) - len(missing_predictions)}")
    print(f"Missing Predictions      : {len(missing_predictions)}")
    if missing_predictions:
        print(f"  Missing files: {', '.join(missing_predictions)}")
    print("-"*80)
    
    print(f"{'Category/Section':<28} | {'Average Accuracy/F1 Score':<25}")
    print("-"*80)
    for cat in categories:
        avg_score = np.mean(aggregates[cat])
        display_name = cat.replace("_", " ").title()
        if cat == "overall":
            print("-"*80)
            print(f"{display_name:<28} | {avg_score:.4f}")
        else:
            print(f"{display_name:<28} | {avg_score:.4f}")
            
    print("="*80)


if __name__ == "__main__":
    main()
