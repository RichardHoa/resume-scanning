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
# SLURM Batch Job Script for High-Speed vLLM Resume Batch Extraction
#
# Usage: sbatch scripts/submit_extract_vllm.sh [pdf_dir] [model] [--tech] [--combined]
#
# Wipes the run folder (runs/full-cnb, or runs/full-tech with --tech) and extracts every PDF into it
# (docs/adr/0010-run-folders.md). --tech reads Vietnamese-dataset/Tech as of its Reference Date (December 2015);
# an explicit PDF dir argument still overrides the dataset folder.
# --combined runs Combined Extraction: vLLM is served with vision on and the extractor also sees each page's image,
# for layout only (values still come from the PDF text). It needs a profile that can see images (VLLM_VISION=1).
# -----------------------------------------------------------------------------

DATASET="CnB"
COMBINED=0
POSITIONAL_ARGS=()
for arg in "$@"; do
  case "$arg" in
    --tech) DATASET="Tech" ;;
    --combined) COMBINED=1 ;;
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

PORT=$(find_free_port)

echo "[$(date +'%H:%M:%S')] Project Root: $PROJECT_ROOT"
echo "[$(date +'%H:%M:%S')] Target PDF Directory: $PDF_DIR"
echo "[$(date +'%H:%M:%S')] Dataset: $DATASET"
echo "[$(date +'%H:%M:%S')] Reference Date: ${REFERENCE_DATE:-today}"
echo "[$(date +'%H:%M:%S')] Run Folder: $RUN_DIR"
echo "[$(date +'%H:%M:%S')] Target Model: $MODEL"
echo "[$(date +'%H:%M:%S')] Combined Extraction: $([ "$COMBINED" -eq 1 ] && echo on || echo off)"
echo "[$(date +'%H:%M:%S')] Allocated Server Port: $PORT"
echo "[$(date +'%H:%M:%S')] HF Cache Path: ${HF_HOME:-default}"

if [ ! -d "$PDF_DIR" ]; then
  echo "[ERROR] PDF directory '$PDF_DIR' does not exist."
  exit 1
fi

echo "[$(date +'%H:%M:%S')] Wiping run folder '$RUN_DIR' (the HR RAG and approved_jsons are kept)..."
reset_run_dir || exit 1

start_vllm_server "$MODEL" "$PORT" "$RUN_LOGS_DIR/vllm.log" || exit 1

echo "=== vLLM Server Ready! Starting Batch Extraction ==="
echo "Processing PDFs from '$PDF_DIR' -> JSONs to '$EXTRACTION_JSON_DIR' using model '$MODEL'"

python3 -u "$PROJECT_ROOT/src/step_1_extractor.py" \
  --dir "$PDF_DIR" \
  --output "$EXTRACTION_JSON_DIR" \
  --model-name "$MODEL" \
  --vllm-url "http://127.0.0.1:$PORT/v1" \
  --workers 6 \
  --reference-date "$REFERENCE_DATE" \
  "${COMBINED_ARGS[@]}" 2>&1 | tee "$RUN_LOGS_DIR/extract.log"

stop_vllm_server
echo "=== [$(date +'%Y-%m-%d %H:%M:%S')] Batch Extraction Job Finished ==="
