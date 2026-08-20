#!/bin/bash
# -----------------------------------------------------------------------------
# Centralized vLLM Utilities & Lifecycle Management Helper
#
# Sourced by SLURM and batch execution scripts to provide environment setup,
# dynamic port allocation, server startup, health checking, and process cleanup.
# -----------------------------------------------------------------------------

# Ensure PROJECT_ROOT is set if not already available
if [ -z "$PROJECT_ROOT" ]; then
  PROJECT_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." 2>/dev/null && pwd)"
fi
export PROJECT_ROOT

# -----------------------------------------------------------------------------
# Setup Environment Variables (Threading, ONNX, Caches)
# -----------------------------------------------------------------------------
setup_vllm_env() {
  export PYTHONUNBUFFERED=1
  export MAX_JOBS=1
  export NVCC_THREADS=1
  export FLASHINFER_BUILD_MAX_JOBS=1
  export OMP_NUM_THREADS=4
  export MKL_NUM_THREADS=4
  export OPENBLAS_NUM_THREADS=4
  export VECLIB_MAXIMUM_THREADS=4
  export NUMEXPR_NUM_THREADS=4
  export DISABLE_PROMPT_LOGGING=1

  # Auto-detect HuggingFace cache location
  if [ -d "/compute_home/$USER/.cache/huggingface" ]; then
    export HF_HOME="/compute_home/$USER/.cache/huggingface"
  elif [ -d "$HOME/.cache/huggingface" ]; then
    export HF_HOME="$HOME/.cache/huggingface"
  fi

  # Pin Triton kernel cache to a persistent directory
  export TRITON_CACHE_DIR="${HF_HOME:-$HOME/.cache}/triton_cache"
  mkdir -p "$TRITON_CACHE_DIR"

  # Pin FlashInfer autotune cache
  export VLLM_FLASHINFER_AUTOTUNE_CACHE_DIR="${HF_HOME:-$HOME/.cache}/flashinfer_autotune_cache"
  mkdir -p "$VLLM_FLASHINFER_AUTOTUNE_CACHE_DIR"
}

# -----------------------------------------------------------------------------
# Find Available Port via OS Socket Binding
# -----------------------------------------------------------------------------
find_free_port() {
  local fallback_port="${1:-8100}"
  python3 -c "import socket; s=socket.socket(); s.bind(('127.0.0.1', 0)); print(s.getsockname()[1]); s.close()" 2>/dev/null || echo "$fallback_port"
}

# -----------------------------------------------------------------------------
# Global PID for vLLM process
# -----------------------------------------------------------------------------
VLLM_PID=""

# -----------------------------------------------------------------------------
# Stop vLLM Server Instance
# -----------------------------------------------------------------------------
stop_vllm_server() {
  if [ -n "$VLLM_PID" ] && kill -0 "$VLLM_PID" 2>/dev/null; then
    echo "[vLLM Helper] Cleaning up vLLM Server (PID: $VLLM_PID)..."
    kill "$VLLM_PID" 2>/dev/null || true
    sleep 1
    if kill -0 "$VLLM_PID" 2>/dev/null; then
      kill -9 "$VLLM_PID" 2>/dev/null || true
    fi
  fi
  VLLM_PID=""
  trap - EXIT INT TERM
}

# -----------------------------------------------------------------------------
# Start vLLM Server Instance and Wait for Readiness
# Usage: start_vllm_server <MODEL_NAME> <PORT> [LOG_FILE]
# -----------------------------------------------------------------------------
start_vllm_server() {
  local model="${1:-Qwen/Qwen3.5-35B-A3B}"
  local port="${2:-8100}"
  local log_file="${3:-$PROJECT_ROOT/logs/vllm_server.log}"

  # Check if vllm python package is installed in environment
  if ! python3 -c "import vllm" 2>/dev/null; then
    echo "====================================================================================="
    echo "[ERROR] 'vllm' package is not installed in the active Conda environment."
    echo "To use vLLM backend, run on terminal: pip install vllm"
    echo "====================================================================================="
    return 1
  fi

  echo "=== vLLM package detected! Starting vLLM Server ($model) on Port $port ==="

  local vllm_cmd="vllm serve"
  if command -v vllm &>/dev/null; then
    vllm_cmd="vllm serve"
  elif python3 -c "import vllm.entrypoints.openai.api_server" 2>/dev/null; then
    vllm_cmd="python3 -u -m vllm.entrypoints.openai.api_server"
  elif python3 -c "import vllm.entrypoints.cli.serve" 2>/dev/null; then
    vllm_cmd="python3 -u -m vllm.entrypoints.cli.serve"
  fi

  mkdir -p "$(dirname "$log_file")"

  $vllm_cmd "$model" \
    --dtype auto \
    --port "$port" \
    --host 127.0.0.1 \
    --max-model-len "${VLLM_MAX_MODEL_LEN:-20000}" \
    --max-num-seqs 256 \
    --gpu-memory-utilization 0.8 \
    --trust-remote-code \
    --served-model-name "$model" \
    > "$log_file" 2>&1 &

  VLLM_PID=$!
  disown $VLLM_PID 2>/dev/null || true
  trap "stop_vllm_server" EXIT INT TERM

  echo "vLLM server launched with PID $VLLM_PID on port $port. Waiting for server readiness..."

  local ready=0
  for i in {1..720}; do
    if ! kill -0 "$VLLM_PID" 2>/dev/null; then
      echo "====================================================================="
      echo "[$(date +'%H:%M:%S')] CRITICAL: vLLM server process (PID $VLLM_PID) exited unexpectedly!"
      echo "--- Tail of $log_file ---"
      tail -n 35 "$log_file" 2>/dev/null || echo "(No log file found)"
      echo "====================================================================="
      break
    fi

    local http_code
    http_code=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:$port/v1/models" 2>/dev/null || echo "000")
    if [ "$http_code" -eq 200 ]; then
      ready=1
      echo "[$(date +'%H:%M:%S')] SUCCESS: vLLM server is READY and responding on port $port!"
      break
    fi

    if [ $((i % 2)) -eq 0 ]; then
      local elapsed=$((i * 5))
      echo "[$(date +'%H:%M:%S')] Loading vLLM server (Attempt $i/720, elapsed: ${elapsed}s)..."
      local last_log
      last_log=$(tail -n 2 "$log_file" 2>/dev/null | tr '\n' ' ')
      if [ -n "$last_log" ]; then
        echo "   └─ vLLM activity: $last_log"
      fi
    fi

    sleep 5
  done

  if [ "$ready" -ne 1 ]; then
    echo "====================================================================================="
    echo "ERROR: vLLM server failed to start within 3600s timeout on port $port."
    echo "--- Full contents / tail of $log_file ---"
    tail -n 50 "$log_file" 2>/dev/null || echo "(No log file found)"
    echo "====================================================================================="
    stop_vllm_server
    return 1
  fi

  return 0
}
