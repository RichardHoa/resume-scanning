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
# SLURM Batch Job Script for DSPy Teleprompter Prompt Optimization with vLLM (src/cli/train_prompts.py)
#
# Usage: sbatch scripts/dspy/train.sh [model]
#   model  model profile key or HuggingFace model ID (default: the DEFAULT_MODEL_KEY profile)
#
# Runs MIPRO (heavy preset) against the evaluator's prompts, reading the candidate extractions in
# runs/batch-cnb/extraction_json (run scripts/pipeline/extract.sh --cnb first; without them the training examples
# use fallback text). Writes the compiled prompt to prompts/dspy_compiled_prompt.json and the training output to
# training.txt at the repository root; the vLLM log is logs/vllm_train_dspy.log.
#
# The optimizer is out of date (see src/optimization/dspy_evaluator.py): it predates the per-criterion reasoning and
# verdict format, so update it before running this job again.
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

# Ensure output & log directories exist at project root
mkdir -p "$PROJECT_ROOT/logs" "$PROJECT_ROOT/logging" "$PROJECT_ROOT/prompts"

# -----------------------------------------------------------------------------
# STEP 3: Resolve the Model, Check the Extractions & Start the vLLM Server
# -----------------------------------------------------------------------------
echo "====================================================================="
echo "[$(date +'%Y-%m-%d %H:%M:%S')] STEP 3: Inspecting GPU hardware allocation..."
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
  echo "[WARNING] For best prompt optimization results, run scripts/pipeline/extract.sh --cnb first."
fi

start_vllm_server "$MODEL" "$PORT" "$PROJECT_ROOT/logs/vllm_train_dspy.log" || exit 1

# -----------------------------------------------------------------------------
# STEP 4: DSPy Teleprompter Optimization
# -----------------------------------------------------------------------------
echo "=== [$(date +'%H:%M:%S')] STEP 4: vLLM Server Ready! Starting DSPy Teleprompter Optimization (output: training.txt) ==="

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
