#!/bin/bash
# -----------------------------------------------------------------------------
# A transcription job on the vLLM vision model, shared by the scanned-book submit scripts (scripts/nugioichung,
# scripts/khotangtucngu). Each submit script keeps its own #SBATCH header and usage, finds scripts/lib, then:
#
#   source "$LIB_DIR/vision_job.sh"
#   run_vision_job <name> <title> <python module> <concurrency> <max images per prompt> "$@"
#
# `--model <key>` picks the model profile (default the default profile); every other argument goes to the module.
# With --dry-run no server is started: the module counts its requests' prompt tokens with the model's processor.
# Otherwise the profile is served with vision on for this job only (profiles serve text only), with at most
# <concurrency> requests in flight, and the module runs against it. The server log is logs/vllm_<name>.log, and its
# state is sampled into logs/vllm_<name>_metrics_<job>.log.
# -----------------------------------------------------------------------------

WATCH_SERVER_EVERY=30    # seconds between samples of the server's state in the metrics log
VLLM_ENFORCE_EAGER=0    # CUDA graphs on: decode is bound by the engine's CPU thread in eager mode (vllm_utils.sh)

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
      # the pattern also matches the job's CLI, through its --vllm-url
      top -b -n 2 -d 1 -c -p "$(pgrep -d, -f '(vllm|EngineCore)' 2>/dev/null | cut -d, -f1-20)" 2>/dev/null \
        | awk '/^ *PID/ {n++; next} n == 2 && $1 ~ /^[0-9]+$/ {printf "cpu: pid %s %s%% %s %s %s\n", $1, $9, $12, $13, $14}'
      curl -s "http://127.0.0.1:$port/metrics" 2>/dev/null | grep -E \
        '^vllm:(num_requests_[a-z]+|num_preemptions[a-z_]*|(prompt|generation)_tokens_total|[a-z_]*cache_usage_perc|[a-z_]*_seconds_(sum|count))[{ ]'
    } >> "$log"
    sleep "$WATCH_SERVER_EVERY"
  done
}

# Usage: run_vision_job <name> <title> <python module> <concurrency> <max images per prompt> [args...]
# Returns the module's exit status.
run_vision_job() {
  local name="$1" title="$2" module="$3" job_concurrency="$4" max_images="$5"
  shift 5

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

  # Consume --model <key> / --model=<key>; forward all other arguments to the module
  local model_key_arg="" dry_run=0
  local job_args=()
  while [ $# -gt 0 ]; do
    case "$1" in
      --model)
        if [ -z "$2" ]; then
          echo "[ERROR] --model requires a key. Valid keys: $MODEL_PROFILE_KEYS" >&2
          return 1
        fi
        model_key_arg="$2"
        shift 2
        ;;
      --model=*)
        model_key_arg="${1#--model=}"
        shift
        ;;
      *)
        [ "$1" = "--dry-run" ] && dry_run=1
        job_args+=("$1")
        shift
        ;;
    esac
  done

  load_model_profile "${model_key_arg:-$DEFAULT_MODEL_KEY}" || return 1
  CONCURRENCY=$job_concurrency
  export CONCURRENCY

  # Vision on: drop the profile's text-only and image-limit flags, then allow this job's images
  serve_vision_on "$max_images"

  if [ -z "$PROJECT_ROOT" ]; then
    echo "[CRITICAL ERROR] PROJECT_ROOT is not set after sourcing config.sh!" >&2
    return 1
  fi

  cd "$PROJECT_ROOT" || return 1
  setup_vllm_env
  mkdir -p "$PROJECT_ROOT/logs" "$PROJECT_ROOT/logging"

  if [ $dry_run -eq 1 ]; then
    echo "=== Dry run: counting prompt tokens with $MODEL's processor, no vLLM server ==="
    python3 -u -m "$module" --model-name "$MODEL" "${job_args[@]}"
    return $?
  fi

  echo "====================================================================="
  nvidia-smi 2>/dev/null || echo "nvidia-smi not available"
  echo "====================================================================="

  local port
  port=$(find_free_port)
  echo "[$(date +'%H:%M:%S')] Target Model: $MODEL (concurrency $CONCURRENCY, vision on)"
  echo "[$(date +'%H:%M:%S')] Allocated Server Port: $port"

  start_vllm_server "$MODEL" "$port" "$PROJECT_ROOT/logs/vllm_$name.log" || return 1
  local metrics_log="$PROJECT_ROOT/logs/vllm_${name}_metrics_${SLURM_JOB_ID:-$(date +%Y%m%d-%H%M%S)}.log"
  watch_server "$port" "$metrics_log" &
  local watch_pid=$!
  echo "[$(date +'%H:%M:%S')] Sampling the server every ${WATCH_SERVER_EVERY}s into $metrics_log"

  echo "=== vLLM Server Ready! Starting $title transcription ==="
  python3 -u -m "$module" \
    --model-name "$MODEL" \
    --vllm-url "http://127.0.0.1:$port/v1" \
    "${job_args[@]}"
  local status=$?

  # The server's full metrics as the run ends, for the histograms' buckets
  { echo "=== final $(date +'%Y-%m-%d %H:%M:%S')"; curl -s "http://127.0.0.1:$port/metrics"; } >> "$metrics_log"
  kill "$watch_pid" 2>/dev/null
  stop_vllm_server
  echo "[$(date +'%H:%M:%S')] Server samples in $metrics_log; server log in $PROJECT_ROOT/logs/vllm_$name.log"
  # The module prints the token stats of its own run
  echo "=== [$(date +'%Y-%m-%d %H:%M:%S')] $title transcription Finished ==="
  return $status
}
