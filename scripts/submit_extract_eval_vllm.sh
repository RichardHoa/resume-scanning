#!/bin/bash
#SBATCH --job-name=extract_eval_vllm
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=32G
#SBATCH --partition=student9696
#SBATCH --gres=gpu:nvidia_rtx_pro_6000_blackwell_server_edition_4g.96gb:1
#SBATCH --time=3:00:00
#SBATCH --output=logging/slurm_extract_eval_%j.out
#SBATCH --error=logging/slurm_extract_eval_%j.err

# -----------------------------------------------------------------------------
# SLURM Batch Job Script for Combined Extraction & Evaluation with vLLM
#
# Usage: sbatch scripts/submit_extract_eval_vllm.sh [pdf_dir] [model] [--tech]
#
# Wipes the run folder (runs/full-cnb, or runs/full-tech with --tech), spins up a vLLM server instance, runs batch
# extraction (Step 1), and then runs batch evaluation (Step 2) using the active vLLM server. Every output of the
# job goes into the run folder: its logs, prompt logs, extraction markdown and JSON, evaluation JSON and resume
# PDFs (docs/adr/0010-run-folders.md). SLURM's own .out/.err files stay in logging/.
#
# Evaluation uses the HR RAG as HR set it on the website's RAG page, and never builds,
# changes or clears it: set the HR RAG for the job before submitting, or the job stops
# before it starts the server.
#
# Dataset: CnB by default (Vietnamese-dataset/CnB). Pass --tech (anywhere among the
# arguments) for Vietnamese-dataset/Tech; the HR RAG must then hold the Tech job's
# requirements (hr-requirement-tech.txt). An explicit PDF dir argument still overrides.
# The Tech resumes are old, so --tech also sets the Reference Date (the date the prompts treat as today)
# to December 2015.
# -----------------------------------------------------------------------------

DATASET="CnB"
POSITIONAL_ARGS=()
for arg in "$@"; do
  case "$arg" in
    --tech) DATASET="Tech" ;;
    *) POSITIONAL_ARGS+=("$arg") ;;
  esac
done
set -- "${POSITIONAL_ARGS[@]}"

if [ "$DATASET" = "Tech" ]; then
  REFERENCE_DATE="2015-12-31"
else
  REFERENCE_DATE=""
fi

RAW_PDF_DIR="$1"
RAW_MODEL="$2"
INITIAL_CWD="$(pwd)"

# -----------------------------------------------------------------------------
# Robust Location of config.sh and vllm_utils.sh
# -----------------------------------------------------------------------------
FIND_CONFIG_DIR=""
if [ -n "$SLURM_SUBMIT_DIR" ]; then
  if [ -f "$SLURM_SUBMIT_DIR/scripts/config.sh" ]; then
    FIND_CONFIG_DIR="$SLURM_SUBMIT_DIR/scripts"
  elif [ -f "$SLURM_SUBMIT_DIR/config.sh" ]; then
    FIND_CONFIG_DIR="$SLURM_SUBMIT_DIR"
  fi
fi

if [ -z "$FIND_CONFIG_DIR" ]; then
  CANDIDATE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)"
  if [ -f "$CANDIDATE_DIR/config.sh" ]; then
    FIND_CONFIG_DIR="$CANDIDATE_DIR"
  elif [ -f "$CANDIDATE_DIR/scripts/config.sh" ]; then
    FIND_CONFIG_DIR="$CANDIDATE_DIR/scripts"
  fi
fi

if [ -z "$FIND_CONFIG_DIR" ]; then
  if [ -f "$INITIAL_CWD/scripts/config.sh" ]; then
    FIND_CONFIG_DIR="$INITIAL_CWD/scripts"
  elif [ -f "$INITIAL_CWD/config.sh" ]; then
    FIND_CONFIG_DIR="$INITIAL_CWD"
  fi
fi

if [ -z "$FIND_CONFIG_DIR" ] || [ ! -f "$FIND_CONFIG_DIR/config.sh" ]; then
  echo "[CRITICAL ERROR] Cannot locate 'config.sh'. Submitting directory: ${SLURM_SUBMIT_DIR:-$INITIAL_CWD}" >&2
  exit 1
fi

SCRIPT_DIR="$FIND_CONFIG_DIR"

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
source "$SCRIPT_DIR/config.sh"
source "$SCRIPT_DIR/vllm_utils.sh"
source "$SCRIPT_DIR/model_profiles.sh"

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

echo "[$(date +'%Y-%m-%d %H:%M:%S')] Combined Extract & Eval Job Started" > "$JOB_LOG"

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
  --reference-date "$REFERENCE_DATE" 2>&1 | tee "$EXTRACT_LOG" | tee -a "$JOB_LOG"

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
python3 "$PROJECT_ROOT/scripts/token_stats.py" 2>&1 | tee -a "$JOB_LOG"
echo "=====================================================================" | tee -a "$JOB_LOG"
echo "=== [$(date +'%Y-%m-%d %H:%M:%S')] Combined Extract & Eval Job Finished Successfully ===" | tee -a "$JOB_LOG"
echo "=====================================================================" | tee -a "$JOB_LOG"
