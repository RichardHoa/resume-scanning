#!/usr/bin/env python3
"""
Vietnamese Resume Evaluator Agent — Step 2: RAG-based Evaluation & Scoring
(Backwards-compatibility shim delegating to modular src packages)
"""
import os
import sys

# Ensure repository root is in sys.path for 'src' package imports
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.core.config import LOGGING_DIR, EVAL_RESULTS_DIR, DIMENSION_WEIGHTS
from src.core.logger import log_llm_call
from src.core.json_utils import clean_and_parse_json as _clean_and_parse_json
from src.providers.rag_engine import LocalCriteriaRAG
from src.pipelines.evaluator import ResumeEvaluator
from src.cli.evaluate import parse_args, main

if __name__ == "__main__":
    main()
