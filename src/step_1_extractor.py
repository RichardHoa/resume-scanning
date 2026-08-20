#!/usr/bin/env python3
"""
Vietnamese Resume Extractor — Step 1: Structured Information Extraction
(Backwards-compatibility shim delegating to modular src packages)
"""
import os
import sys

# Ensure repository root is in sys.path for 'src' package imports
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.core.json_utils import load_schema_from_file, extract_json_substring, repair_truncated_json
from src.prompts.extractor_prompts import get_system_prompt
from src.providers.llm_backend import (
    load_local_model,
    run_local_inference,
    run_vllm_inference,
    run_mock_extraction,
    vllm_discover_model as _vllm_discover_model,
    vllm_chat_request as _vllm_chat_request,
)
from src.pipelines.extractor import extract_text_from_pdf, ResumeExtractor
from src.cli.extract import parse_args, main

if __name__ == "__main__":
    main()
