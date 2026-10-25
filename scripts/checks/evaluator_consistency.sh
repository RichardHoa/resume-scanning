#!/bin/bash
#SBATCH --job-name=eval_consistency
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=32
#SBATCH --mem=32G
#SBATCH --partition=student9696
#SBATCH --gres=gpu:nvidia_rtx_pro_6000_blackwell_server_edition_4g.96gb:1
#SBATCH --time=6:00:00
#SBATCH --output=logging/slurm_eval_consistency_%j.out
#SBATCH --error=logging/slurm_eval_consistency_%j.err

# -----------------------------------------------------------------------------
# SLURM Batch Job Script for the Evaluator Consistency Check
#
# Usage: sbatch scripts/checks/evaluator_consistency.sh [model] --cnb|--tech [--text]
#
# Extracts every resume of one resume set once, then evaluates that extraction 5 times (5 Repeat Evaluations, each
# with the production Category runs) and writes a report of what changes between them: Match Recommendation,
# Must-have Rejection, Overall and Category Scores, and each Verdict, with the reasoning behind each flipped Verdict
# (.scratch/evaluator-consistency/spec.md). No Review Panel runs.
#
# Only one HR RAG is stored, so set the resume set's HR RAG on the website's RAG page before submitting. Wipes
# runs/evaluator-consistency-cnb (--cnb) or runs/evaluator-consistency-tech (--tech) first; it holds the set's one
# extraction JSON per resume, the 5 evaluation JSONs per resume and evaluator_consistency_report.md / .json. The
# Tech set's Reference Date is December 2015, as in the extract and evaluate job.
#
# Combined Extraction (page images) is the default, so the model must be able to see images (VLLM_VISION=1);
# --text runs text-only extraction instead.
# -----------------------------------------------------------------------------

DATASET=""
SET_FLAGS=0
COMBINED=1
POSITIONAL_ARGS=()
for arg in "$@"; do
  case "$arg" in
    --cnb) DATASET="CnB"; SET_FLAGS=$((SET_FLAGS + 1)) ;;
    --tech) DATASET="Tech"; SET_FLAGS=$((SET_FLAGS + 1)) ;;
    --text) COMBINED=0 ;;
    *) POSITIONAL_ARGS+=("$arg") ;;
  esac
done
set -- "${POSITIONAL_ARGS[@]}"

# The resume set is never defaulted: it must match the stored HR RAG
if [ "$SET_FLAGS" -ne 1 ]; then
  echo "[ERROR] Pass exactly one of --cnb or --tech to pick the resume set." >&2
  exit 1
fi

if [ "$DATASET" = "Tech" ]; then
  REFERENCE_DATE="2015-12-31"
else
  REFERENCE_DATE=""
fi

RAW_MODEL="$1"

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
# STEP 3: Resolve the Model, Validate the Resume Set & Check the HR RAG
# -----------------------------------------------------------------------------
# Target model: a profile key or HuggingFace model ID (default: the DEFAULT_MODEL_KEY profile)
resolve_model_arg "$RAW_MODEL" || exit 1

# Combined Extraction: refuse a model that cannot see images before anything is wiped, then serve vision on
COMBINED_ARGS=()
if [ "$COMBINED" -eq 1 ]; then
  require_vision_profile || exit 1
  serve_vision_on "$COMBINED_MAX_PAGES"
  COMBINED_ARGS=(--combined)
fi

PDF_DIR="$PROJECT_ROOT/Vietnamese-dataset/$DATASET"
if [ ! -d "$PDF_DIR" ]; then
  echo "[ERROR] PDF directory '$PDF_DIR' does not exist." >&2
  exit 1
fi

require_hr_rag || exit 1

# -----------------------------------------------------------------------------
# STEP 4: Wipe the Set's Evaluator Consistency Run Folder
# -----------------------------------------------------------------------------
use_consistency_run_dir evaluator "$DATASET"

echo "====================================================================="
echo "[$(date +'%Y-%m-%d %H:%M:%S')] STEP 4: Wiping run folder '$RUN_DIR'..."
echo "====================================================================="

mkdir -p "$PROJECT_ROOT/logging"
reset_run_dir || exit 1

# -----------------------------------------------------------------------------
# STEP 5: Server Startup
# -----------------------------------------------------------------------------
JOB_LOG="$RUN_LOGS_DIR/consistency.log"
VLLM_LOG="$RUN_LOGS_DIR/vllm.log"

echo "=====================================================================" | tee -a "$JOB_LOG"
echo "[$(date +'%Y-%m-%d %H:%M:%S')] STEP 5: Inspecting GPU hardware allocation..." | tee -a "$JOB_LOG"
nvidia-smi 2>/dev/null | tee -a "$JOB_LOG" || echo "nvidia-smi not available" | tee -a "$JOB_LOG"
echo "=====================================================================" | tee -a "$JOB_LOG"

PORT=$(find_free_port)

echo "[$(date +'%H:%M:%S')] Project Root: $PROJECT_ROOT" | tee -a "$JOB_LOG"
echo "[$(date +'%H:%M:%S')] Dataset: $DATASET" | tee -a "$JOB_LOG"
echo "[$(date +'%H:%M:%S')] Reference Date: ${REFERENCE_DATE:-today}" | tee -a "$JOB_LOG"
echo "[$(date +'%H:%M:%S')] Run Folder: $RUN_DIR" | tee -a "$JOB_LOG"
echo "[$(date +'%H:%M:%S')] Target Model: $MODEL" | tee -a "$JOB_LOG"
echo "[$(date +'%H:%M:%S')] Combined Extraction: $([ "$COMBINED" -eq 1 ] && echo on || echo off)" | tee -a "$JOB_LOG"
echo "[$(date +'%H:%M:%S')] Allocated Server Port: $PORT" | tee -a "$JOB_LOG"
echo "[$(date +'%H:%M:%S')] Server Log File: $VLLM_LOG" | tee -a "$JOB_LOG"
echo "[$(date +'%H:%M:%S')] HF Cache Path: ${HF_HOME:-default}" | tee -a "$JOB_LOG"

start_vllm_server "$MODEL" "$PORT" "$VLLM_LOG" || exit 1

# -----------------------------------------------------------------------------
# STEP 6: One Extraction, then 5 Repeat Evaluations per Resume
# -----------------------------------------------------------------------------
echo "=====================================================================" | tee -a "$JOB_LOG"
echo "[$(date +'%Y-%m-%d %H:%M:%S')] === Evaluator Consistency: $DATASET ===" | tee -a "$JOB_LOG"
echo "=====================================================================" | tee -a "$JOB_LOG"

python3 -u "$PROJECT_ROOT/scripts/checks/evaluator_consistency.py" \
  --dir "$PDF_DIR" \
  --set-name "$DATASET" \
  --model-name "$MODEL" \
  --vllm-url "http://127.0.0.1:$PORT/v1" \
  --extract-workers 6 \
  --reference-date "$REFERENCE_DATE" \
  "${COMBINED_ARGS[@]}" 2>&1 | tee -a "$JOB_LOG"

STATUS=${PIPESTATUS[0]}

stop_vllm_server

echo "====================================================================="
echo "Report: $RUN_DIR/evaluator_consistency_report.md"
if [ "$STATUS" -ne 0 ]; then
  echo "=== [$(date +'%Y-%m-%d %H:%M:%S')] Evaluator Consistency Job Failed with exit code $STATUS ===" >&2
  exit 1
fi
echo "=== [$(date +'%Y-%m-%d %H:%M:%S')] Evaluator Consistency Job Finished Successfully ==="
