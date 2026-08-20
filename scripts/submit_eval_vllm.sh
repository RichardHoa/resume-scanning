#!/bin/bash
#SBATCH --job-name=eval_vllm
#SBATCH --partition=researcher
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --gres=gpu:1
#SBATCH --time=12:00:00
#SBATCH --output=logging/slurm_%j.out
#SBATCH --error=logging/slurm_%j.err

# -----------------------------------------------------------------------------
# SLURM Batch Job Script for High-Speed vLLM Resume Evaluation Server
# -----------------------------------------------------------------------------

RAW_MODEL="$1"
INITIAL_CWD="$(pwd)"

# -----------------------------------------------------------------------------
# Robust Location of config.sh
# Under SLURM, scripts are copied to /var/spool/slurmd/jobXXXXX/slurm_script,
# so BASH_SOURCE[0] points to the spool directory. We locate config.sh via
# SLURM_SUBMIT_DIR, BASH_SOURCE, or CWD.
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

if [ -z "$PROJECT_ROOT" ]; then
  echo "[CRITICAL ERROR] PROJECT_ROOT is not set after sourcing config.sh!" >&2
  exit 1
fi

# Force execution strictly from project repository root directory
cd "$PROJECT_ROOT" || exit 1

# Optimization & Threading Environment Variables (Prevent ONNX/PyTorch crashes & RAM OOM)
export MAX_JOBS=1
export NVCC_THREADS=1
export FLASHINFER_BUILD_MAX_JOBS=1
export OMP_NUM_THREADS=4
export MKL_NUM_THREADS=4
export OPENBLAS_NUM_THREADS=4
export VECLIB_MAXIMUM_THREADS=4
export NUMEXPR_NUM_THREADS=4

# Ensure output & log directories exist at project root
mkdir -p "$PROJECT_ROOT/logs" "$PROJECT_ROOT/evaluation_json" "$PROJECT_ROOT/logging" "$PROJECT_ROOT/output_jsons" "$PROJECT_ROOT/pdfs"

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

# Ensure critical evaluation dependencies (sentence-transformers, chromadb) are installed
if ! python3 -c "import sentence_transformers, chromadb" 2>/dev/null; then
  echo "[NOTICE] 'sentence-transformers' or 'chromadb' package missing in Conda environment 'resume_env'."
  echo "[NOTICE] Auto-installing missing evaluation dependencies via pip..."
  python3 -m pip install sentence-transformers chromadb 2>/dev/null || pip install sentence-transformers chromadb 2>/dev/null || true
fi

# Print GPU info on compute node immediately
echo "====================================================================="
echo "[$(date +'%Y-%m-%d %H:%M:%S')] STEP 3: Inspecting GPU hardware allocation..."
nvidia-smi 2>/dev/null || echo "nvidia-smi not available"
echo "====================================================================="

# Auto-detect HuggingFace cache location
if [ -d "/compute_home/$USER/.cache/huggingface" ]; then
  export HF_HOME="/compute_home/$USER/.cache/huggingface"
elif [ -d "$HOME/.cache/huggingface" ]; then
  export HF_HOME="$HOME/.cache/huggingface"
fi

# Pin Triton kernel cache to a persistent directory
export TRITON_CACHE_DIR="${HF_HOME:-$HOME/.cache}/triton_cache"
mkdir -p "$TRITON_CACHE_DIR"
echo "[$(date +'%H:%M:%S')] Triton Cache: $TRITON_CACHE_DIR"

# Pin FlashInfer autotune cache
export VLLM_FLASHINFER_AUTOTUNE_CACHE_DIR="${HF_HOME:-$HOME/.cache}/flashinfer_autotune_cache"
mkdir -p "$VLLM_FLASHINFER_AUTOTUNE_CACHE_DIR"
echo "[$(date +'%H:%M:%S')] FlashInfer Autotune Cache: $VLLM_FLASHINFER_AUTOTUNE_CACHE_DIR"

# Find an available open port instantly using OS socket binding
PORT=$(python3 -c "import socket; s=socket.socket(); s.bind(('127.0.0.1', 0)); print(s.getsockname()[1]); s.close()" 2>/dev/null || echo 8100)
MODEL="${RAW_MODEL:-Qwen/Qwen3.5-35B-A3B}"

echo "[$(date +'%H:%M:%S')] Project Root: $PROJECT_ROOT"
echo "[$(date +'%H:%M:%S')] Target Model: $MODEL"
echo "[$(date +'%H:%M:%S')] Allocated Server Port: $PORT"
echo "[$(date +'%H:%M:%S')] HF Cache Path: ${HF_HOME:-default}"

