#!/bin/bash
#SBATCH --job-name=eval_bias_test
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=32GB
#SBATCH --partition=student9696
#SBATCH --gres=gpu:nvidia_rtx_pro_6000_blackwell_server_edition_4g.96gb:1
#SBATCH --time=12:00:00
#SBATCH --output=logging/slurm_eval_bias_%j.out
#SBATCH --error=logging/slurm_eval_bias_%j.err

# -----------------------------------------------------------------------------
# SLURM Batch Job Script for ATS Evaluator Bias & Positional Sensitivity Suite
# Usage:
#   sbatch scripts/checks/evaluator_bias.sh [--model <key>] [suite flags]
#   sbatch scripts/checks/evaluator_bias.sh --model glm4.7-flash --all
#   sbatch scripts/checks/evaluator_bias.sh --remaining
#   sbatch scripts/checks/evaluator_bias.sh --all
#   sbatch scripts/checks/evaluator_bias.sh --seniority_title
#   sbatch scripts/checks/evaluator_bias.sh --education_certifications
#   sbatch scripts/checks/evaluator_bias.sh --work_experience
#   sbatch scripts/checks/evaluator_bias.sh --technical_skills
#
# --model keys (default: DEFAULT_MODEL_KEY) are listed in MODEL_PROFILE_KEYS in scripts/lib/model_profiles.sh.
# Results go to bias-result/<model-key>/.
# -----------------------------------------------------------------------------

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

# Consume --model <key> / --model=<key>; forward all other arguments to evaluator_bias.py
MODEL_KEY_ARG=""
SUITE_ARGS=()
while [ $# -gt 0 ]; do
  case "$1" in
    --model)
      if [ -z "$2" ]; then
        echo "[ERROR] --model requires a key. Valid keys: $MODEL_PROFILE_KEYS" >&2
        exit 1
      fi
      MODEL_KEY_ARG="$2"
      shift 2
      ;;
    --model=*)
      MODEL_KEY_ARG="${1#--model=}"
      shift
      ;;
    *)
      SUITE_ARGS+=("$1")
      shift
      ;;
  esac
done

load_model_profile "${MODEL_KEY_ARG:-$DEFAULT_MODEL_KEY}" || exit 1

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

# Print GPU info
echo "====================================================================="
echo "[$(date +'%Y-%m-%d %H:%M:%S')] STEP 3: Inspecting GPU hardware allocation..."
nvidia-smi 2>/dev/null || echo "nvidia-smi not available"
echo "====================================================================="

PORT=$(find_free_port)

echo "[$(date +'%H:%M:%S')] Project Root: $PROJECT_ROOT"
echo "[$(date +'%H:%M:%S')] Target Model: $MODEL (profile: $MODEL_KEY)"
echo "[$(date +'%H:%M:%S')] Profile: CONCURRENCY=$CONCURRENCY MAX_EVAL_PER_SHUFFLE_KIND=$MAX_EVAL_PER_SHUFFLE_KIND VLLM_ENABLE_THINKING=$VLLM_ENABLE_THINKING VLLM_REASONING_STRENGTH=${VLLM_REASONING_STRENGTH:-(unset)}"
echo "[$(date +'%H:%M:%S')] Extra vLLM Args: ${VLLM_EXTRA_ARGS[*]:-(none)}"
echo "[$(date +'%H:%M:%S')] Allocated Server Port: $PORT"

export VLLM_URL="http://127.0.0.1:$PORT/v1"
export MODEL_NAME="$MODEL"

require_hr_rag || exit 1
start_vllm_server "$MODEL" "$PORT" "$PROJECT_ROOT/logs/vllm_evaluator_bias_${MODEL_KEY}.log" || exit 1

echo "=== vLLM Server Ready! ==="

# Pre-flight: Ensure at least one extracted resume JSON exists in output_jsons/
JSON_COUNT=$(find "$PROJECT_ROOT/output_jsons/" -maxdepth 1 -name "*.json" 2>/dev/null | wc -l | tr -d ' ')
if [ "$JSON_COUNT" -eq 0 ]; then
  echo "=== [Pre-Flight] 'output_jsons/' is empty. Extracting PDF resumes from 'pdfs/' first... ==="
  python3 -u "$PROJECT_ROOT/src/step_1_extractor.py" \
    --dir pdfs \
    --output output_jsons \
    --model-name "$MODEL" \
    --vllm-url "$VLLM_URL"
fi

echo "=== Starting Bias & Positional Order Sensitivity Suite (Arguments: ${SUITE_ARGS[*]:-'--remaining (default)'}) ==="
python3 -u "$PROJECT_ROOT/scripts/checks/evaluator_bias.py" "${SUITE_ARGS[@]}"

stop_vllm_server
echo "=== [$(date +'%Y-%m-%d %H:%M:%S')] Bias Detection Job Finished ==="
