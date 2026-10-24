#!/bin/bash
#SBATCH --job-name=eval_vllm
#SBATCH --partition=student
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --gres=gpu:1
#SBATCH --time=12:00:00
#SBATCH --output=logging/slurm_%j.out
#SBATCH --error=logging/slurm_%j.err

# -----------------------------------------------------------------------------
# SLURM Batch Job Script for High-Speed vLLM Resume Evaluation Server
#
# Usage: sbatch scripts/submit_eval_vllm.sh [model] --cnb|--tech
#
# Evaluates the extractions already in the run folder (runs/batch-cnb with --cnb, runs/batch-tech with --tech).
# Only the folder's evaluations are wiped first (their JSONs, prompt logs, token usage and logs); the extractions stay
# (docs/adr/0010-run-folders.md). With no extractions yet, the dataset's PDFs are extracted first.
# -----------------------------------------------------------------------------

DATASET=""
SET_FLAGS=0
POSITIONAL_ARGS=()
for arg in "$@"; do
  case "$arg" in
    --cnb) DATASET="CnB"; SET_FLAGS=$((SET_FLAGS + 1)) ;;
    --tech) DATASET="Tech"; SET_FLAGS=$((SET_FLAGS + 1)) ;;
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

RAW_MODEL="$1"
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

use_pipeline_run_dir "$DATASET"
mkdir -p "$PROJECT_ROOT/logging"

# Load cluster modules (miniconda3)
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
echo "[$(date +'%H:%M:%S')] Step 2 complete. Active Python: $(which python3 2>/dev/null || echo 'python3 not found')"

# Print GPU info on compute node immediately
echo "====================================================================="
echo "[$(date +'%Y-%m-%d %H:%M:%S')] STEP 3: Inspecting GPU hardware allocation..."
nvidia-smi 2>/dev/null || echo "nvidia-smi not available"
echo "====================================================================="

require_hr_rag || exit 1
PORT=$(find_free_port)
resolve_model_arg "$RAW_MODEL" || exit 1

echo "[$(date +'%H:%M:%S')] Project Root: $PROJECT_ROOT"
echo "[$(date +'%H:%M:%S')] Dataset: $DATASET"
echo "[$(date +'%H:%M:%S')] Reference Date: ${REFERENCE_DATE:-today}"
echo "[$(date +'%H:%M:%S')] Run Folder: $RUN_DIR"
echo "[$(date +'%H:%M:%S')] Target Model: $MODEL"
echo "[$(date +'%H:%M:%S')] Allocated Server Port: $PORT"
echo "[$(date +'%H:%M:%S')] HF Cache Path: ${HF_HOME:-default}"

echo "[$(date +'%H:%M:%S')] Wiping the evaluations in '$RUN_DIR' (extractions are kept)..."
reset_run_dir_evaluations || exit 1

start_vllm_server "$MODEL" "$PORT" "$RUN_LOGS_DIR/vllm_eval.log" || exit 1

echo "=== vLLM Server Ready! ==="

JSON_COUNT=$(find "$EXTRACTION_JSON_DIR/" -maxdepth 1 -name "*.json" 2>/dev/null | wc -l | tr -d ' ')
if [ "$JSON_COUNT" -eq 0 ]; then
  echo "=== [Step 1 Auto-Run] '$EXTRACTION_JSON_DIR' is empty. Extracting PDF resumes from 'Vietnamese-dataset/$DATASET' first... ==="
  python3 -u "$PROJECT_ROOT/src/step_1_extractor.py" \
    --dir "$PROJECT_ROOT/Vietnamese-dataset/$DATASET" \
    --output "$EXTRACTION_JSON_DIR" \
    --model-name "$MODEL" \
    --vllm-url "http://127.0.0.1:$PORT/v1" \
    --reference-date "$REFERENCE_DATE" 2>&1 | tee "$RUN_LOGS_DIR/extract.log"
fi

echo "=== Starting Step 2 High-Precision vLLM Batch Evaluation ==="
python3 -u "$PROJECT_ROOT/src/step_2_evaluate.py" \
  --model-name "$MODEL" \
  --vllm-url "http://127.0.0.1:$PORT/v1" \
  --dir "$EXTRACTION_JSON_DIR" \
  --output "$EVALUATION_JSON_DIR" \
  --reference-date "$REFERENCE_DATE" 2>&1 | tee "$RUN_LOGS_DIR/eval.log"

stop_vllm_server
echo "=== [$(date +'%Y-%m-%d %H:%M:%S')] Batch Evaluation Job Finished ==="
