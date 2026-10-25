#!/bin/bash
#SBATCH --job-name=extract_consistency
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=32
#SBATCH --mem=32G
#SBATCH --partition=student9696
#SBATCH --gres=gpu:nvidia_rtx_pro_6000_blackwell_server_edition_4g.96gb:1
#SBATCH --time=3:00:00
#SBATCH --output=logging/slurm_extract_consistency_%j.out
#SBATCH --error=logging/slurm_extract_consistency_%j.err

# -----------------------------------------------------------------------------
# SLURM Batch Job Script for the Extractor Consistency Check
#
# Usage: sbatch scripts/checks/extractor_consistency.sh [model] [--text]
#
# Extracts every resume of both resume sets, CnB then Tech, 5 times on one vLLM server, and writes a report of
# what changes between the runs, with every Fidelity Warning and failed run (.scratch/extractor-consistency/spec.md).
# Wipes runs/extractor-consistency-cnb and runs/extractor-consistency-tech first; each holds its set's 5 extraction
# JSONs per resume and consistency_report.md / .json. No evaluation runs, so no HR RAG is needed. The Tech set's
# Reference Date is December 2015, as in the extract and evaluate job.
#
# Combined Extraction (page images) is the default, so the model must be able to see images (VLLM_VISION=1);
# --text runs text-only extraction instead.
# -----------------------------------------------------------------------------

COMBINED=1
POSITIONAL_ARGS=()
for arg in "$@"; do
  case "$arg" in
    --text) COMBINED=0 ;;
    *) POSITIONAL_ARGS+=("$arg") ;;
  esac
done
set -- "${POSITIONAL_ARGS[@]}"

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
# STEP 3: Resolve the Model & Validate the Resume Sets
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

DATASETS=(CnB Tech)
for DATASET in "${DATASETS[@]}"; do
  if [ ! -d "$PROJECT_ROOT/Vietnamese-dataset/$DATASET" ]; then
    echo "[ERROR] PDF directory '$PROJECT_ROOT/Vietnamese-dataset/$DATASET' does not exist." >&2
    exit 1
  fi
done

# -----------------------------------------------------------------------------
# STEP 4: Wipe Both Consistency Run Folders
# -----------------------------------------------------------------------------
echo "====================================================================="
echo "[$(date +'%Y-%m-%d %H:%M:%S')] STEP 4: Wiping runs/extractor-consistency-cnb and runs/extractor-consistency-tech..."
echo "====================================================================="

mkdir -p "$PROJECT_ROOT/logging"
for DATASET in "${DATASETS[@]}"; do
  use_consistency_run_dir extractor "$DATASET"
  reset_run_dir || exit 1
done

# -----------------------------------------------------------------------------
# STEP 5: Server Startup (its log goes in the CnB folder, which runs first)
# -----------------------------------------------------------------------------
use_consistency_run_dir extractor CnB
VLLM_LOG="$RUN_LOGS_DIR/vllm.log"

echo "====================================================================="
echo "[$(date +'%Y-%m-%d %H:%M:%S')] STEP 5: Inspecting GPU hardware allocation..."
nvidia-smi 2>/dev/null || echo "nvidia-smi not available"
echo "====================================================================="

PORT=$(find_free_port)

echo "[$(date +'%H:%M:%S')] Project Root: $PROJECT_ROOT"
echo "[$(date +'%H:%M:%S')] Target Model: $MODEL"
echo "[$(date +'%H:%M:%S')] Combined Extraction: $([ "$COMBINED" -eq 1 ] && echo on || echo off)"
echo "[$(date +'%H:%M:%S')] Allocated Server Port: $PORT"
echo "[$(date +'%H:%M:%S')] Server Log File: $VLLM_LOG"
echo "[$(date +'%H:%M:%S')] HF Cache Path: ${HF_HOME:-default}"

start_vllm_server "$MODEL" "$PORT" "$VLLM_LOG" || exit 1

# -----------------------------------------------------------------------------
# STEP 6: Each Resume Set, 5 Extractions per Resume
# -----------------------------------------------------------------------------
FAILED_SETS=()
for DATASET in "${DATASETS[@]}"; do
  use_consistency_run_dir extractor "$DATASET"
  JOB_LOG="$RUN_LOGS_DIR/consistency.log"
  # A server that died during the previous set would fail every extraction of this one
  if ! kill -0 "$VLLM_PID" 2>/dev/null; then
    echo "[ERROR] vLLM server (PID $VLLM_PID) is no longer running; skipping $DATASET. See $VLLM_LOG." | tee -a "$JOB_LOG" >&2
    FAILED_SETS+=("$DATASET")
    continue
  fi
  if [ "$DATASET" = "Tech" ]; then
    REFERENCE_DATE="2015-12-31"
  else
    REFERENCE_DATE=""
  fi

  echo "=====================================================================" | tee -a "$JOB_LOG"
  echo "[$(date +'%Y-%m-%d %H:%M:%S')] === Extractor Consistency: $DATASET ===" | tee -a "$JOB_LOG"
  echo "Run Folder: $RUN_DIR, Reference Date: ${REFERENCE_DATE:-today}" | tee -a "$JOB_LOG"
  echo "=====================================================================" | tee -a "$JOB_LOG"

  python3 -u "$PROJECT_ROOT/scripts/checks/extractor_consistency.py" \
    --dir "$PROJECT_ROOT/Vietnamese-dataset/$DATASET" \
    --set-name "$DATASET" \
    --model-name "$MODEL" \
    --vllm-url "http://127.0.0.1:$PORT/v1" \
    --workers 6 \
    --reference-date "$REFERENCE_DATE" \
    "${COMBINED_ARGS[@]}" 2>&1 | tee -a "$JOB_LOG"

  STATUS=${PIPESTATUS[0]}
  if [ "$STATUS" -ne 0 ]; then
    echo "[ERROR] Consistency check for $DATASET failed with exit code $STATUS." | tee -a "$JOB_LOG" >&2
    FAILED_SETS+=("$DATASET")
  fi
done

stop_vllm_server

echo "====================================================================="
echo "Reports: $PROJECT_ROOT/runs/extractor-consistency-cnb/consistency_report.md"
echo "         $PROJECT_ROOT/runs/extractor-consistency-tech/consistency_report.md"
if [ "${#FAILED_SETS[@]}" -gt 0 ]; then
  echo "=== [$(date +'%Y-%m-%d %H:%M:%S')] Extractor Consistency Job Finished; failed: ${FAILED_SETS[*]} ===" >&2
  exit 1
fi
echo "=== [$(date +'%Y-%m-%d %H:%M:%S')] Extractor Consistency Job Finished Successfully ==="
