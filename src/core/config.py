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
# One JSON line per vLLM request (step, prompt/completion tokens, finish reason); summarized by scripts/token_stats.py
TOKEN_USAGE_FILE = os.path.join(LOGGING_DIR, "token_usage.jsonl")
EVAL_RESULTS_DIR = os.path.join(ROOT_DIR, "eval_results")
EVALUATION_JSON_DIR = os.path.join(ROOT_DIR, "evaluation_json")
SCHEMAS_DIR = os.path.join(ROOT_DIR, "schemas")
RAG_DIR = os.path.join(ROOT_DIR, "rag")
APPROVED_DIR = os.path.join(ROOT_DIR, "approved_jsons")
OUTPUT_DIR = os.path.join(ROOT_DIR, "output_jsons")
PDF_DIR = os.path.join(ROOT_DIR, "pdfs")
# Original resume PDFs kept at extraction, named like their extraction JSON, so HR can view them next to the evaluation
RESUME_PDF_DIR = os.path.join(ROOT_DIR, "resumes_pdf")
EXTRACTION_MARKDOWN_DIR = os.path.join(ROOT_DIR, "extraction_markdown")
SERVER_STATE_DIR = os.path.join(ROOT_DIR, "server_state")

# Ensure required directories exist
for d in [LOGGING_DIR, BROKEN_JSON_DIR, EVAL_RESULTS_DIR, EVALUATION_JSON_DIR, RAG_DIR, EXTRACTION_MARKDOWN_DIR, APPROVED_DIR, SERVER_STATE_DIR, RESUME_PDF_DIR]:
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
VLLM_MAX_MODEL_LEN = 32768 # Total vLLM model context length limit (--max-model-len)
MAX_NEW_TOKENS = 8192     # Output new tokens limit
# A normal category evaluation is well under this; a model stuck repeating inside the schema runs to the cap,
# so a lower cap makes that failed attempt end in a couple of minutes instead of ~7
CATEGORY_EVAL_MAX_TOKENS = 4096
# Retrying an identical prompt at temperature 0 reproduces the same failure, so retries after the first
# attempt sample instead
CATEGORY_EVAL_RETRY_TEMPERATURE = 0.5
DSPY_MAX_TOKENS = 4096    # DSPy prompt optimization output token limit
REQUIREMENTS_DECOMPOSITION_MAX_TOKENS = 4096

# Requirement-scrutiny step (web-only; surfaces Implicit Assumptions as Clarification Questions
# before decomposition). Uses a non-zero temperature deliberately — see docs/adr/0001-nondeterministic-temperature-for-scrutiny-step.md
SCRUTINY_TEMPERATURE = 0.7
SCRUTINY_MAX_QUESTIONS_PER_FIELD = 5

# Default model defaults
DEFAULT_LLM_MODEL = "aisingapore/Qwen-SEA-LION-v4.5-27B-IT"
DEFAULT_EMBEDDING_MODEL = "AITeamVN/Vietnamese_Embedding"
DEFAULT_VLLM_URL = "http://127.0.0.1:8100/v1"
VLLM_REQUEST_TIMEOUT = 1800

# Process-wide cap on requests in flight to vLLM, shared by every caller. Defaults from the model
# profile's CONCURRENCY (exported by scripts/model_profiles.sh)
DEFAULT_VLLM_MAX_CONCURRENT_REQUESTS = 50
VLLM_MAX_CONCURRENT_REQUESTS = int(os.environ.get("CONCURRENCY") or DEFAULT_VLLM_MAX_CONCURRENT_REQUESTS)

# Review Panel (Candidate Feedback). Thinking is always off for the panel, whatever the model profile says
REVIEW_PANEL_TEMPERATURE = 0.0
REVIEW_PANEL_PANELIST_MAX_TOKENS = 4096
REVIEW_PANEL_COORDINATOR_MAX_TOKENS = 8192
REVIEW_PANEL_MAX_ATTEMPTS = 2               # the whole panel is retried once from the beginning

# Per-model reasoning controls, exported by scripts/model_profiles.sh
VLLM_ENABLE_THINKING = os.environ.get("VLLM_ENABLE_THINKING", "0") == "1"
VLLM_REASONING_STRENGTH = os.environ.get("VLLM_REASONING_STRENGTH", "")


# Operation duration tracking (web waiting-screen time estimates). The expected duration of an
# operation kind is the median of its recent successful runs, or the default below when none exist.
OPERATION_DURATIONS_PATH = os.path.join(SERVER_STATE_DIR, "operation_durations.json")
OPERATION_DURATION_WINDOW = 20
OPERATION_DURATION_DEFAULTS_SECONDS = {
    "scrutiny": 30.0,
    "decompose": 60.0,
    "save_criteria": 10.0,
    "extract": 60.0,
    "evaluate_candidate": 90.0
}

# Background batch-evaluation jobs: finished jobs are dropped from memory after this many seconds
EVAL_JOB_TTL_SECONDS = 1800
