"""
Core Configuration & Paths for Resume Scanning & Evaluation Engine
"""
import os

from src.core.onnx_patch import apply_onnx_affinity_patch

apply_onnx_affinity_patch()

SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
SRC_DIR = os.path.dirname(SCRIPT_DIR)
ROOT_DIR = os.path.dirname(SRC_DIR)

# Durable inputs and state, never wiped by a run
SCHEMAS_DIR = os.path.join(ROOT_DIR, "schemas")
RAG_DIR = os.path.join(ROOT_DIR, "rag")
APPROVED_DIR = os.path.join(ROOT_DIR, "approved_jsons")
PDF_DIR = os.path.join(ROOT_DIR, "pdfs")
SERVER_STATE_DIR = os.path.join(ROOT_DIR, "server_state")

# Run folders (docs/adr/0010-run-folders.md): every output of one source of work lives in one folder under runs/.
# A pipeline job wipes its folder before it starts; the website's folder is never wiped. The scripts in scripts/
# repeat these folder and subfolder names
RUNS_DIR = os.path.join(ROOT_DIR, "runs")
DEFAULT_RUN_FOLDER = "batch-cnb"
# The website's folder when it is started without a resume set: it reads no pipeline run folder
WEB_NO_SET_RUN_FOLDER = "web"
# Each website run folder and the pipeline run folder of the same resume set, which the website also reads, read-only
WEB_TO_PIPELINE_RUN_FOLDER = {"web-cnb": "batch-cnb", "web-tech": "batch-tech"}
# The extractor consistency check's folders, one per resume set; the website never reads them
CONSISTENCY_RUN_FOLDERS = ("consistency-cnb", "consistency-tech")
RUN_FOLDER_NAMES = ("batch-cnb", "batch-tech", WEB_NO_SET_RUN_FOLDER, *WEB_TO_PIPELINE_RUN_FOLDER, *CONSISTENCY_RUN_FOLDERS)

LOGS_SUBDIR = "logs"
PROMPT_LOGS_SUBDIR = "prompt_logs"
EXTRACTION_MARKDOWN_SUBDIR = "extraction_markdown"
EXTRACTION_JSON_SUBDIR = "extraction_json"
EVALUATION_JSON_SUBDIR = "evaluation_json"
RESUME_PDF_SUBDIR = "resumes_pdf"
TOKEN_USAGE_FILENAME = "token_usage.jsonl"


def _resolve_run_dir() -> str:
    """
    The active run folder from RUN_DIR (an absolute path, a path from the repo root, or a bare folder name under
    runs/), or runs/batch-cnb when unset.
    """
    raw = os.environ.get("RUN_DIR") or DEFAULT_RUN_FOLDER
    if os.path.isabs(raw):
        path = raw
    elif os.sep in raw:
        path = os.path.join(ROOT_DIR, raw)
    else:
        path = os.path.join(RUNS_DIR, raw)
    path = os.path.abspath(path)
    # realpath: the scripts' PROJECT_ROOT may reach the repo through a symlink
    if os.path.realpath(os.path.dirname(path)) != os.path.realpath(RUNS_DIR) or os.path.basename(path) not in RUN_FOLDER_NAMES:
        raise RuntimeError(f"RUN_DIR must be one of {', '.join(RUN_FOLDER_NAMES)} under {RUNS_DIR}, not '{raw}'")
    return os.path.join(RUNS_DIR, os.path.basename(path))


# The run folder this process writes to
RUN_DIR = _resolve_run_dir()
RUN_LOGS_DIR = os.path.join(RUN_DIR, LOGS_SUBDIR)
# Every LLM prompt and response: prompt_logs/<resume>/<category>/N.txt, unparsable ones under <resume>/broken_json/
PROMPT_LOGS_DIR = os.path.join(RUN_DIR, PROMPT_LOGS_SUBDIR)
EXTRACTION_MARKDOWN_DIR = os.path.join(RUN_DIR, EXTRACTION_MARKDOWN_SUBDIR)
EXTRACTION_JSON_DIR = os.path.join(RUN_DIR, EXTRACTION_JSON_SUBDIR)
EVALUATION_JSON_DIR = os.path.join(RUN_DIR, EVALUATION_JSON_SUBDIR)
# Original resume PDFs kept at extraction, named like their extraction JSON, so HR can view them next to the evaluation
RESUME_PDF_DIR = os.path.join(RUN_DIR, RESUME_PDF_SUBDIR)
# One JSON line per vLLM request (step, resume, prompt/completion tokens, finish reason); summarized by scripts/token_stats.py
TOKEN_USAGE_FILE = os.path.join(RUN_LOGS_DIR, TOKEN_USAGE_FILENAME)

