#!/bin/bash
#SBATCH --job-name=extract_vllm
#SBATCH --partition=researcher
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --gres=gpu:1
#SBATCH --time=12:00:00
#SBATCH --output=logging/slurm_extract_%j.out
#SBATCH --error=logging/slurm_extract_%j.err

# -----------------------------------------------------------------------------
# SLURM Batch Job Script for High-Speed vLLM Resume Batch Extraction
# -----------------------------------------------------------------------------

RAW_PDF_DIR="$1"
RAW_MODEL="$2"
RAW_OUTPUT_DIR="$3"
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

if [ -z "$PROJECT_ROOT" ]; then
  echo "[CRITICAL ERROR] PROJECT_ROOT is not set after sourcing config.sh!" >&2
  exit 1
fi

# Force execution strictly from project repository root directory
cd "$PROJECT_ROOT" || exit 1

# Setup optimization & threading environment variables
setup_vllm_env

# Resolve PDF input directory (Default: Vietnamese-dataset/CnB inside project root)
if [ -n "$RAW_PDF_DIR" ]; then
  if [[ "$RAW_PDF_DIR" = /* ]]; then
    PDF_DIR="$RAW_PDF_DIR"
  elif [ -d "$INITIAL_CWD/$RAW_PDF_DIR" ]; then
    PDF_DIR="$(cd "$INITIAL_CWD/$RAW_PDF_DIR" && pwd)"
  else
    PDF_DIR="$PROJECT_ROOT/$RAW_PDF_DIR"
  fi
else
  PDF_DIR="$PROJECT_ROOT/Vietnamese-dataset/CnB"
fi

# Target Model Name (Default: Qwen/Qwen3.5-35B-A3B)
MODEL="${RAW_MODEL:-Qwen/Qwen3.5-35B-A3B}"

# Target Output Directory (Default: output_jsons inside project root)
if [ -n "$RAW_OUTPUT_DIR" ]; then
  if [[ "$RAW_OUTPUT_DIR" = /* ]]; then
    OUTPUT_DIR="$RAW_OUTPUT_DIR"
  elif [ -d "$INITIAL_CWD/$RAW_OUTPUT_DIR" ]; then
    OUTPUT_DIR="$(cd "$INITIAL_CWD/$RAW_OUTPUT_DIR" && pwd)"
  else
    OUTPUT_DIR="$PROJECT_ROOT/$RAW_OUTPUT_DIR"
  fi
else
  OUTPUT_DIR="$PROJECT_ROOT/output_jsons"
fi

# Ensure output & log directories exist at project root
mkdir -p "$PROJECT_ROOT/logs" "$PROJECT_ROOT/evaluation_json" "$PROJECT_ROOT/logging" "$PROJECT_ROOT/output_jsons" "$PROJECT_ROOT/pdfs" "$OUTPUT_DIR"

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
echo "[$(date +'%H:%M:%S')] Target Output Directory: $OUTPUT_DIR"
echo "[$(date +'%H:%M:%S')] Target Model: $MODEL"
echo "[$(date +'%H:%M:%S')] Allocated Server Port: $PORT"
echo "[$(date +'%H:%M:%S')] HF Cache Path: ${HF_HOME:-default}"

if [ ! -d "$PDF_DIR" ]; then
  echo "[ERROR] PDF directory '$PDF_DIR' does not exist."
  exit 1
fi

start_vllm_server "$MODEL" "$PORT" "$PROJECT_ROOT/logs/vllm_extract.log" || exit 1

echo "=== vLLM Server Ready! Starting Batch Extraction ==="
echo "Processing PDFs from '$PDF_DIR' -> JSONs to '$OUTPUT_DIR' using model '$MODEL'"

python3 -u "$PROJECT_ROOT/src/step_1_extractor.py" \
  --dir "$PDF_DIR" \
  --output "$OUTPUT_DIR" \
  --model-name "$MODEL" \
  --backend vllm \
  --vllm-url "http://127.0.0.1:$PORT/v1"

stop_vllm_server
echo "=== [$(date +'%Y-%m-%d %H:%M:%S')] Batch Extraction Job Finished ==="
