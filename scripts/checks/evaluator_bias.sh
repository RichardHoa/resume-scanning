#!/bin/bash
#SBATCH --job-name=eval_bias_test
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=32GB
#SBATCH --partition=student9696
#SBATCH --gres=gpu:nvidia_rtx_pro_6000_blackwell_server_edition_4g.96gb:1
#SBATCH --time=12:00:00
#SBATCH --output=logging/slurm_eval_bias_%j.out
#SBATCH --error=logging/slurm_eval_bias_%j.err

# -----------------------------------------------------------------------------
# SLURM Batch Job Script for the Bias Check (.scratch/bias-check/spec.md)
# Usage:
#   sbatch scripts/checks/evaluator_bias.sh [category flags] [--dry-run]
#   sbatch scripts/checks/evaluator_bias.sh                  (all 4 categories)
#   sbatch scripts/checks/evaluator_bias.sh --seniority_title
#   sbatch scripts/checks/evaluator_bias.sh --education_certifications
#   sbatch scripts/checks/evaluator_bias.sh --work_experience
#   sbatch scripts/checks/evaluator_bias.sh --technical_skills
#
# Every flag is passed on to scripts/checks/evaluator_bias.py. --dry-run there mocks the extraction and evaluation
# (no LLM calls) to build every permutation and check the prompts; this job still wipes the run folder and starts
# vLLM, so for a quick check run `python3 scripts/checks/evaluator_bias.py --dry-run` directly instead.
#
# Runs on the default model profile only (DEFAULT_MODEL_KEY in scripts/lib/model_profiles.sh). Extracts the one fixed
# CnB resume (Vietnamese-dataset/CnB/CnB - Nguyen Ho Mi Sa.pdf) from scratch with Combined Extraction, then runs each
# category's Baseline and Shuffle Kinds as production Category runs.
#
# The resume is a CnB resume, so set the CnB HR RAG on the website's RAG page before submitting. Wipes runs/bias-cnb
# first; it holds the extraction JSON, the per-category CSVs, bias_summary.csv / report.txt / report.html, the prompt
# logs and the job and vLLM logs.
# -----------------------------------------------------------------------------

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
# STEP 1: Load Cluster Modules & Activate Conda Environment FIRST (config.sh reads src/core/config.py with python3)
# -----------------------------------------------------------------------------
echo "[$(date +'%H:%M:%S')] STEP 1: Loading system environment modules and activating Conda environment 'resume_env'..."
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
# STEP 3: Load the Default Model, Serve Vision On & Check the HR RAG
# -----------------------------------------------------------------------------
load_model_profile "$DEFAULT_MODEL_KEY" || exit 1

# Combined Extraction: refuse a model that cannot see images before anything is wiped, then serve vision on
require_vision_profile || exit 1
serve_vision_on "$COMBINED_MAX_PAGES"

BIAS_PDF="$PROJECT_ROOT/Vietnamese-dataset/CnB/CnB - Nguyen Ho Mi Sa.pdf"
if [ ! -f "$BIAS_PDF" ]; then
  echo "[ERROR] The Bias Check resume '$BIAS_PDF' does not exist." >&2
  exit 1
fi

require_hr_rag || exit 1

# -----------------------------------------------------------------------------
# STEP 4: Wipe the Bias Check Run Folder
# -----------------------------------------------------------------------------
use_bias_run_dir

echo "====================================================================="
echo "[$(date +'%Y-%m-%d %H:%M:%S')] STEP 4: Wiping run folder '$RUN_DIR'..."
echo "====================================================================="

mkdir -p "$PROJECT_ROOT/logging"
reset_run_dir || exit 1

# -----------------------------------------------------------------------------
# STEP 5: Server Startup
# -----------------------------------------------------------------------------
JOB_LOG="$RUN_LOGS_DIR/bias.log"
VLLM_LOG="$RUN_LOGS_DIR/vllm.log"

echo "=====================================================================" | tee -a "$JOB_LOG"
echo "[$(date +'%Y-%m-%d %H:%M:%S')] STEP 5: Inspecting GPU hardware allocation..." | tee -a "$JOB_LOG"
nvidia-smi 2>/dev/null | tee -a "$JOB_LOG" || echo "nvidia-smi not available" | tee -a "$JOB_LOG"
echo "=====================================================================" | tee -a "$JOB_LOG"

PORT=$(find_free_port)

echo "[$(date +'%H:%M:%S')] Project Root: $PROJECT_ROOT" | tee -a "$JOB_LOG"
echo "[$(date +'%H:%M:%S')] Run Folder: $RUN_DIR" | tee -a "$JOB_LOG"
echo "[$(date +'%H:%M:%S')] Target Model: $MODEL (profile: $MODEL_KEY)" | tee -a "$JOB_LOG"
echo "[$(date +'%H:%M:%S')] Profile: CONCURRENCY=$CONCURRENCY VLLM_ENABLE_THINKING=$VLLM_ENABLE_THINKING VLLM_REASONING_STRENGTH=${VLLM_REASONING_STRENGTH:-(unset)}" | tee -a "$JOB_LOG"
echo "[$(date +'%H:%M:%S')] Extra vLLM Args: ${VLLM_EXTRA_ARGS[*]:-(none)}" | tee -a "$JOB_LOG"
echo "[$(date +'%H:%M:%S')] Allocated Server Port: $PORT" | tee -a "$JOB_LOG"
echo "[$(date +'%H:%M:%S')] Server Log File: $VLLM_LOG" | tee -a "$JOB_LOG"

start_vllm_server "$MODEL" "$PORT" "$VLLM_LOG" || exit 1

# -----------------------------------------------------------------------------
# STEP 6: Extract the Resume, then Run the Bias Check
# -----------------------------------------------------------------------------
echo "=== Starting Bias Check (Arguments: ${*:-'all 4 categories (default)'}) ===" | tee -a "$JOB_LOG"
python3 -u "$PROJECT_ROOT/scripts/checks/evaluator_bias.py" \
  --vllm-url "http://127.0.0.1:$PORT/v1" \
  "$@" 2>&1 | tee -a "$JOB_LOG"

STATUS=${PIPESTATUS[0]}

stop_vllm_server

echo "====================================================================="
echo "Report: $RUN_DIR/report.html"
if [ "$STATUS" -ne 0 ]; then
  echo "=== [$(date +'%Y-%m-%d %H:%M:%S')] Bias Check Job Failed with exit code $STATUS ===" >&2
  exit 1
fi
echo "=== [$(date +'%Y-%m-%d %H:%M:%S')] Bias Check Job Finished Successfully ==="
