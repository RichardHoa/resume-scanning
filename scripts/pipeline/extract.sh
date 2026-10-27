#!/bin/bash
#SBATCH --job-name=extract_vllm
#SBATCH --partition=student
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=32G
#SBATCH --gres=gpu:1
#SBATCH --time=4:00:00
#SBATCH --output=logging/slurm_extract_%j.out
#SBATCH --error=logging/slurm_extract_%j.err

# -----------------------------------------------------------------------------
# SLURM Batch Job Script for Resume Batch Extraction with vLLM
#
# Usage: sbatch scripts/pipeline/extract.sh [pdf_dir] [model] --cnb|--tech
#
# Wipes the run folder (runs/batch-cnb with --cnb, runs/batch-tech with --tech) and extracts every PDF into it
# (docs/adr/0004-run-folders.md). --tech reads Vietnamese-dataset/Tech as of its Reference Date (December 2015);
# an explicit PDF dir argument still overrides the dataset folder. No evaluation runs, so no HR RAG is needed.
# Every resume is extracted with Combined Extraction: vLLM is served with vision on and the extractor also sees each
# page's image, for layout only (values still come from the PDF text). It needs a profile that can see images
# (VLLM_VISION=1).
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
require_vision_profile || exit 1
serve_vision_on "$COMBINED_MAX_PAGES"

use_pipeline_run_dir "$DATASET"
mkdir -p "$PROJECT_ROOT/logging"

if [ ! -d "$PDF_DIR" ]; then
  echo "[ERROR] PDF directory '$PDF_DIR' does not exist." >&2
  exit 1
fi

# -----------------------------------------------------------------------------
# STEP 4: Wipe the Run Folder & Start the vLLM Server
# -----------------------------------------------------------------------------
echo "====================================================================="
echo "[$(date +'%Y-%m-%d %H:%M:%S')] STEP 4: Inspecting GPU hardware allocation..."
nvidia-smi 2>/dev/null || echo "nvidia-smi not available"
echo "====================================================================="

PORT=$(find_free_port)

echo "[$(date +'%H:%M:%S')] Project Root: $PROJECT_ROOT"
echo "[$(date +'%H:%M:%S')] Target PDF Directory: $PDF_DIR"
echo "[$(date +'%H:%M:%S')] Dataset: $DATASET"
echo "[$(date +'%H:%M:%S')] Reference Date: ${REFERENCE_DATE:-today}"
echo "[$(date +'%H:%M:%S')] Run Folder: $RUN_DIR"
echo "[$(date +'%H:%M:%S')] Target Model: $MODEL"
echo "[$(date +'%H:%M:%S')] Allocated Server Port: $PORT"
echo "[$(date +'%H:%M:%S')] HF Cache Path: ${HF_HOME:-default}"

echo "[$(date +'%H:%M:%S')] Wiping run folder '$RUN_DIR' (the HR RAG and approved_jsons are kept)..."
reset_run_dir || exit 1

start_vllm_server "$MODEL" "$PORT" "$RUN_LOGS_DIR/vllm.log" || exit 1

# -----------------------------------------------------------------------------
# STEP 5: Batch Extraction
# -----------------------------------------------------------------------------
echo "=== [$(date +'%H:%M:%S')] STEP 5: vLLM Server Ready! Starting Batch Extraction ==="
echo "Processing PDFs from '$PDF_DIR' -> JSONs to '$EXTRACTION_JSON_DIR' using model '$MODEL'"

python3 -u "$PROJECT_ROOT/src/step_1_extractor.py" \
  --dir "$PDF_DIR" \
  --output "$EXTRACTION_JSON_DIR" \
  --model-name "$MODEL" \
  --vllm-url "http://127.0.0.1:$PORT/v1" \
  --workers 6 \
  --reference-date "$REFERENCE_DATE" 2>&1 | tee "$RUN_LOGS_DIR/extract.log"

stop_vllm_server
echo "=== [$(date +'%Y-%m-%d %H:%M:%S')] Batch Extraction Job Finished ==="
