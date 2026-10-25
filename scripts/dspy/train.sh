#!/bin/bash
#SBATCH --job-name=train_dspy
#SBATCH --partition=student
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --gres=gpu:1
#SBATCH --time=16:00:00
#SBATCH --output=logging/slurm_%j.out
#SBATCH --error=logging/slurm_%j.err

# -----------------------------------------------------------------------------
# SLURM Batch Job Script for DSPy Teleprompter Prompt Optimization with vLLM
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

# Ensure output & log directories exist at project root
mkdir -p "$PROJECT_ROOT/logs" "$PROJECT_ROOT/logging" "$PROJECT_ROOT/prompts"

# Print GPU info on compute node immediately
echo "====================================================================="
echo "[$(date +'%Y-%m-%d %H:%M:%S')] STEP 4: Inspecting GPU hardware allocation..."
nvidia-smi 2>/dev/null || echo "nvidia-smi not available"
echo "====================================================================="

PORT=$(find_free_port)
resolve_model_arg "$RAW_MODEL" || exit 1

echo "[$(date +'%H:%M:%S')] Project Root: $PROJECT_ROOT"
echo "[$(date +'%H:%M:%S')] Target Model: $MODEL"
echo "[$(date +'%H:%M:%S')] Allocated Server Port: $PORT"
echo "[$(date +'%H:%M:%S')] HF Cache Path: ${HF_HOME:-default}"

# Check presence of extracted candidate resumes in the CnB run folder, which training reads by default
EXTRACTION_JSON_DIR="$PROJECT_ROOT/runs/batch-cnb/extraction_json"
JSON_COUNT=$(find "$EXTRACTION_JSON_DIR" -maxdepth 1 -name "*.json" 2>/dev/null | wc -l)
echo "[$(date +'%H:%M:%S')] Found $JSON_COUNT candidate JSON extractions in $EXTRACTION_JSON_DIR"
if [ "$JSON_COUNT" -eq 0 ]; then
  echo "[WARNING] No extracted resume JSONs found in $EXTRACTION_JSON_DIR. Candidate ground truth examples will use fallback text."
  echo "[WARNING] For best prompt optimization results, run step 1 extraction first."
fi

# Launch local vLLM server
start_vllm_server "$MODEL" "$PORT" "$PROJECT_ROOT/logs/vllm_train_dspy.log" || exit 1

echo "=== vLLM Server Ready! Starting DSPy Teleprompter Optimization ==="

python3 -u "$PROJECT_ROOT/src/cli/train_prompts.py" \
  --mode train \
  --teleprompter mipro \
  --auto-preset heavy \
  --eval-runs-per-category 1 \
  --num-threads 70 \
  --model-name "$MODEL" \
  --vllm-url "http://127.0.0.1:$PORT/v1" > "$PROJECT_ROOT/training.txt" 2>&1

stop_vllm_server
echo "=== [$(date +'%Y-%m-%d %H:%M:%S')] DSPy Teleprompter Training Job Finished ==="
