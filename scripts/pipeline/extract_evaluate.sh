#!/bin/bash
#SBATCH --job-name=extract_eval_vllm
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=132
#SBATCH --mem=32G
#SBATCH --partition=student9696
#SBATCH --gres=gpu:nvidia_rtx_pro_6000_blackwell_server_edition_4g.96gb:1
#SBATCH --time=6:00:00
#SBATCH --output=logging/slurm_extract_eval_%j.out
#SBATCH --error=logging/slurm_extract_eval_%j.err

# -----------------------------------------------------------------------------
# SLURM Batch Job Script for Extraction & Evaluation in One Job with vLLM
#
# Usage: sbatch scripts/pipeline/extract_evaluate.sh [pdf_dir] [model] --cnb|--tech [--combined]
#
# Wipes the run folder (runs/batch-cnb with --cnb, runs/batch-tech with --tech), spins up a vLLM server instance,
# runs batch extraction (Step 1), and then runs batch evaluation (Step 2) using the active vLLM server. Every
# output of the job goes into the run folder: its logs, prompt logs, extraction markdown and JSON, evaluation JSON
# and resume PDFs (docs/adr/0010-run-folders.md). SLURM's own .out/.err files stay in logging/.
#
# Evaluation uses the HR RAG as HR set it on the website's RAG page, and never builds,
# changes or clears it: set the HR RAG for the job before submitting, or the job stops
# before it starts the server.
#
# Dataset: pass --cnb (Vietnamese-dataset/CnB) or --tech (Vietnamese-dataset/Tech), anywhere among the
# arguments; one is required. With --tech the HR RAG must then hold the Tech job's
# requirements (hr-requirement-tech.txt). An explicit PDF dir argument still overrides.
# The Tech resumes are old, so --tech also sets the Reference Date (the date the prompts treat as today)
# to December 2015.
#
# --combined runs Combined Extraction: vLLM is served with vision on and the extractor also sees each page's image,
# for layout only (values still come from the PDF text). It needs a profile that can see images (VLLM_VISION=1).
# -----------------------------------------------------------------------------

DATASET=""
SET_FLAGS=0
COMBINED=0
POSITIONAL_ARGS=()
for arg in "$@"; do
  case "$arg" in
    --cnb) DATASET="CnB"; SET_FLAGS=$((SET_FLAGS + 1)) ;;
    --tech) DATASET="Tech"; SET_FLAGS=$((SET_FLAGS + 1)) ;;
    --combined) COMBINED=1 ;;
    *) POSITIONAL_ARGS+=("$arg") ;;
  esac
done
set -- "${POSITIONAL_ARGS[@]}"

# The resume set is never defaulted, so a job never lands in the wrong run folder
if [ "$SET_FLAGS" -ne 1 ]; then
  echo "[ERROR] Pass exactly one of --cnb or --tech to pick the resume set." >&2
  exit 1
fi

if [ "$DATASET" = "Tech" ]; then
  REFERENCE_DATE="2015-12-31"
else
  REFERENCE_DATE=""
fi

RAW_PDF_DIR="$1"
RAW_MODEL="$2"
INITIAL_CWD="$(pwd)"

# -----------------------------------------------------------------------------
# Location of the shared helpers (scripts/lib). SLURM runs a copy of this script, so under sbatch they are found
# from the submitting directory, the repository root; run with bash, from the script's own folder
# -----------------------------------------------------------------------------
LIB_DIR="${SLURM_SUBMIT_DIR:-$(pwd)}/scripts/lib"
[ -f "$LIB_DIR/config.sh" ] || LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../lib" 2>/dev/null && pwd)"
if [ ! -f "$LIB_DIR/config.sh" ]; then
  echo "[CRITICAL ERROR] Cannot locate 'scripts/lib/config.sh'. Submit from the repository root. Submitting directory: ${SLURM_SUBMIT_DIR:-$(pwd)}" >&2
  exit 1
fi

# -----------------------------------------------------------------------------
# STEP 1: Load Cluster Modules & Activate Conda Environment FIRST
# -----------------------------------------------------------------------------
echo "[$(date +'%H:%M:%S')] STEP 1: Loading system environment modules..."
module load miniconda3 2>/dev/null || true
module load cuda 2>/dev/null || module load cuda13.0 2>/dev/null || true

# Check conda binary path
if ! command -v conda &>/dev/null; then
  for c_path in /compute_home/$USER/miniconda3/bin/conda /compute_home/$USER/anaconda3/bin/conda /opt/miniconda3/bin/conda /opt/anaconda3/bin/conda; do
    if [ -x "$c_path" ]; then
      export PATH="$(dirname "$c_path"):$PATH"
      break
    fi
  done
fi

