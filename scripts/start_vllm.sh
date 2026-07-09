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

MODEL="${1:-numind/NuExtract3}"
PORT=8100
export VLLM_USE_DEEP_GEMM=0

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
    --max-model-len 20000 \
    --gpu-memory-utilization 0.90 \
    --kv-cache-dtype fp8 \
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
