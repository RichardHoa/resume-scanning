#!/bin/bash
#SBATCH --job-name=check_evaluator_consistency
#SBATCH --partition=researcher
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --gres=gpu:1
#SBATCH --time=12:00:00
#SBATCH --output=logging/slurm_evaluator_consistency_%j.out
#SBATCH --error=logging/slurm_evaluator_consistency_%j.err

# -----------------------------------------------------------------------------
# SLURM Batch Job Script for 20-Round Resume Evaluation Consistency Test
# -----------------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/config.sh"

# Optimization & Threading Environment Variables (Prevent ONNX/PyTorch crashes & RAM OOM)
export MAX_JOBS=1
export NVCC_THREADS=1
export FLASHINFER_BUILD_MAX_JOBS=1
export OMP_NUM_THREADS=4
export MKL_NUM_THREADS=4
export OPENBLAS_NUM_THREADS=4
export VECLIB_MAXIMUM_THREADS=4
export NUMEXPR_NUM_THREADS=4

# Disable detailed prompt logging to txt files (keep console logs normal)
export DISABLE_PROMPT_LOGGING=1

# Ensure output & log directories exist
mkdir -p logs evaluation_json logging output_jsons pdfs

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
MODEL="${1:-Qwen/Qwen3.5-35B-A3B}"

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
    --max-model-len "$VLLM_MAX_MODEL_LEN" \
    --max-num-seqs 256 \
    --gpu-memory-utilization 0.8 \
    --trust-remote-code \
    --enable-prefix-caching \
    --enable-chunked-prefill \
    --served-model-name "$MODEL" \
    > logs/vllm_evaluator_consistency.log 2>&1 &

  VLLM_PID=$!
  trap "kill -9 $VLLM_PID 2>/dev/null || true" EXIT INT TERM

  echo "vLLM server launched with PID $VLLM_PID on port $PORT. Waiting for server readiness..."

  READY=0
  for i in {1..720}; do
    if ! kill -0 $VLLM_PID 2>/dev/null; then
      echo "====================================================================="
      echo "[$(date +'%H:%M:%S')] CRITICAL: vLLM server process (PID $VLLM_PID) exited unexpectedly!"
      echo "--- Tail of logs/vllm_evaluator_consistency.log ---"
      tail -n 35 logs/vllm_evaluator_consistency.log 2>/dev/null || echo "(No log file found)"
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
      LAST_LOG=$(tail -n 2 logs/vllm_evaluator_consistency.log 2>/dev/null | tr '\n' ' ')
      if [ -n "$LAST_LOG" ]; then
        echo "   └─ vLLM activity: $LAST_LOG"
      fi
    fi

    sleep 5
  done

  if [ $READY -eq 1 ]; then
    echo "=== vLLM Server Ready! ==="

    JSON_COUNT=$(find output_jsons/ -maxdepth 1 -name "*.json" 2>/dev/null | wc -l | tr -d ' ')
    if [ "$JSON_COUNT" -eq 0 ]; then
      echo "=== [Step 1 Auto-Run] 'output_jsons/' is empty. Extracting PDF resumes from 'pdfs/' first... ==="
      python3 -u src/step_1_extractor.py \
        --dir pdfs \
        --output output_jsons \
        --model-name "$MODEL" \
        --backend vllm \
        --vllm-url "http://127.0.0.1:$PORT/v1"
    fi

    echo "=== Starting 20-Round Consistency Evaluation Matrix Generation ==="
    python3 -u "$SCRIPT_DIR/run_consistency.py" \
      --model-name "$MODEL" \
      --backend vllm \
      --vllm-url "http://127.0.0.1:$PORT/v1" \
      --dir output_jsons \
      --job-req hr-requirement.txt \
      --workers 6 \
      --rounds 20 \
      --num-evaluations 20 \
      --output consistency_results.csv
  else
    echo "====================================================================================="
    echo "ERROR: vLLM server failed to start within 3600s timeout on port $PORT."
    echo "--- Full contents / tail of logs/vllm_evaluator_consistency.log ---"
    tail -n 50 logs/vllm_evaluator_consistency.log 2>/dev/null || echo "(No log file found)"
    echo "====================================================================================="
  fi

  echo "=== Cleaning up vLLM Server (PID: $VLLM_PID) ==="
  kill -9 $VLLM_PID 2>/dev/null || true
  trap - EXIT INT TERM
else
  echo "====================================================================================="
  echo "[ERROR] 'vllm' package is not installed in Conda environment 'resume_env'."
  echo "To use vLLM backend, run on terminal: pip install vllm"
  echo "====================================================================================="
  exit 1
fi
echo "=== [$(date +'%Y-%m-%d %H:%M:%S')] Evaluator Consistency Job Finished ==="
