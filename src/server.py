#!/usr/bin/env python3
"""
Resume Extraction Web Server (FastAPI)

Provides a web UI and REST API for uploading PDF resumes and receiving
structured JSON extractions.  Wraps :class:`ResumeExtractor` from
``step_1_extractor.py``.

Inference runs on a vLLM server, which must be started first
(see ``scripts/server.sh --start-vllm``).

Usage:
    # Start vLLM server first
    ./scripts/server.sh --start-vllm

    # Then start this web server
    python src/server.py
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

# The website writes only to its own run folder, one per resume set, or runs/web with no resume set
# (docs/adr/0010-run-folders.md). Set before any src import, since src.core.config builds every path from it when
# first imported
if "--tech" in sys.argv[1:]:
    os.environ["RUN_DIR"] = "web-tech"
elif "--cnb" in sys.argv[1:]:
    os.environ["RUN_DIR"] = "web-cnb"
else:
    os.environ["RUN_DIR"] = "web"

from step_1_extractor import ResumeExtractor
from step_2_evaluate import ResumeEvaluator
from src.core.state import state
from src.core.evaluation_order import load_evaluation_order, set_resume_set, CNB_RESUME_SET, TECH_RESUME_SET
from src.core.reference_date import set_reference_date, TECH_REFERENCE_DATE
from src.api import include_api_routers

# 1. Parse Command Line Arguments at module level to let uvicorn and parser coexist
parser = argparse.ArgumentParser(description="Resume Extractor FastAPI Server")
parser.add_argument("--model", type=str, default=None,
                    help="Model name (auto-detected from vLLM server if not provided)")
parser.add_argument("--mock", action="store_true",
                    help="Mock mode: use pre-defined mock extraction without loading the model")
parser.add_argument("--vllm-url", type=str, default="http://127.0.0.1:8100/v1",
                    help="Base URL of the vLLM OpenAI-compatible server")
parser.add_argument("--host", type=str, default="0.0.0.0",
                    help="Host bind address")
parser.add_argument("--port", type=int, default=8005,
                    help="Port bind number")
resume_set_group = parser.add_mutually_exclusive_group()
resume_set_group.add_argument("--cnb", action="store_true",
                              help="CnB resume set: rank by evaluation_order.txt")
resume_set_group.add_argument("--tech", action="store_true",
                              help=f"Tech resume set: rank by evaluation_order_tech.txt and use the set's Reference Date ({TECH_REFERENCE_DATE})")

# Use parse_known_args so that uvicorn flags like --reload do not crash our parser
args, unknown_args = parser.parse_known_args()

# Before any prompt is built: each resume set is ranked by its own secret file, and the Tech one is read as of
# December 2015. With neither flag no dataset is loaded, so no secret file is read
resume_set = TECH_RESUME_SET if args.tech else CNB_RESUME_SET if args.cnb else None
set_resume_set(resume_set)
if args.tech:
    set_reference_date(TECH_REFERENCE_DATE)

# Populate global state
state.args = args
state.temp_dir = os.path.join(SCRIPT_DIR, "temp_uploads")
state.static_dir = os.path.join(SCRIPT_DIR, "static")

os.makedirs(state.temp_dir, exist_ok=True)
os.makedirs(state.static_dir, exist_ok=True)

# Initialize the global extractor and evaluator instances in state
state.extractor = ResumeExtractor(model_name=args.model, mock=args.mock, vllm_url=args.vllm_url)

state.evaluator = ResumeEvaluator(model_name=args.model, mock=args.mock, vllm_url=args.vllm_url)


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Resolves the vLLM model name once at startup."""
    print("----------------------------------------------------------------", file=sys.stderr)
    print("Initializing Resume Extraction & Evaluation Server", file=sys.stderr)
    print(f"Mock Mode: {args.mock}", file=sys.stderr)
    print(f"Resume Set: {resume_set or 'none (no dataset loaded)'}", file=sys.stderr)
    print("----------------------------------------------------------------", file=sys.stderr)
    
    # Load secret evaluation order file on server startup
    startup_order = load_evaluation_order()
    if resume_set is None:
        print("[SERVER EVALUATION ORDER] No resume set given (--cnb or --tech): no evaluation order is loaded.", file=sys.stderr)
    elif startup_order.get("file_found"):
        print(f"[SERVER EVALUATION ORDER] Secret order loaded from '{startup_order.get('file_path')}': Tier 1={len(startup_order.get('tier1', []))} items, Tier 2={len(startup_order.get('tier2', []))} items", file=sys.stderr)
    else:
        order_name = "evaluation_order_tech.txt" if args.tech else "evaluation_order.txt"
        print(f"[SERVER EVALUATION ORDER] Warning: No secret {order_name} file found at startup.", file=sys.stderr)

    if not args.mock:
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
