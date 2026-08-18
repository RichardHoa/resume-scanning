#!/bin/bash
# -----------------------------------------------------------------------------
# Modular Web Server & vLLM Engine Manager
# Model: Qwen/Qwen3.5-35B-A3B
#
# Usage:
#   ./scripts/server.sh                 -> Starts both vLLM + FastAPI web server
#   ./scripts/server.sh --start         -> Starts both vLLM + FastAPI web server
#   ./scripts/server.sh --stop          -> Stops both vLLM + FastAPI web server
#
#   ./scripts/server.sh --start-vllm    -> Starts vLLM inference server ONLY
#   ./scripts/server.sh --stop-vllm     -> Stops vLLM inference server ONLY
#
#   ./scripts/server.sh --start-web     -> Starts FastAPI web server ONLY
#   ./scripts/server.sh --stop-web      -> Stops FastAPI web server ONLY
#
#   ./scripts/server.sh --status        -> Checks status of all running services
#   ./scripts/server.sh --help          -> Shows detailed usage information
# -----------------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/config.sh"

MODEL="Qwen/Qwen3.5-35B-A3B"
DEFAULT_VLLM_PORT=8100
WEB_PORT=8005

VLLM_PID_FILE="logs/vllm.pid"
VLLM_PORT_FILE="logs/vllm.port"
VLLM_LOG_FILE="logs/vllm_server.log"

WEB_PID_FILE="logs/web.pid"
WEB_LOG_FILE="logs/web_server.log"

DAEMON_PID_FILE="server.pid"
DAEMON_LOG_FILE="server.txt"

# --- HELPER: Setup Environment ---
setup_environment() {
  export MAX_JOBS=1
  export NVCC_THREADS=1
  export FLASHINFER_BUILD_MAX_JOBS=1
  export OMP_NUM_THREADS=4
  export MKL_NUM_THREADS=4
  export OPENBLAS_NUM_THREADS=4
  export VECLIB_MAXIMUM_THREADS=4
  export NUMEXPR_NUM_THREADS=4

  mkdir -p logs temp_uploads static

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
  source activate resume_env 2>/dev/null || true

  if [ -d "/compute_home/$USER/.cache/huggingface" ]; then
    export HF_HOME="/compute_home/$USER/.cache/huggingface"
  elif [ -d "$HOME/.cache/huggingface" ]; then
    export HF_HOME="$HOME/.cache/huggingface"
  fi

  export TRITON_CACHE_DIR="${HF_HOME:-$HOME/.cache}/triton_cache"
  mkdir -p "$TRITON_CACHE_DIR"

  export VLLM_FLASHINFER_AUTOTUNE_CACHE_DIR="${HF_HOME:-$HOME/.cache}/flashinfer_autotune_cache"
  mkdir -p "$VLLM_FLASHINFER_AUTOTUNE_CACHE_DIR"
}

# --- HELPER: Get vLLM Port ---
get_vllm_port() {
  if [ -n "$VLLM_PORT" ]; then
    echo "$VLLM_PORT"
  elif [ -f "$VLLM_PORT_FILE" ]; then
    cat "$VLLM_PORT_FILE" 2>/dev/null
  else
    echo "$DEFAULT_VLLM_PORT"
  fi
}

# --- HELPER: Check process by PID ---
is_pid_running() {
  local pid="$1"
  if [ -n "$pid" ] && kill -0 "$pid" 2>/dev/null; then
    return 0
  else
    return 1
  fi
}

# --- HELPER: Find vLLM PIDs ---
find_vllm_pids() {
  local pids=""
  if [ -f "$VLLM_PID_FILE" ]; then
    pids=$(cat "$VLLM_PID_FILE" 2>/dev/null)
  fi
  local pgrep_pids=$(pgrep -f "vllm.*$MODEL" 2>/dev/null)
  echo "$pids $pgrep_pids" | tr ' ' '\n' | sort -u | tr '\n' ' ' | xargs
}

# --- HELPER: Find Web Server PIDs ---
find_web_pids() {
  local pids=""
  if [ -f "$WEB_PID_FILE" ]; then
    pids=$(cat "$WEB_PID_FILE" 2>/dev/null)
  fi
  local pgrep_pids=$(pgrep -f "src/server.py" 2>/dev/null)
  echo "$pids $pgrep_pids" | tr ' ' '\n' | sort -u | tr '\n' ' ' | xargs
}

