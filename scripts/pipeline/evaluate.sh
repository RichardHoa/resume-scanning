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
# SLURM Batch Job Script for Resume Batch Evaluation with vLLM
#
# Usage: sbatch scripts/pipeline/evaluate.sh [model] --cnb|--tech
#
# Evaluates the extractions already in the run folder (runs/batch-cnb with --cnb, runs/batch-tech with --tech).
# Only the folder's evaluations are wiped first (their JSONs, prompt logs, token usage and logs); the extractions stay
# (docs/adr/0004-run-folders.md). With no extractions yet, the dataset's PDFs are extracted first, with Combined
# Extraction, so the model must then be a profile that can see images (VLLM_VISION=1).
#
# Each category is run several times and each Verdict voted across the runs (DEFAULT_NUM_EVALUATIONS in
# src/core/config.py), then the Review Panel writes each report's Candidate Feedback. Evaluation uses the HR RAG as
# HR set it on the website's RAG page and never builds or changes it: set the resume set's HR RAG before submitting,
# or the job stops before it starts the server. --tech also sets the Reference Date (the date the prompts treat as today) to December 2015.
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
# STEP 3: Resolve the Model, Check the HR RAG & Wipe the Evaluations
# -----------------------------------------------------------------------------
# Target model: a profile key or HuggingFace model ID (default: the DEFAULT_MODEL_KEY profile)
resolve_model_arg "$RAW_MODEL" || exit 1

use_pipeline_run_dir "$DATASET"
mkdir -p "$PROJECT_ROOT/logging"

require_hr_rag || exit 1

PDF_DIR="$PROJECT_ROOT/Vietnamese-dataset/$DATASET"
JSON_COUNT=$(find "$EXTRACTION_JSON_DIR/" -maxdepth 1 -name "*.json" 2>/dev/null | wc -l | tr -d ' ')
if [ "$JSON_COUNT" -eq 0 ]; then
  # Nothing to evaluate yet, so the job extracts first: Combined Extraction needs a model that can see images and
  # vLLM served with vision on
  if [ ! -d "$PDF_DIR" ]; then
    echo "[ERROR] '$EXTRACTION_JSON_DIR' is empty and PDF directory '$PDF_DIR' does not exist." >&2
    exit 1
  fi
  require_vision_profile || exit 1
  serve_vision_on "$COMBINED_MAX_PAGES"
fi

PORT=$(find_free_port)

echo "[$(date +'%H:%M:%S')] Project Root: $PROJECT_ROOT"
echo "[$(date +'%H:%M:%S')] Dataset: $DATASET"
echo "[$(date +'%H:%M:%S')] Reference Date: ${REFERENCE_DATE:-today}"
echo "[$(date +'%H:%M:%S')] Run Folder: $RUN_DIR"
echo "[$(date +'%H:%M:%S')] Extractions Found: $JSON_COUNT"
echo "[$(date +'%H:%M:%S')] Target Model: $MODEL"
echo "[$(date +'%H:%M:%S')] Allocated Server Port: $PORT"
echo "[$(date +'%H:%M:%S')] HF Cache Path: ${HF_HOME:-default}"

echo "[$(date +'%H:%M:%S')] Wiping the evaluations in '$RUN_DIR' (extractions are kept)..."
reset_run_dir_evaluations || exit 1

# -----------------------------------------------------------------------------
# STEP 4: Start the vLLM Server
# -----------------------------------------------------------------------------
echo "====================================================================="
echo "[$(date +'%Y-%m-%d %H:%M:%S')] STEP 4: Inspecting GPU hardware allocation..."
nvidia-smi 2>/dev/null || echo "nvidia-smi not available"
echo "====================================================================="

start_vllm_server "$MODEL" "$PORT" "$RUN_LOGS_DIR/vllm_eval.log" || exit 1

# -----------------------------------------------------------------------------
# STEP 5: Extract First if the Run Folder Has No Extractions
# -----------------------------------------------------------------------------
if [ "$JSON_COUNT" -eq 0 ]; then
  echo "=== [$(date +'%H:%M:%S')] STEP 5: '$EXTRACTION_JSON_DIR' is empty. Extracting PDF resumes from '$PDF_DIR' first... ==="
  python3 -u "$PROJECT_ROOT/src/step_1_extractor.py" \
    --dir "$PDF_DIR" \
    --output "$EXTRACTION_JSON_DIR" \
    --model-name "$MODEL" \
    --vllm-url "http://127.0.0.1:$PORT/v1" \
    --workers 6 \
    --reference-date "$REFERENCE_DATE" 2>&1 | tee "$RUN_LOGS_DIR/extract.log"

  EXTRACT_STATUS=${PIPESTATUS[0]}
  if [ "$EXTRACT_STATUS" -ne 0 ]; then
    echo "[CRITICAL ERROR] Batch extraction failed with exit code $EXTRACT_STATUS!" >&2
    stop_vllm_server
    exit "$EXTRACT_STATUS"
  fi
fi

# -----------------------------------------------------------------------------
# STEP 6: Batch Evaluation
# -----------------------------------------------------------------------------
echo "=== [$(date +'%H:%M:%S')] STEP 6: Starting Batch Evaluation ==="
python3 -u "$PROJECT_ROOT/src/step_2_evaluate.py" \
  --model-name "$MODEL" \
  --vllm-url "http://127.0.0.1:$PORT/v1" \
  --dir "$EXTRACTION_JSON_DIR" \
  --output "$EVALUATION_JSON_DIR" \
  --reference-date "$REFERENCE_DATE" 2>&1 | tee "$RUN_LOGS_DIR/eval.log"

stop_vllm_server
echo "=== [$(date +'%Y-%m-%d %H:%M:%S')] Batch Evaluation Job Finished ==="
