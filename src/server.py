#!/usr/bin/env python3
"""
Resume Extraction Web Server (FastAPI)

Provides a web UI and REST API for uploading PDF resumes and receiving
structured JSON extractions.  Wraps :class:`ResumeExtractor` from
``step_1_extractor.py``.

Backend selection:
    This server defaults to ``--backend vllm`` because the web server
    use-case (concurrent browser requests) is where vLLM's continuous
    batching provides a real throughput advantage.  A running vLLM server
    must be started first (see ``scripts/start_vllm.sh``).

    For simple one-off or batch CLI usage without a web UI, prefer
    running ``step_1_extractor.py`` directly with the default HuggingFace
    Transformers backend (``--backend transformers``).

Usage:
    # Start vLLM server first
    bash scripts/start_vllm.sh

    # Then start this web server
    python src/server.py                            # defaults to vLLM
    python src/server.py --backend transformers      # or use HF directly
"""
import os
import sys
import argparse
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

# Add paths to sys.path so we can import step_1_extractor robustly
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from step_1_extractor import ResumeExtractor
from step_2_evaluate import ResumeEvaluator
from src.core.state import state
from src.core.evaluation_order import load_evaluation_order
from src.api import include_api_routers

# 1. Parse Command Line Arguments at module level to let uvicorn and parser coexist
parser = argparse.ArgumentParser(description="Resume Extractor FastAPI Server")
parser.add_argument("--model", type=str, default=None,
                    help="Model name (auto-detected from vLLM server if not provided)")
parser.add_argument("--mock", action="store_true",
                    help="Mock mode: use pre-defined mock extraction without loading the model")
parser.add_argument("--backend", type=str, default="vllm", choices=["transformers", "vllm"],
                    help="Inference backend: 'transformers' (load model locally) or 'vllm' (call a running vLLM server)")
parser.add_argument("--vllm-url", type=str, default="http://127.0.0.1:8100/v1",
                    help="Base URL of the vLLM OpenAI-compatible server (only used with --backend vllm)")
parser.add_argument("--host", type=str, default="0.0.0.0",
                    help="Host bind address")
parser.add_argument("--port", type=int, default=8005,
                    help="Port bind number")

# Use parse_known_args so that uvicorn flags like --reload do not crash our parser
args, unknown_args = parser.parse_known_args()

# Populate global state
state.args = args
state.temp_dir = os.path.join(SCRIPT_DIR, "temp_uploads")
state.static_dir = os.path.join(SCRIPT_DIR, "static")

os.makedirs(state.temp_dir, exist_ok=True)
os.makedirs(state.static_dir, exist_ok=True)

# Initialize the global extractor and evaluator instances in state
state.extractor = ResumeExtractor(
    model_name=args.model, mock=args.mock,
    backend=args.backend, vllm_url=args.vllm_url
)

state.evaluator = ResumeEvaluator(
    model_name=args.model or "Qwen/Qwen3.5-9B", mock=args.mock,
    backend=args.backend, vllm_url=args.vllm_url
)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load model once at startup to optimize processing times."""
    print("----------------------------------------------------------------", file=sys.stderr)
    print("Initializing Resume Extraction & Evaluation Server", file=sys.stderr)
    print(f"Backend: {args.backend}", file=sys.stderr)
    print(f"Mock Mode: {args.mock}", file=sys.stderr)
    print("----------------------------------------------------------------", file=sys.stderr)
    
    # Load secret evaluation order file on server startup
    startup_order = load_evaluation_order()
    if startup_order.get("file_found"):
        print(f"[SERVER EVALUATION ORDER] Secret order loaded from '{startup_order.get('file_path')}': Tier 1={len(startup_order.get('tier1', []))} items, Tier 2={len(startup_order.get('tier2', []))} items", file=sys.stderr)
    else:
        print("[SERVER EVALUATION ORDER] Warning: No secret evaluation_order.txt file found at startup.", file=sys.stderr)

    if not args.mock and args.backend == "transformers":
        print("Loading local model (this can take a few minutes)...", file=sys.stderr)
        state.extractor.load_model()
        state.evaluator.tokenizer = getattr(state.extractor, 'tokenizer_or_processor', None)
        state.evaluator.model = state.extractor.model
        print("Model loaded successfully!", file=sys.stderr)
    elif args.backend == "vllm":
        print(f"Connecting to vLLM server at {args.vllm_url}...", file=sys.stderr)
        state.extractor.load_model()
        state.evaluator.model_name = state.extractor.model_name
        print(f"Using model: {state.extractor.model_name}", file=sys.stderr)
    else:
        print("Mock mode is enabled. Model will not be loaded into memory.", file=sys.stderr)
    yield


# 2. Create the FastAPI Application
app = FastAPI(title="Resume Extraction Server", lifespan=lifespan)

# Mount static files folder & include routers
app.mount("/static", StaticFiles(directory=state.static_dir), name="static")
include_api_routers(app)

if __name__ == "__main__":
    print(f"Starting server on {args.host}:{args.port}", file=sys.stderr)
    uvicorn.run(app, host=args.host, port=args.port)