# --- ACTION: Stop vLLM Server Only ---
stop_vllm() {
  echo "[server.sh] Stopping vLLM Inference Server..."
  local pids=$(find_vllm_pids)
  local stopped=0

  if [ -n "$pids" ]; then
    for pid in $pids; do
      if is_pid_running "$pid"; then
        echo "  ├─ Terminating vLLM process PID $pid..."
        kill "$pid" 2>/dev/null || true
        stopped=1
      fi
    done
    sleep 2
    for pid in $pids; do
      if is_pid_running "$pid"; then
        echo "  ├─ Force killing vLLM process PID $pid..."
        kill -9 "$pid" 2>/dev/null || true
      fi
    done
  fi

  rm -f "$VLLM_PID_FILE" "$VLLM_PORT_FILE"
  if [ $stopped -eq 1 ]; then
    echo "[server.sh] SUCCESS: vLLM Inference Server stopped."
  else
    echo "[server.sh] vLLM server is not currently running."
  fi
}

# --- ACTION: Stop Web Server Only ---
stop_web() {
  echo "[server.sh] Stopping FastAPI Web Server..."
  local pids=$(find_web_pids)
  local stopped=0

  if [ -n "$pids" ]; then
    for pid in $pids; do
      if is_pid_running "$pid"; then
        echo "  ├─ Terminating Web Server process PID $pid..."
        kill "$pid" 2>/dev/null || true
        stopped=1
      fi
    done
    sleep 2
    for pid in $pids; do
      if is_pid_running "$pid"; then
        echo "  ├─ Force killing Web Server process PID $pid..."
        kill -9 "$pid" 2>/dev/null || true
      fi
    done
  fi

  rm -f "$WEB_PID_FILE"
  if [ $stopped -eq 1 ]; then
    echo "[server.sh] SUCCESS: FastAPI Web Server stopped."
  else
    echo "[server.sh] Web Server is not currently running."
  fi
}

# --- ACTION: Stop All ---
stop_all() {
  echo "====================================================================="
  echo "[server.sh] Stopping all background processes (Web Server + vLLM)..."
  echo "====================================================================="
  stop_web
  stop_vllm

  # Clean up legacy daemon PID if present
  if [ -f "$DAEMON_PID_FILE" ]; then
    for pid in $(cat "$DAEMON_PID_FILE" 2>/dev/null); do
      if is_pid_running "$pid"; then
        kill -9 "$pid" 2>/dev/null || true
      fi
    done
    rm -f "$DAEMON_PID_FILE"
  fi
  echo "[server.sh] All server processes stopped."
}

