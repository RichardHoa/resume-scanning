#!/bin/bash
# ---------------------------------------------------------------------------
# Start a vLLM OpenAI-compatible inference server
# ---------------------------------------------------------------------------
#
# WHEN TO USE THIS:
#   Use this script when you need to serve concurrent requests through the
#   web server (server.py).  vLLM's continuous batching efficiently handles
#   multiple simultaneous requests.
#
#   For sequential CLI batch processing (one resume at a time), you do NOT
#   need vLLM.  Just use the default HuggingFace backend instead:
#     python src/step_1_extractor.py --dir pdfs/ --output output_jsons/
#
# Usage:
#   bash scripts/start_vllm.sh                     # default model
#   bash scripts/start_vllm.sh Qwen/Qwen2.5-7B-Instruct   # custom model
#
# Stop the server:
#   kill $(cat logs/vllm.pid)
# ---------------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/config.sh"

MODEL="${1:-numind/NuExtract3}"
PORT=8100
export VLLM_USE_DEEP_GEMM=0
export ORT_DISABLE_THREAD_AFFINITY=1
export ONNXRUNTIME_DISABLE_THREAD_AFFINITY=1
export ORT_DISABLE_CPU_AFFINITY=1
export ORT_SESSION_THREAD_POOL_SIZE=4
export ORT_LOGGING_LEVEL=4
export ONNXRUNTIME_LOG_LEVEL=4
export ORT_INTRA_OP_NUM_THREADS=4
export ORT_INTER_OP_NUM_THREADS=4
export OMP_NUM_THREADS=4
export OPENBLAS_NUM_THREADS=4

mkdir -p logs

echo "Starting vLLM server for $MODEL on port $PORT..."
echo "Logs: logs/vllm.log"

# --gpu-memory-utilization controls how much VRAM vLLM pre-allocates for its
# KV-cache at startup.  0.90 = 90% of total VRAM.  Lower this if you need
# to leave VRAM free for other processes (e.g. 0.50 for light workloads).
nohup vllm serve "$MODEL" \
    --dtype auto \
    --port "$PORT" \
    --host 0.0.0.0 \
    --max-model-len "$VLLM_MAX_MODEL_LEN" \
    --gpu-memory-utilization 0.90 \
    --kv-cache-dtype auto \
    > logs/vllm.log 2>&1 &

echo $! > logs/vllm.pid
echo "PID: $(cat logs/vllm.pid)"
echo ""
echo "Wait for it to load (watch with: tail -f logs/vllm.log)"
echo "Once you see 'Started server process', run the web server:"
echo ""
echo "  python src/server.py --backend vllm --vllm-url http://localhost:$PORT/v1"
echo ""
echo "Or use the CLI directly with vLLM:"
echo ""
echo "  python src/step_1_extractor.py --dir pdfs/ --output output_jsons/ \\"
echo "      --backend vllm --vllm-url http://localhost:$PORT/v1"
echo ""
echo "To stop the server later:"
echo "  kill \$(cat logs/vllm.pid)"