# Check if vllm python package is installed in environment
if python3 -c "import vllm" 2>/dev/null; then
  echo "=== vLLM package detected in environment! Starting vLLM Server ($MODEL) on Port $PORT ==="
  
  if command -v vllm &>/dev/null; then
    VLLM_CMD="vllm serve"
  elif python3 -c "import vllm.entrypoints.openai.api_server" 2>/dev/null; then
    VLLM_CMD="python3 -u -m vllm.entrypoints.openai.api_server"
  elif python3 -c "import vllm.entrypoints.cli.serve" 2>/dev/null; then
    VLLM_CMD="python3 -u -m vllm.entrypoints.cli.serve"
  else
    VLLM_CMD="vllm serve"
  fi

  $VLLM_CMD "$MODEL" \
    --dtype auto \
    --port "$PORT" \
    --host 127.0.0.1 \
    --max-model-len "${VLLM_MAX_MODEL_LEN:-20000}" \
    --max-num-seqs 256 \
    --gpu-memory-utilization 0.8 \
    --trust-remote-code \
    --enable-prefix-caching \
    --enable-chunked-prefill \
    --served-model-name "$MODEL" \
    > "$PROJECT_ROOT/logs/vllm_batch.log" 2>&1 &

  VLLM_PID=$!
  trap "kill -9 $VLLM_PID 2>/dev/null || true" EXIT INT TERM

  echo "vLLM server launched with PID $VLLM_PID on port $PORT. Waiting for server readiness..."

  READY=0
  for i in {1..720}; do
    if ! kill -0 $VLLM_PID 2>/dev/null; then
      echo "====================================================================="
      echo "[$(date +'%H:%M:%S')] CRITICAL: vLLM server process (PID $VLLM_PID) exited unexpectedly!"
      echo "--- Tail of $PROJECT_ROOT/logs/vllm_batch.log ---"
      tail -n 35 "$PROJECT_ROOT/logs/vllm_batch.log" 2>/dev/null || echo "(No log file found)"
      echo "====================================================================="
      break
    fi

    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:$PORT/v1/models" 2>/dev/null || echo "000")
    if [ "$HTTP_CODE" -eq 200 ]; then
      READY=1
      echo "[$(date +'%H:%M:%S')] SUCCESS: vLLM server is READY and responding on port $PORT!"
      break
    fi

    if [ $((i % 2)) -eq 0 ]; then
      ELAPSED=$((i * 5))
      echo "[$(date +'%H:%M:%S')] Loading vLLM server (Attempt $i/720, elapsed: ${ELAPSED}s)..."
      LAST_LOG=$(tail -n 2 "$PROJECT_ROOT/logs/vllm_batch.log" 2>/dev/null | tr '\n' ' ')
      if [ -n "$LAST_LOG" ]; then
        echo "   └─ vLLM activity: $LAST_LOG"
      fi
    fi

    sleep 5
  done

  if [ $READY -eq 1 ]; then
    echo "=== vLLM Server Ready! ==="

    JSON_COUNT=$(find "$PROJECT_ROOT/output_jsons/" -maxdepth 1 -name "*.json" 2>/dev/null | wc -l | tr -d ' ')
    if [ "$JSON_COUNT" -eq 0 ]; then
      echo "=== [Step 1 Auto-Run] 'output_jsons/' is empty. Extracting PDF resumes from 'pdfs/' first... ==="
      python3 -u "$PROJECT_ROOT/src/step_1_extractor.py" \
        --dir pdfs \
        --output output_jsons \
        --model-name "$MODEL" \
        --backend vllm \
        --vllm-url "http://127.0.0.1:$PORT/v1"
    fi

    echo "=== Starting Step 2 High-Precision vLLM Batch Evaluation ==="
    python3 -u "$PROJECT_ROOT/src/step_2_evaluate.py" \
      --model-name "$MODEL" \
      --backend vllm \
      --vllm-url "http://127.0.0.1:$PORT/v1" \
      --dir output_jsons \
      --job-req hr-requirement.txt \
      --output evaluation_json \
      --workers 6
  else
    echo "====================================================================================="
    echo "ERROR: vLLM server failed to start within 3600s timeout on port $PORT."
    echo "--- Full contents / tail of $PROJECT_ROOT/logs/vllm_batch.log ---"
    tail -n 50 "$PROJECT_ROOT/logs/vllm_batch.log" 2>/dev/null || echo "(No log file found)"
    echo "====================================================================================="
  fi

  echo "=== Cleaning up vLLM Server (PID: $VLLM_PID) ==="
  kill -9 $VLLM_PID 2>/dev/null || true
  trap - EXIT INT TERM
else
  echo "====================================================================================="
  echo "[ERROR] 'vllm' package is not installed in Conda environment 'resume_env'."
  echo "To use vLLM backend, run on terminal: pip install vllm"
  echo "Or fallback to submit_eval_transformer.sh"
  echo "====================================================================================="
  exit 1
fi
echo "=== [$(date +'%Y-%m-%d %H:%M:%S')] Batch Evaluation Job Finished ==="