echo "[$(date +'%H:%M:%S')] STEP 2: Activating Conda environment 'resume_env'..."
eval "$(conda shell.bash hook 2>/dev/null)" || true
source activate resume_env 2>/dev/null || conda activate resume_env 2>/dev/null || true
echo "[$(date +'%H:%M:%S')] Active Python: $(which python3 2>/dev/null || echo 'python3 not found')"

# -----------------------------------------------------------------------------
# STEP 2: Source Configuration & vLLM Helpers (Python environment is active)
# -----------------------------------------------------------------------------
source "$LIB_DIR/config.sh"
source "$LIB_DIR/vllm_utils.sh"
source "$LIB_DIR/model_profiles.sh"

if [ -z "$PROJECT_ROOT" ]; then
  echo "[CRITICAL ERROR] PROJECT_ROOT is not set after sourcing config.sh!" >&2
  exit 1
fi

# Force execution strictly from project repository root directory
cd "$PROJECT_ROOT" || exit 1

# Setup optimization & threading environment variables
setup_vllm_env

# -----------------------------------------------------------------------------
# STEP 3: Resolve Parameters & Validate Input Paths
# -----------------------------------------------------------------------------
# Resolve PDF input directory (Default: Vietnamese-dataset/$DATASET inside project root)
if [ -n "$RAW_PDF_DIR" ]; then
  if [[ "$RAW_PDF_DIR" = /* ]]; then
    PDF_DIR="$RAW_PDF_DIR"
  elif [ -d "$INITIAL_CWD/$RAW_PDF_DIR" ]; then
    PDF_DIR="$(cd "$INITIAL_CWD/$RAW_PDF_DIR" && pwd)"
  else
    PDF_DIR="$PROJECT_ROOT/$RAW_PDF_DIR"
  fi
else
  PDF_DIR="$PROJECT_ROOT/Vietnamese-dataset/$DATASET"
fi

# Target model: a profile key or HuggingFace model ID (default: the DEFAULT_MODEL_KEY profile)
resolve_model_arg "$RAW_MODEL" || exit 1

# Combined Extraction: refuse a model that cannot see images before anything is wiped, then serve vision on
COMBINED_ARGS=()
if [ "$COMBINED" -eq 1 ]; then
  require_vision_profile || exit 1
  serve_vision_on "$COMBINED_MAX_PAGES"
  COMBINED_ARGS=(--combined)
fi

use_pipeline_run_dir "$DATASET"

if [ ! -d "$PDF_DIR" ]; then
  echo "[ERROR] PDF directory '$PDF_DIR' does not exist." >&2
  exit 1
fi

require_hr_rag || exit 1

# -----------------------------------------------------------------------------
# STEP 4: Wipe the Run Folder
# -----------------------------------------------------------------------------
echo "====================================================================="
echo "[$(date +'%Y-%m-%d %H:%M:%S')] STEP 4: Wiping run folder '$RUN_DIR'..."
echo "Every output of the previous pass goes (the HR RAG and approved_jsons are kept)."
echo "====================================================================="

mkdir -p "$PROJECT_ROOT/logging"
reset_run_dir || exit 1

# -----------------------------------------------------------------------------
# STEP 5: Logging Setup & Server Startup
# -----------------------------------------------------------------------------
JOB_LOG="$RUN_LOGS_DIR/job.log"
EXTRACT_LOG="$RUN_LOGS_DIR/extract.log"
EVAL_LOG="$RUN_LOGS_DIR/eval.log"
VLLM_LOG="$RUN_LOGS_DIR/vllm.log"

echo "[$(date +'%Y-%m-%d %H:%M:%S')] Extract & Eval Job Started" > "$JOB_LOG"

echo "=====================================================================" | tee -a "$JOB_LOG"
echo "[$(date +'%Y-%m-%d %H:%M:%S')] STEP 5: Inspecting GPU hardware allocation..." | tee -a "$JOB_LOG"
nvidia-smi 2>/dev/null | tee -a "$JOB_LOG" || echo "nvidia-smi not available" | tee -a "$JOB_LOG"
echo "=====================================================================" | tee -a "$JOB_LOG"

PORT=$(find_free_port)

echo "[$(date +'%H:%M:%S')] Project Root: $PROJECT_ROOT" | tee -a "$JOB_LOG"
echo "[$(date +'%H:%M:%S')] Dataset: $DATASET" | tee -a "$JOB_LOG"
echo "[$(date +'%H:%M:%S')] Reference Date: ${REFERENCE_DATE:-today}" | tee -a "$JOB_LOG"
echo "[$(date +'%H:%M:%S')] Target PDF Directory: $PDF_DIR" | tee -a "$JOB_LOG"
echo "[$(date +'%H:%M:%S')] Run Folder: $RUN_DIR" | tee -a "$JOB_LOG"
echo "[$(date +'%H:%M:%S')] Target Model: $MODEL" | tee -a "$JOB_LOG"
echo "[$(date +'%H:%M:%S')] Combined Extraction: $([ "$COMBINED" -eq 1 ] && echo on || echo off)" | tee -a "$JOB_LOG"
echo "[$(date +'%H:%M:%S')] Allocated Server Port: $PORT" | tee -a "$JOB_LOG"
echo "[$(date +'%H:%M:%S')] Server Log File: $VLLM_LOG" | tee -a "$JOB_LOG"
echo "[$(date +'%H:%M:%S')] Extractor Log File: $EXTRACT_LOG" | tee -a "$JOB_LOG"
echo "[$(date +'%H:%M:%S')] Evaluator Log File: $EVAL_LOG" | tee -a "$JOB_LOG"
echo "[$(date +'%H:%M:%S')] HF Cache Path: ${HF_HOME:-default}" | tee -a "$JOB_LOG"

start_vllm_server "$MODEL" "$PORT" "$VLLM_LOG" || exit 1

# -----------------------------------------------------------------------------
# STEP 6: Execute Step 1 - Batch Extraction
# -----------------------------------------------------------------------------
echo "=====================================================================" | tee -a "$JOB_LOG"
echo "[$(date +'%Y-%m-%d %H:%M:%S')] === [Step 1/2] Starting Batch Extraction (vLLM) ===" | tee -a "$JOB_LOG"
echo "Processing PDFs from '$PDF_DIR' -> JSONs to '$EXTRACTION_JSON_DIR' using model '$MODEL'" | tee -a "$JOB_LOG"
echo "Detailed extraction log: $EXTRACT_LOG" | tee -a "$JOB_LOG"
echo "=====================================================================" | tee -a "$JOB_LOG"

python3 -u "$PROJECT_ROOT/src/step_1_extractor.py" \
  --dir "$PDF_DIR" \
  --output "$EXTRACTION_JSON_DIR" \
  --model-name "$MODEL" \
  --vllm-url "http://127.0.0.1:$PORT/v1" \
  --workers 6 \
  --reference-date "$REFERENCE_DATE" \
  "${COMBINED_ARGS[@]}" 2>&1 | tee "$EXTRACT_LOG" | tee -a "$JOB_LOG"

EXTRACT_STATUS=${PIPESTATUS[0]}
if [ "$EXTRACT_STATUS" -ne 0 ]; then
  echo "[CRITICAL ERROR] Batch extraction failed with exit code $EXTRACT_STATUS!" | tee -a "$JOB_LOG" >&2
  stop_vllm_server
  exit "$EXTRACT_STATUS"
fi

# -----------------------------------------------------------------------------
# STEP 7: Execute Step 2 - High-Precision Evaluation
# -----------------------------------------------------------------------------
echo "=====================================================================" | tee -a "$JOB_LOG"
echo "[$(date +'%Y-%m-%d %H:%M:%S')] === [Step 2/2] Starting High-Precision Batch Evaluation (vLLM) ===" | tee -a "$JOB_LOG"
echo "Evaluating JSONs from '$EXTRACTION_JSON_DIR' -> Results to '$EVALUATION_JSON_DIR' using model '$MODEL'" | tee -a "$JOB_LOG"
echo "Detailed evaluation log: $EVAL_LOG" | tee -a "$JOB_LOG"
echo "=====================================================================" | tee -a "$JOB_LOG"

python3 -u "$PROJECT_ROOT/src/step_2_evaluate.py" \
  --model-name "$MODEL" \
  --vllm-url "http://127.0.0.1:$PORT/v1" \
  --dir "$EXTRACTION_JSON_DIR" \
  --output "$EVALUATION_JSON_DIR" \
  --reference-date "$REFERENCE_DATE" 2>&1 | tee "$EVAL_LOG" | tee -a "$JOB_LOG"

EVAL_STATUS=${PIPESTATUS[0]}
if [ "$EVAL_STATUS" -ne 0 ]; then
  echo "[CRITICAL ERROR] Batch evaluation failed with exit code $EVAL_STATUS!" | tee -a "$JOB_LOG" >&2
  stop_vllm_server
  exit "$EVAL_STATUS"
fi

stop_vllm_server
python3 "$PROJECT_ROOT/scripts/checks/token_stats.py" 2>&1 | tee -a "$JOB_LOG"
echo "=====================================================================" | tee -a "$JOB_LOG"
echo "=== [$(date +'%Y-%m-%d %H:%M:%S')] Extract & Eval Job Finished Successfully ===" | tee -a "$JOB_LOG"
echo "=====================================================================" | tee -a "$JOB_LOG"
