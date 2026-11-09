#!/bin/bash
#SBATCH --job-name=extract_accuracy
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=32
#SBATCH --mem=32G
#SBATCH --partition=student9696
#SBATCH --gres=gpu:nvidia_rtx_pro_6000_blackwell_server_edition_4g.96gb:1
#SBATCH --time=10:00:00
#SBATCH --output=logging/slurm_extract_accuracy_%j.out
#SBATCH --error=logging/slurm_extract_accuracy_%j.err

# -----------------------------------------------------------------------------
# SLURM Batch Job Script for the Extractor Accuracy Check
#
# Usage: sbatch scripts/checks/extractor_accuracy.sh [model]
#
# Extracts every resume that has a Ground Truth Extraction in data/extraction_ground_truth 5 times, CnB then Tech,
# on one vLLM server, and reports how often each value matches the ground truth (.scratch/extractor-accuracy/spec.md).
# Wipes runs/extractor-accuracy first; it holds the 5 extraction JSONs per resume and accuracy_report.md / .json.
# No evaluation runs, so no HR RAG is needed. The Tech set's Reference Date is December 2015, as in the extract and
# evaluate job.
#
# Every resume is extracted with Combined Extraction: vLLM is served with vision on and the extractor also sees each
# page's image, for layout only (values still come from the PDF text). It needs a profile that can see images
# (VLLM_VISION=1).
# -----------------------------------------------------------------------------

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
# STEP 3: Resolve the Model & Validate the Ground Truth Extractions
# -----------------------------------------------------------------------------
# Target model: a profile key or HuggingFace model ID (default: the DEFAULT_MODEL_KEY profile)
resolve_model_arg "$RAW_MODEL" || exit 1

# Combined Extraction: refuse a model that cannot see images before anything is wiped, then serve vision on
require_vision_profile || exit 1
serve_vision_on "$COMBINED_MAX_PAGES"

# Every Ground Truth Extraction needs the PDF of the same name in one resume set, checked before the server starts
GROUND_TRUTH_DIR="$PROJECT_ROOT/data/extraction_ground_truth"
shopt -s nullglob
GROUND_TRUTHS=("$GROUND_TRUTH_DIR"/*.json)
shopt -u nullglob
if [ "${#GROUND_TRUTHS[@]}" -eq 0 ]; then
  echo "[ERROR] No Ground Truth Extractions found in '$GROUND_TRUTH_DIR'." >&2
  exit 1
fi
MISSING_PDFS=()
for GT in "${GROUND_TRUTHS[@]}"; do
  RESUME="$(basename "$GT" .json)"
  if [ ! -f "$PROJECT_ROOT/Vietnamese-dataset/CnB/$RESUME.pdf" ] && [ ! -f "$PROJECT_ROOT/Vietnamese-dataset/Tech/$RESUME.pdf" ]; then
    MISSING_PDFS+=("$RESUME")
  fi
done
if [ "${#MISSING_PDFS[@]}" -gt 0 ]; then
  echo "[ERROR] No PDF in Vietnamese-dataset/CnB or Vietnamese-dataset/Tech for ground truth: ${MISSING_PDFS[*]}" >&2
  exit 1
fi

# -----------------------------------------------------------------------------
# STEP 4: Wipe the Accuracy Run Folder
# -----------------------------------------------------------------------------
echo "====================================================================="
echo "[$(date +'%Y-%m-%d %H:%M:%S')] STEP 4: Wiping runs/extractor-accuracy..."
echo "====================================================================="

mkdir -p "$PROJECT_ROOT/logging"
use_accuracy_run_dir
reset_run_dir || exit 1
VLLM_LOG="$RUN_LOGS_DIR/vllm.log"
JOB_LOG="$RUN_LOGS_DIR/accuracy.log"

# -----------------------------------------------------------------------------
# STEP 5: Server Startup
# -----------------------------------------------------------------------------
echo "====================================================================="
echo "[$(date +'%Y-%m-%d %H:%M:%S')] STEP 5: Inspecting GPU hardware allocation..."
nvidia-smi 2>/dev/null || echo "nvidia-smi not available"
echo "====================================================================="

PORT=$(find_free_port)

echo "[$(date +'%H:%M:%S')] Project Root: $PROJECT_ROOT"
echo "[$(date +'%H:%M:%S')] Target Model: $MODEL"
echo "[$(date +'%H:%M:%S')] Allocated Server Port: $PORT"
echo "[$(date +'%H:%M:%S')] Server Log File: $VLLM_LOG"
echo "[$(date +'%H:%M:%S')] HF Cache Path: ${HF_HOME:-default}"

start_vllm_server "$MODEL" "$PORT" "$VLLM_LOG" || exit 1

# -----------------------------------------------------------------------------
# STEP 6: Both Resume Sets, 5 Extractions per Resume
# -----------------------------------------------------------------------------
echo "=====================================================================" | tee -a "$JOB_LOG"
echo "[$(date +'%Y-%m-%d %H:%M:%S')] === Extractor Accuracy: ${#GROUND_TRUTHS[@]} Ground Truth Extractions ===" | tee -a "$JOB_LOG"
echo "Run Folder: $RUN_DIR" | tee -a "$JOB_LOG"
echo "=====================================================================" | tee -a "$JOB_LOG"

python3 -u "$PROJECT_ROOT/scripts/checks/extractor_accuracy.py" \
  --model-name "$MODEL" \
  --vllm-url "http://127.0.0.1:$PORT/v1" \
  --workers 10 2>&1 | tee -a "$JOB_LOG"

STATUS=${PIPESTATUS[0]}

stop_vllm_server

echo "====================================================================="
echo "Report: $PROJECT_ROOT/runs/extractor-accuracy/accuracy_report.md"
if [ "$STATUS" -ne 0 ]; then
  echo "=== [$(date +'%Y-%m-%d %H:%M:%S')] Extractor Accuracy Job Failed with exit code $STATUS ===" >&2
  exit 1
fi
echo "=== [$(date +'%Y-%m-%d %H:%M:%S')] Extractor Accuracy Job Finished Successfully ==="
