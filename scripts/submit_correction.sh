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
#   sbatch scripts/submit_correction.sh [--model <key>] [proofread.py flags]
#   sbatch scripts/submit_correction.sh --pages 10-40                     # a trial slice
#   sbatch scripts/submit_correction.sh --pages 10-40 --no-ocr-hint       # the same slice, image only
#   sbatch scripts/submit_correction.sh --run-dir vsc-project/ai-pass/<time>   # finish a run's missing tasks
#   bash scripts/submit_correction.sh --dry-run                           # on the login node: token counts, no GPU
#
# The model profile is served with vision on for this job only (profiles serve text only), and with at most
# PROOFREAD_CONCURRENCY requests in flight.
# -----------------------------------------------------------------------------

PROOFREAD_CONCURRENCY=30
MAX_IMAGES_PER_PROMPT=1    # a page task sends its page; a note task the page the note is printed on

INITIAL_CWD="$(pwd)"

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
SERVE_ARGS=()
skip_next=0
for arg in "${VLLM_EXTRA_ARGS[@]}"; do
  if [ $skip_next -eq 1 ]; then
    skip_next=0
    continue
  fi
  case "$arg" in
    --language-model-only) ;;
    --limit-mm-per-prompt*=*) ;;
    --limit-mm-per-prompt*) skip_next=1 ;;
    *) SERVE_ARGS+=("$arg") ;;
  esac
done
VLLM_EXTRA_ARGS=("${SERVE_ARGS[@]}" --limit-mm-per-prompt.image "$MAX_IMAGES_PER_PROMPT" --limit-mm-per-prompt.video 0)

if [ -z "$PROJECT_ROOT" ]; then
  echo "[CRITICAL ERROR] PROJECT_ROOT is not set after sourcing config.sh!" >&2
  exit 1
fi

cd "$PROJECT_ROOT" || exit 1
setup_vllm_env
mkdir -p "$PROJECT_ROOT/logs" "$PROJECT_ROOT/logging"

echo "[$(date +'%H:%M:%S')] STEP 1: Loading system environment modules..."
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

echo "[$(date +'%H:%M:%S')] STEP 2: Activating Conda environment 'resume_env'..."
eval "$(conda shell.bash hook 2>/dev/null)" || true
source activate resume_env 2>/dev/null || conda activate resume_env 2>/dev/null || true
echo "[$(date +'%H:%M:%S')] Step 2 complete. Active Python: $(which python3 2>/dev/null || echo 'python3 not found')"

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
python3 "$PROJECT_ROOT/scripts/token_stats.py"
echo "=== [$(date +'%Y-%m-%d %H:%M:%S')] AI Proofreading Pass Finished ==="
exit $STATUS
