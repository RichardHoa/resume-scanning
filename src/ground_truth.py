#!/usr/bin/env python3
"""
Resume Ground Truth Validator Server
(Backwards-compatibility shim delegating to modular src packages)
"""
import os
import sys

# Ensure repository root is in sys.path for 'src' package imports
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.pipelines.ground_truth import (
    PORT,
    WORKSPACE_DIR,
    PDF_DIR,
    JSON_DIR,
    APPROVED_DIR,
    HTML_CONTENT,
    natural_sort_key,
    GroundTruthHandler,
    run
)

if __name__ == '__main__':
    run()