# --- ACTION: Start vLLM Server Only ---
start_vllm() {
  local running_pids=$(find_vllm_pids)
  if [ -n "$running_pids" ]; then
    echo "[server.sh] ERROR: vLLM server is already running (PID(s): $running_pids)."
    echo "[server.sh] Run './scripts/server.sh --stop-vllm' to stop it first."
    return 1
  fi

  setup_environment

  local PORT=$(get_vllm_port)
  echo "$PORT" > "$VLLM_PORT_FILE"

  echo "====================================================================="
  echo "[$(date +'%Y-%m-%d %H:%M:%S')] Starting vLLM Inference Server..."
  echo "  ├─ Model: $MODEL"
  echo "  ├─ Port:  $PORT"
  echo "  └─ Log:   $VLLM_LOG_FILE"
  echo "====================================================================="

  if ! python3 -c "import vllm" 2>/dev/null; then
    echo "[ERROR] 'vllm' package is not installed in Conda environment."
    echo "Please run: pip install vllm"
    return 1
  fi

  local VLLM_CMD
  if command -v vllm &>/dev/null; then
    VLLM_CMD="vllm serve"
  elif python3 -c "import vllm.entrypoints.openai.api_server" 2>/dev/null; then
    VLLM_CMD="python3 -u -m vllm.entrypoints.openai.api_server"
  elif python3 -c "import vllm.entrypoints.cli.serve" 2>/dev/null; then
    VLLM_CMD="python3 -u -m vllm.entrypoints.cli.serve"
  else
    VLLM_CMD="vllm serve"
  fi

  nohup $VLLM_CMD "$MODEL" \
    --dtype auto \
    --port "$PORT" \
    --host 127.0.0.1 \
    --max-model-len "$VLLM_MAX_MODEL_LEN" \
    --max-num-seqs 256 \
    --gpu-memory-utilization 0.8 \
    --trust-remote-code \
    --enable-prefix-caching \
    --enable-chunked-prefill \
    --served-model-name "$MODEL" \
    > "$VLLM_LOG_FILE" 2>&1 &

  local VLLM_PID=$!
  echo "$VLLM_PID" > "$VLLM_PID_FILE"

  echo "[server.sh] vLLM process launched (PID: $VLLM_PID). Waiting for engine readiness..."

  local READY=0
  for i in {1..720}; do
    if ! is_pid_running $VLLM_PID; then
      echo "====================================================================="
      echo "[ERROR] vLLM server process (PID $VLLM_PID) exited unexpectedly!"
      echo "--- Tail of $VLLM_LOG_FILE ---"
      tail -n 35 "$VLLM_LOG_FILE" 2>/dev/null || echo "(No log file found)"
      echo "====================================================================="
      rm -f "$VLLM_PID_FILE" "$VLLM_PORT_FILE"
      return 1
    fi

    local HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:$PORT/v1/models" 2>/dev/null || echo "000")
    if [ "$HTTP_CODE" -eq 200 ]; then
      READY=1
      echo "[$(date +'%H:%M:%S')] SUCCESS: vLLM server is READY on port $PORT!"
      break
    fi

    if [ $((i % 2)) -eq 0 ]; then
      local ELAPSED=$((i * 5))
      echo "[$(date +'%H:%M:%S')] Loading vLLM model (Attempt $i/720, elapsed: ${ELAPSED}s)..."
      local LAST_LOG=$(tail -n 2 "$VLLM_LOG_FILE" 2>/dev/null | tr '\n' ' ')
      if [ -n "$LAST_LOG" ]; then
        echo "   └─ vLLM activity: $LAST_LOG"
      fi
    fi

    sleep 5
  done

  if [ $READY -ne 1 ]; then
    echo "ERROR: vLLM server failed to respond within timeout on port $PORT."
    rm -f "$VLLM_PID_FILE" "$VLLM_PORT_FILE"
    return 1
  fi

  return 0
}

# --- ACTION: Start Web Server Only ---
start_web() {
  local running_pids=$(find_web_pids)
  if [ -n "$running_pids" ]; then
    echo "[server.sh] ERROR: Web Server is already running (PID(s): $running_pids)."
    echo "[server.sh] Run './scripts/server.sh --stop-web' to stop it first."
    return 1
  fi

  setup_environment

  local PORT=$(get_vllm_port)
  local VLLM_HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:$PORT/v1/models" 2>/dev/null || echo "000")
  if [ "$VLLM_HTTP_CODE" -ne 200 ]; then
    echo "[WARNING] vLLM server does not appear to be ready on port $PORT (HTTP status: $VLLM_HTTP_CODE)."
    echo "[WARNING] Starting Web Server anyway, but inference requests will fail until vLLM is online."
  fi

  echo "====================================================================="
  echo "[$(date +'%Y-%m-%d %H:%M:%S')] Starting Resume Extraction Web Server (FastAPI)..."
  echo "  ├─ Connecting to vLLM: http://127.0.0.1:$PORT/v1"
  echo "  ├─ Web Port:  $WEB_PORT"
  echo "  └─ Log:       $WEB_LOG_FILE"
  echo "====================================================================="

  nohup python3 -u src/server.py \
    --model "$MODEL" \
    --backend vllm \
    --vllm-url "http://127.0.0.1:$PORT/v1" \
    --host 0.0.0.0 \
    --port "$WEB_PORT" \
    > "$WEB_LOG_FILE" 2>&1 &

  local SERVER_PID=$!
  echo "$SERVER_PID" > "$WEB_PID_FILE"

  echo "[server.sh] SUCCESS: Web Server started in background!"
  echo "  ├─ Web Server PID: $SERVER_PID"
  echo "  ├─ URL:            http://localhost:$WEB_PORT"
  echo "  └─ Monitor logs:   tail -f $WEB_LOG_FILE"
  return 0
}

