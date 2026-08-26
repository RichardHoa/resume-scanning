#!/bin/bash
#SBATCH --job-name=eval_bias_test
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=128GB
#SBATCH --partition=student9696
#SBATCH --gres=gpu:nvidia_rtx_pro_6000_blackwell_server_edition_4g.96gb
#SBATCH --time=10:00:00
#SBATCH --output=logging/slurm_eval_bias_%j.out
#SBATCH --error=logging/slurm_eval_bias_%j.err

# -----------------------------------------------------------------------------
# SLURM Batch Job Script for ATS Evaluator Bias & Positional Sensitivity Suite
# Usage:
#   sbatch scripts/check_evaluator_bias.sh --remaining
#   sbatch scripts/check_evaluator_bias.sh --all
#   sbatch scripts/check_evaluator_bias.sh --seniority_title
#   sbatch scripts/check_evaluator_bias.sh --education_certifications
#   sbatch scripts/check_evaluator_bias.sh --work_experience
#   sbatch scripts/check_evaluator_bias.sh --technical_skills
# -----------------------------------------------------------------------------

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

# Ensure output & log directories exist at project root
mkdir -p "$PROJECT_ROOT/logs" "$PROJECT_ROOT/evaluation_json" "$PROJECT_ROOT/logging" "$PROJECT_ROOT/logging/bias_prompts" "$PROJECT_ROOT/output_jsons" "$PROJECT_ROOT/pdfs" "$PROJECT_ROOT/bias-result"

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

# Ensure critical evaluation dependencies are present
if ! python3 -c "import sentence_transformers, chromadb" 2>/dev/null; then
  echo "[NOTICE] Auto-installing missing evaluation dependencies via pip..."
  python3 -m pip install sentence-transformers chromadb 2>/dev/null || pip install sentence-transformers chromadb 2>/dev/null || true
fi

# Print GPU info
echo "====================================================================="
echo "[$(date +'%Y-%m-%d %H:%M:%S')] STEP 3: Inspecting GPU hardware allocation..."
nvidia-smi 2>/dev/null || echo "nvidia-smi not available"
echo "====================================================================="

PORT=$(find_free_port)
MODEL="Qwen/Qwen3.5-35B-A3B"

echo "[$(date +'%H:%M:%S')] Project Root: $PROJECT_ROOT"
echo "[$(date +'%H:%M:%S')] Target Model: $MODEL"
echo "[$(date +'%H:%M:%S')] Allocated Server Port: $PORT"

export VLLM_URL="http://127.0.0.1:$PORT/v1"
export MODEL_NAME="$MODEL"

start_vllm_server "$MODEL" "$PORT" "$PROJECT_ROOT/logs/vllm_evaluator_bias.log" || exit 1

echo "=== vLLM Server Ready! ==="

# Pre-flight: Ensure at least one extracted resume JSON exists in output_jsons/
JSON_COUNT=$(find "$PROJECT_ROOT/output_jsons/" -maxdepth 1 -name "*.json" 2>/dev/null | wc -l | tr -d ' ')
if [ "$JSON_COUNT" -eq 0 ]; then
  echo "=== [Pre-Flight] 'output_jsons/' is empty. Extracting PDF resumes from 'pdfs/' first... ==="
  python3 -u "$PROJECT_ROOT/src/step_1_extractor.py" \
    --dir pdfs \
    --output output_jsons \
    --model-name "$MODEL" \
    --backend vllm \
    --vllm-url "$VLLM_URL"
fi

export CONCURRENCY=100
export MAX_EVAL_PER_SHUFFLE_KIND=1000
echo "=== Starting Bias & Positional Order Sensitivity Suite (Arguments: ${*:-'--remaining (default)'}) ==="
python3 -u "$PROJECT_ROOT/scripts/run_bias_detection.py" "$@"

stop_vllm_server
echo "=== [$(date +'%Y-%m-%d %H:%M:%S')] Bias Detection Job Finished ==="
