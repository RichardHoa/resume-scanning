"""
Core Configuration & Paths for Resume Scanning & Evaluation Engine
"""
import os

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(SCRIPT_DIR)
ROOT_DIR = os.path.dirname(SRC_DIR)

LOGGING_DIR = os.path.join(ROOT_DIR, "logging")
EVAL_RESULTS_DIR = os.path.join(ROOT_DIR, "eval_results")
EVALUATION_JSON_DIR = os.path.join(ROOT_DIR, "evaluation_json")
SCHEMAS_DIR = os.path.join(ROOT_DIR, "schemas")
RAG_DIR = os.path.join(ROOT_DIR, "rag")
APPROVED_DIR = os.path.join(ROOT_DIR, "approved_jsons")
OUTPUT_DIR = os.path.join(ROOT_DIR, "output_jsons")
PDF_DIR = os.path.join(ROOT_DIR, "pdfs")

# Ensure required directories exist
for d in [LOGGING_DIR, EVAL_RESULTS_DIR, EVALUATION_JSON_DIR, RAG_DIR]:
    os.makedirs(d, exist_ok=True)

# Weight distribution for 5 evaluation dimensions
DIMENSION_WEIGHTS = {
    "seniority_title": 0.15,
    "technical_skills": 0.30,
    "work_experience": 0.30,
    "education_certifications": 0.10,
    "hidden_culture": 0.15
}

# Token generation limit
MAX_NEW_TOKENS = 20000

# Default model defaults
DEFAULT_LLM_MODEL = "Qwen/Qwen3.5-9B"
DEFAULT_EMBEDDING_MODEL = "AITeamVN/Vietnamese_Embedding"
DEFAULT_VLLM_URL = "http://localhost:8100/v1"