# --- ACTION: Show Status ---
show_status() {
  local PORT=$(get_vllm_port)
  echo "====================================================================="
  echo "               RESUME EXTRACTOR SERVICE STATUS                       "
  echo "====================================================================="

  # 1. vLLM Status
  local vllm_pids=$(find_vllm_pids)
  if [ -n "$vllm_pids" ]; then
    local HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:$PORT/v1/models" 2>/dev/null || echo "000")
    if [ "$HTTP_CODE" -eq 200 ]; then
      echo "  [vLLM Inference Server] : RUNNING & READY (PID: $vllm_pids, Port: $PORT)"
    else
      echo "  [vLLM Inference Server] : STARTING / UNHEALTHY (PID: $vllm_pids, Port: $PORT, HTTP: $HTTP_CODE)"
    fi
  else
    echo "  [vLLM Inference Server] : STOPPED"
  fi

  # 2. Web Server Status
  local web_pids=$(find_web_pids)
  if [ -n "$web_pids" ]; then
    local WEB_CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:$WEB_PORT/" 2>/dev/null || echo "000")
    if [ "$WEB_CODE" -eq 200 ] || [ "$WEB_CODE" -eq 404 ]; then
      echo "  [FastAPI Web Server]    : RUNNING (PID: $web_pids, Port: $WEB_PORT)"
    else
      echo "  [FastAPI Web Server]    : RUNNING (PID: $web_pids, Port: $WEB_PORT, HTTP: $WEB_CODE)"
    fi
  else
    echo "  [FastAPI Web Server]    : STOPPED"
  fi

  echo "====================================================================="
}

# --- ACTION: Show Help ---
show_help() {
  echo "Usage: ./scripts/server.sh [OPTION]"
  echo ""
  echo "Options:"
  echo "  --start, start                 Start both vLLM and FastAPI Web Server (default)"
  echo "  --stop, stop                   Stop both vLLM and FastAPI Web Server"
  echo "  --start-vllm, start-vllm       Start ONLY the vLLM Inference Server"
  echo "  --stop-vllm, stop-vllm         Stop ONLY the vLLM Inference Server"
  echo "  --start-web, start-web         Start ONLY the FastAPI Web Server"
  echo "  --stop-web, stop-web           Stop ONLY the FastAPI Web Server"
  echo "  --status, status               Show current running status of all services"
  echo "  --help, -h                     Show this help message"
  echo ""
}

# --- MAIN DISPATCHER ---
case "$1" in
  __internal_daemon)
    setup_environment
    start_vllm || exit 1
    start_web || exit 1
    # Wait on web server PID
    local_web_pid=$(cat "$WEB_PID_FILE" 2>/dev/null)
    if [ -n "$local_web_pid" ]; then
      wait "$local_web_pid" 2>/dev/null
    fi
    ;;
  --start-vllm|start-vllm)
    start_vllm
    ;;
  --stop-vllm|stop-vllm)
    stop_vllm
    ;;
  --start-web|start-web|--start-server|start-server)
    start_web
    ;;
  --stop-web|stop-web|--stop-server|stop-server)
    stop_web
    ;;
  --stop|stop)
    stop_all
    ;;
  --status|status)
    show_status
    ;;
  --help|-h|help)
    show_help
    ;;
  ""|--start|start)
    # Default combined non-blocking launch
    local_vllm=$(find_vllm_pids)
    local_web=$(find_web_pids)
    if [ -n "$local_vllm" ] || [ -n "$local_web" ]; then
      echo "[server.sh] ERROR: Server processes are already running."
      show_status
      echo "[server.sh] Run './scripts/server.sh --stop' to stop them first."
      exit 1
    fi

    echo "====================================================================="
    echo "[server.sh] Launching Web Server with vLLM ($MODEL) in background..."
    echo "====================================================================="
    nohup bash "$SCRIPT_DIR/server.sh" __internal_daemon > "$DAEMON_LOG_FILE" 2>&1 &
    DAEMON_PID=$!
    echo "$DAEMON_PID" > "$DAEMON_PID_FILE"

    echo "[server.sh] Full server stack starting in background!"
    echo "  ├─ Daemon PID:   $DAEMON_PID"
    echo "  ├─ Log:          $DAEMON_LOG_FILE"
    echo "  ├─ Monitor:      tail -f $DAEMON_LOG_FILE"
    echo "  ├─ Status check: ./scripts/server.sh --status"
    echo "  └─ Stop all:     ./scripts/server.sh --stop"
    echo "====================================================================="
    ;;
  *)
    echo "Unknown option: $1"
    show_help
    exit 1
    ;;
esac
