"""
Core Configuration & Paths for Resume Scanning & Evaluation Engine
"""
import os

from src.core.onnx_patch import apply_onnx_affinity_patch

apply_onnx_affinity_patch()

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(SCRIPT_DIR)
ROOT_DIR = os.path.dirname(SRC_DIR)

LOGGING_DIR = os.path.join(ROOT_DIR, "logging")
BROKEN_JSON_DIR = os.path.join(ROOT_DIR, "broken-json")
EVAL_RESULTS_DIR = os.path.join(ROOT_DIR, "eval_results")
EVALUATION_JSON_DIR = os.path.join(ROOT_DIR, "evaluation_json")
SCHEMAS_DIR = os.path.join(ROOT_DIR, "schemas")
RAG_DIR = os.path.join(ROOT_DIR, "rag")
APPROVED_DIR = os.path.join(ROOT_DIR, "approved_jsons")
OUTPUT_DIR = os.path.join(ROOT_DIR, "output_jsons")
PDF_DIR = os.path.join(ROOT_DIR, "pdfs")
EXTRACTION_MARKDOWN_DIR = os.path.join(ROOT_DIR, "extraction_markdown")

# Ensure required directories exist
for d in [LOGGING_DIR, BROKEN_JSON_DIR, EVAL_RESULTS_DIR, EVALUATION_JSON_DIR, RAG_DIR, EXTRACTION_MARKDOWN_DIR, APPROVED_DIR]:
    os.makedirs(d, exist_ok=True)

# Weight distribution for 5 evaluation dimensions
DIMENSION_WEIGHTS = {
    "seniority_title": 0.22,
    "technical_skills": 0.22,
    "work_experience": 0.22,
    "education_certifications": 0.22,
    "hidden_culture": 0.12
}

# Fallback score when evaluation fails or retries are exhausted
FALLBACK_ERROR_SCORE = 0

# Recommendation thresholds for overall evaluation match
MATCH_THRESHOLDS = {
    "STRONG": 85,
    "POTENTIAL": 70,
    "LOW": 55
}

# Token & Context Window Limits
VLLM_MAX_MODEL_LEN = 40000 # Total vLLM model context length limit (--max-model-len)
MAX_NEW_TOKENS = 8096     # Output new tokens limit
DSPY_MAX_TOKENS = 4048    # DSPy prompt optimization output token limit

# Default model defaults
DEFAULT_LLM_MODEL = "Qwen/Qwen3.5-35B-A3B-FP8"
DEFAULT_EMBEDDING_MODEL = "AITeamVN/Vietnamese_Embedding"
DEFAULT_VLLM_URL = "http://127.0.0.1:8100/v1"
VLLM_REQUEST_TIMEOUT = 1800

