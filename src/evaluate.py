#!/usr/bin/env python3
"""
Structured JSON Accuracy Evaluator for Resume Extraction
(Backwards-compatibility shim delegating to modular src packages)
"""
import os
import sys

# Ensure repository root is in sys.path for 'src' package imports
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.metrics.embedding import HAS_TORCH_TRANSFORMERS, mean_pooling, EmbeddingEvaluator, LexicalEvaluator
from src.metrics.lexical import (
    cosine_similarity,
    normalize_email,
    normalize_phone,
    evaluate_email,
    evaluate_phone,
    text_similarity,
    get_tokens,
    solve_assignment,
    evaluate_skills,
    evaluate_nested_list,
    evaluate_json_pair,
)
from src.cli.benchmark import main

if __name__ == "__main__":
    main()