# Run folders read from, the active one first so its copy of a resume wins: a website folder also reads its
# resume set's pipeline folder, so a batch run can be browsed on the website
_pipeline_run_folder = WEB_TO_PIPELINE_RUN_FOLDER.get(os.path.basename(RUN_DIR))
SOURCE_RUN_DIRS = [RUN_DIR] + ([os.path.join(RUNS_DIR, _pipeline_run_folder)] if _pipeline_run_folder else [])
# Extracted resume JSONs, most trusted first: HR's ground truth, then each run folder's extractions
RESUME_JSON_DIRS = [APPROVED_DIR] + [os.path.join(d, EXTRACTION_JSON_SUBDIR) for d in SOURCE_RUN_DIRS]
EVALUATION_JSON_DIRS = [os.path.join(d, EVALUATION_JSON_SUBDIR) for d in SOURCE_RUN_DIRS]

# Ensure required directories exist
for d in [RAG_DIR, APPROVED_DIR, SERVER_STATE_DIR, RUN_LOGS_DIR, PROMPT_LOGS_DIR, EXTRACTION_MARKDOWN_DIR,
          EXTRACTION_JSON_DIR, EVALUATION_JSON_DIR, RESUME_PDF_DIR]:
    os.makedirs(d, exist_ok=True)

# The five Categories every resume is judged on, by key and display name
CATEGORY_LABELS = {
    "seniority_title": "Position & Seniority Match",
    "technical_skills": "Technical Skills & Competencies",
    "work_experience": "Work Experience & Project Relevance",
    "education_certifications": "Education & Certifications",
    "hidden_culture": "HR Hidden Requirements & Culture Fit"
}

# Weight distribution for 5 evaluation dimensions
DIMENSION_WEIGHTS = {
    "seniority_title": 0.22,
    "technical_skills": 0.22,
    "work_experience": 0.22,
    "education_certifications": 0.22,
    "hidden_culture": 0.12
}

# Importance of one Criterion inside its Category, set only by HR in the HR RAG. The Must-have and Standard Criteria
# share the Category's 100 points by these weights, so an all-Standard Category scores as an unweighted mean. A
# Nice-to-have only adds bonus points at its weight, capped at the Category's 100, and never costs any (ADR 0014).
# A Must-have weighs the same as a Standard: what sets it apart is the Must-have Rejection (NO_EVIDENCE on any one
# rejects the candidate, ADR 0011). The single source of the levels: the API, hr_rag.txt and the criteria editor
# (through the RAG summary) read them here
MUST_HAVE = "must_have"
DEFAULT_IMPORTANCE = "standard"
NICE_TO_HAVE = "nice_to_have"
IMPORTANCE_LEVELS = {
    MUST_HAVE: {"label": "Bắt buộc", "weight": 2},
    DEFAULT_IMPORTANCE: {"label": "Tiêu chuẩn", "weight": 2},
    NICE_TO_HAVE: {"label": "Ưu tiên", "weight": 1}
}
IMPORTANCE_WEIGHTS = {key: level["weight"] for key, level in IMPORTANCE_LEVELS.items()}

# Key the decomposer and the RAG store use for HR Check Items: requirements no ordinary resume would show, which
# are kept beside the five Categories but never weighted or judged, and handed to HR to check by hand
HR_CHECK_ITEMS_KEY = "hr_check_items"

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
# so a stuck attempt costs the full 8k tokens before it fails
CATEGORY_EVAL_MAX_TOKENS = 8192
# Retrying an identical prompt at temperature 0 reproduces the same failure, so retries after the first
# attempt sample instead
CATEGORY_EVAL_RETRY_TEMPERATURE = 0.5
# Evaluation runs per Category: the Category score is their median, and a Must-have rejects only on a majority of
# No Evidence. Run 1 is greedy; later runs sample at CATEGORY_EVAL_SAMPLE_TEMPERATURE so they are independent
# judgements instead of copies of run 1 (ADR 0012)
DEFAULT_NUM_EVALUATIONS = 3
CATEGORY_EVAL_SAMPLE_TEMPERATURE = 0.5
DSPY_MAX_TOKENS = 4096    # DSPy prompt optimization output token limit
REQUIREMENTS_DECOMPOSITION_MAX_TOKENS = 4096
# AI Proofreading Pass (src/cli/proofread.py): a page task rewrites at most one page of text; a note task
# thinks first. Retries after the first attempt sample, as an identical prompt at temperature 0 fails the same way
PROOFREAD_PAGE_MAX_TOKENS = 4096
PROOFREAD_NOTE_MAX_TOKENS = 16384
PROOFREAD_RETRY_TEMPERATURE = 0.3
# Combined Extraction (--combined): the extractor sees page images next to the PyMuPDF text, for layout only.
# At most COMBINED_MAX_PAGES pages are shown; keep it equal to COMBINED_MAX_PAGES in scripts/model_profiles.sh,
# which sets vLLM's per-prompt image limit
COMBINED_IMAGE_DPI = 150
COMBINED_MAX_PAGES = 6

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
