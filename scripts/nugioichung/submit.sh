#!/bin/bash
#SBATCH --job-name=nugioichung_vllm
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=32G
#SBATCH --partition=student9696
#SBATCH --gres=gpu:nvidia_rtx_pro_6000_blackwell_server_edition_4g.96gb:1
#SBATCH --time=4:00:00
#SBATCH --output=logging/slurm_nugioichung_%j.out
#SBATCH --error=logging/slurm_nugioichung_%j.err

# -----------------------------------------------------------------------------
# Nữ Giới Chung: transcribe one scanned Issue PDF (src/nugioichung/cli.py)
#
# A layout pass splits each page into Regions, a transcription pass reads each Region from the 300 dpi scan, and
# the code joins them into the Issue's Markdown (src/nugioichung/docs/adr/0001-two-pass-vlm-no-ocr-draft.md).
#
# Usage:
#   sbatch scripts/nugioichung/submit.sh <issue.pdf> [--model <key>] [cli.py flags]
#   sbatch scripts/nugioichung/submit.sh vsc-project/NuGioiChung/So1_Feb1_1918.pdf --pages 1,2,6,13   # a trial
#   sbatch scripts/nugioichung/submit.sh <issue.pdf> --run-dir vsc-project/NuGioiChung/runs/<issue>/<time>
#                                                                       # finish a run's missing requests
#   bash scripts/nugioichung/submit.sh <issue.pdf> --dry-run           # on the login node: token counts, no GPU
#
# The model profile is served with vision on for this job only (profiles serve text only), and with at most
# NUGIOICHUNG_CONCURRENCY requests in flight.
# -----------------------------------------------------------------------------

NUGIOICHUNG_CONCURRENCY=40    # the default profile's
MAX_IMAGES_PER_PROMPT=1    # a layout request sends its page; a transcription request its Region's crop
WATCH_SERVER_EVERY=30    # seconds between samples of the server's state in the metrics log

# Every WATCH_SERVER_EVERY seconds while the vLLM server runs, appends to <log>: GPU utilization and memory, the
# CPU use of the vLLM processes and the node's load, and vLLM's own counters (requests running/waiting,
# preemptions, tokens, KV cache, and the sum/count of its latency histograms: queue, prefill, decode, per output
# token). A low GPU utilization while decoding is slow points at CPU-side work, such as enforcing the JSON schema.
# Usage: watch_server <port> <log>
watch_server() {
  local port="$1" log="$2"
  while kill -0 "$VLLM_PID" 2>/dev/null; do
    {
      echo "=== $(date +'%Y-%m-%d %H:%M:%S')"
      echo "gpu: $(nvidia-smi --query-gpu=utilization.gpu,memory.used,memory.total --format=csv,noheader 2>/dev/null)"
      echo "load: $(cut -d' ' -f1-3 /proc/loadavg 2>/dev/null)"
      # top's second sample is the CPU use over the last second (ps would give the average since each process began);
      # the pattern also matches the Nữ Giới Chung CLI, through its --vllm-url
      top -b -n 2 -d 1 -c -p "$(pgrep -d, -f '(vllm|EngineCore)' 2>/dev/null | cut -d, -f1-20)" 2>/dev/null \
        | awk '/^ *PID/ {n++; next} n == 2 && $1 ~ /^[0-9]+$/ {printf "cpu: pid %s %s%% %s %s %s\n", $1, $9, $12, $13, $14}'
      curl -s "http://127.0.0.1:$port/metrics" 2>/dev/null | grep -E \
        '^vllm:(num_requests_[a-z]+|num_preemptions[a-z_]*|(prompt|generation)_tokens_total|[a-z_]*cache_usage_perc|[a-z_]*_seconds_(sum|count))[{ ]'
    } >> "$log"
    sleep "$WATCH_SERVER_EVERY"
  done
}

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

# Consume --model <key> / --model=<key>; forward all other arguments to the Nữ Giới Chung CLI
MODEL_KEY_ARG=""
NUGIOICHUNG_ARGS=()
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
      NUGIOICHUNG_ARGS+=("$1")
      shift
      ;;
  esac
done

load_model_profile "${MODEL_KEY_ARG:-$DEFAULT_MODEL_KEY}" || exit 1
CONCURRENCY=$NUGIOICHUNG_CONCURRENCY
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
  python3 -u -m src.nugioichung.cli --model-name "$MODEL" "${NUGIOICHUNG_ARGS[@]}"
  exit $?
fi

echo "====================================================================="
nvidia-smi 2>/dev/null || echo "nvidia-smi not available"
echo "====================================================================="

PORT=$(find_free_port)
echo "[$(date +'%H:%M:%S')] Target Model: $MODEL (concurrency $CONCURRENCY, vision on)"
echo "[$(date +'%H:%M:%S')] Allocated Server Port: $PORT"

start_vllm_server "$MODEL" "$PORT" "$PROJECT_ROOT/logs/vllm_nugioichung.log" || exit 1
METRICS_LOG="$PROJECT_ROOT/logs/vllm_nugioichung_metrics_${SLURM_JOB_ID:-$(date +%Y%m%d-%H%M%S)}.log"
watch_server "$PORT" "$METRICS_LOG" &
WATCH_PID=$!
echo "[$(date +'%H:%M:%S')] Sampling the server every ${WATCH_SERVER_EVERY}s into $METRICS_LOG"

echo "=== vLLM Server Ready! Starting Nữ Giới Chung transcription ==="
python3 -u -m src.nugioichung.cli \
  --model-name "$MODEL" \
  --vllm-url "http://127.0.0.1:$PORT/v1" \
  "${NUGIOICHUNG_ARGS[@]}"
STATUS=$?

# The server's full metrics as the run ends, for the histograms' buckets
{ echo "=== final $(date +'%Y-%m-%d %H:%M:%S')"; curl -s "http://127.0.0.1:$PORT/metrics"; } >> "$METRICS_LOG"
kill "$WATCH_PID" 2>/dev/null
stop_vllm_server
echo "[$(date +'%H:%M:%S')] Server samples in $METRICS_LOG; server log in $PROJECT_ROOT/logs/vllm_nugioichung.log"
# cli.py prints the token stats of its own run folder
echo "=== [$(date +'%Y-%m-%d %H:%M:%S')] Nữ Giới Chung transcription Finished ==="
exit $STATUS
