#!/bin/bash
#SBATCH --job-name=proofread_vllm
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=32G
#SBATCH --partition=student9696
#SBATCH --gres=gpu:nvidia_rtx_pro_6000_blackwell_server_edition_4g.96gb:1
#SBATCH --time=4:00:00
#SBATCH --output=logging/slurm_proofread_%j.out
#SBATCH --error=logging/slurm_proofread_%j.err

# -----------------------------------------------------------------------------
# AI Proofreading Pass over a scanned book (src/cli/proofread.py)
#
# The model transcribes each scanned page, with the page's OCR lines as a draft, and the code joins the pages into
# book.ai.md; it never edits the reviewed book. The book folder (default vsc-project/) is data-for-ai/<book>/ from
# `python -m vsc_ocr prepare-ai <book>` in the vsc repo, copied as is.
#
# Usage:
#   sbatch scripts/proofread/submit.sh [--model <key>] [proofread.py flags]
#   sbatch scripts/proofread/submit.sh --pages 10-40                     # a trial slice
#   sbatch scripts/proofread/submit.sh --pages 10-40 --no-ocr-hint       # the same slice, image only
#   sbatch scripts/proofread/submit.sh --run-dir vsc-project/ai-pass/<time>   # finish a run's missing tasks
#   bash scripts/proofread/submit.sh --dry-run                           # on the login node: token counts, no GPU
#
# The model profile is served with vision on for this job only (profiles serve text only), and with at most
# PROOFREAD_CONCURRENCY requests in flight.
# -----------------------------------------------------------------------------

PROOFREAD_CONCURRENCY=30
MAX_IMAGES_PER_PROMPT=1    # a page task sends its page; a note task the page the note is printed on

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

# Load cluster modules and activate resume_env before sourcing config.sh, which reads src/core/config.py with python3
echo "[$(date +'%H:%M:%S')] STEP 1: Loading system environment modules and activating Conda environment 'resume_env'..."
module load miniconda3 2>/dev/null || true
module load cuda 2>/dev/null || module load cuda13.0 2>/dev/null || true

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

source "$LIB_DIR/config.sh"
source "$LIB_DIR/vllm_utils.sh"
source "$LIB_DIR/model_profiles.sh"

# Consume --model <key> / --model=<key>; forward all other arguments to proofread.py
MODEL_KEY_ARG=""
PROOFREAD_ARGS=()
DRY_RUN=0
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
      [ "$1" = "--dry-run" ] && DRY_RUN=1
      PROOFREAD_ARGS+=("$1")
      shift
      ;;
  esac
done

load_model_profile "${MODEL_KEY_ARG:-$DEFAULT_MODEL_KEY}" || exit 1
CONCURRENCY=$PROOFREAD_CONCURRENCY
export CONCURRENCY

# Vision on: drop the profile's text-only and image-limit flags, then allow this job's images
serve_vision_on "$MAX_IMAGES_PER_PROMPT"

if [ -z "$PROJECT_ROOT" ]; then
  echo "[CRITICAL ERROR] PROJECT_ROOT is not set after sourcing config.sh!" >&2
  exit 1
fi

cd "$PROJECT_ROOT" || exit 1
setup_vllm_env
mkdir -p "$PROJECT_ROOT/logs" "$PROJECT_ROOT/logging"

if [ $DRY_RUN -eq 1 ]; then
  echo "=== Dry run: counting prompt tokens with $MODEL's processor, no vLLM server ==="
  python3 -u "$PROJECT_ROOT/src/cli/proofread.py" --model-name "$MODEL" "${PROOFREAD_ARGS[@]}"
  exit $?
fi

echo "====================================================================="
nvidia-smi 2>/dev/null || echo "nvidia-smi not available"
echo "====================================================================="

PORT=$(find_free_port)
echo "[$(date +'%H:%M:%S')] Target Model: $MODEL (concurrency $CONCURRENCY, vision on)"
echo "[$(date +'%H:%M:%S')] Allocated Server Port: $PORT"

start_vllm_server "$MODEL" "$PORT" "$PROJECT_ROOT/logs/vllm_proofread.log" || exit 1

echo "=== vLLM Server Ready! Starting AI Proofreading Pass ==="
python3 -u "$PROJECT_ROOT/src/cli/proofread.py" \
  --model-name "$MODEL" \
  --vllm-url "http://127.0.0.1:$PORT/v1" \
  "${PROOFREAD_ARGS[@]}"
STATUS=$?

stop_vllm_server
python3 "$PROJECT_ROOT/scripts/checks/token_stats.py"
echo "=== [$(date +'%Y-%m-%d %H:%M:%S')] AI Proofreading Pass Finished ==="
exit $STATUS
