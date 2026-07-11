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
import json
import argparse
import uvicorn
from contextlib import asynccontextmanager
from fastapi import FastAPI, UploadFile, File, HTTPException
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles

# Add paths to sys.path so we can import step_1_extractor robustly
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__))
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
PARENT_DIR = os.path.dirname(SCRIPT_DIR)
if PARENT_DIR not in sys.path:
    sys.path.insert(0, PARENT_DIR)

from step_1_extractor import ResumeExtractor

# 1. Parse Command Line Arguments at module level to let uvicorn and parser coexist
parser = argparse.ArgumentParser(description="Resume Extractor FastAPI Server")
parser.add_argument("--model", type=str, default=None,
                    help="Model name (auto-detected from vLLM server if not provided)")
parser.add_argument("--mock", action="store_true",
                    help="Mock mode: use pre-defined mock extraction without loading the model")
parser.add_argument("--backend", type=str, default="vllm", choices=["transformers", "vllm"],
                    help="Inference backend: 'transformers' (load model locally) or 'vllm' (call a running vLLM server)")
parser.add_argument("--vllm-url", type=str, default="http://localhost:8100/v1",
                    help="Base URL of the vLLM OpenAI-compatible server (only used with --backend vllm)")
parser.add_argument("--host", type=str, default="0.0.0.0",
                    help="Host bind address")
parser.add_argument("--port", type=int, default=8005,
                    help="Port bind number")

# Use parse_known_args so that uvicorn flags like --reload do not crash our parser
args, unknown_args = parser.parse_known_args()

# Initialize the global extractor instance
extractor = ResumeExtractor(
    model_name=args.model, mock=args.mock,
    backend=args.backend, vllm_url=args.vllm_url
)

@asynccontextmanager
async def lifespan(app: FastAPI):
    """Load model once at startup to optimize processing times."""
    print("----------------------------------------------------------------", file=sys.stderr)
    print(f"Initializing Resume Extraction Server", file=sys.stderr)
    print(f"Backend: {args.backend}", file=sys.stderr)
    print(f"Mock Mode: {args.mock}", file=sys.stderr)
    print("----------------------------------------------------------------", file=sys.stderr)
    
    if not args.mock and args.backend == "transformers":
        print("Loading local model (this can take a few minutes)...", file=sys.stderr)
        extractor.load_model()
        print("Model loaded successfully!", file=sys.stderr)
    elif args.backend == "vllm":
        print(f"Connecting to vLLM server at {args.vllm_url}...", file=sys.stderr)
        extractor.load_model()
        print(f"Using model: {extractor.model_name}", file=sys.stderr)
    else:
        print("Mock mode is enabled. Model will not be loaded into memory.", file=sys.stderr)
    yield

# 2. Create the FastAPI Application
app = FastAPI(title="Resume Extraction Server", lifespan=lifespan)

# Ensure temporary upload directory exists
TEMP_DIR = os.path.join(SCRIPT_DIR, "temp_uploads")
os.makedirs(TEMP_DIR, exist_ok=True)

# Mount the static files folder
STATIC_DIR = os.path.join(SCRIPT_DIR, "static")
os.makedirs(STATIC_DIR, exist_ok=True)
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

@app.get("/")
def read_root():
    """Serves the dashboard index.html page."""
    index_path = os.path.join(STATIC_DIR, "index.html")
    if not os.path.exists(index_path):
        from fastapi.responses import HTMLResponse
        return HTMLResponse(
            content="<h1>Frontend not found</h1><p>Please build index.html in src/static/</p>",
            status_code=404
        )
    return FileResponse(index_path)

@app.get("/api/config")
def get_config():
    """Exposes current server configuration to the UI."""
    return {
        "model": extractor.model_name,
        "backend": args.backend,
        "image_mode": False,
        "mock": args.mock
    }

@app.post("/api/extract")
async def extract_resume(file: UploadFile = File(...)):
    """Handles PDF resume uploads, extracts details, and returns JSON."""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    # Save uploaded file temporarily in the workspace directory
    safe_filename = os.path.basename(file.filename)
    temp_file_path = os.path.join(TEMP_DIR, safe_filename)
    try:
        with open(temp_file_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)
            
        print(f"Received file: {safe_filename}, processing extraction...", file=sys.stderr)
        
        # Run extractor class
        import time
        start_time = time.time()
        formatted_json_str = extractor.extract(temp_file_path)
        elapsed_time = time.time() - start_time
        
        # Load string back to dict to return standard structured response
        try:
            extracted_data = json.loads(formatted_json_str)
            headers = {"X-Extraction-Time": f"{elapsed_time:.2f}"}
            return JSONResponse(content=extracted_data, headers=headers)
        except json.JSONDecodeError:
            # Fallback in case raw text repair failed
            headers = {"X-Extraction-Time": f"{elapsed_time:.2f}"}
            return JSONResponse(
                content={"error": "Failed to parse model output as JSON", "raw_output": formatted_json_str},
                status_code=500,
                headers=headers
            )
            
    except Exception as e:
        print(f"Error during extraction of {safe_filename}: {e}", file=sys.stderr)
        raise HTTPException(status_code=500, detail=str(e))
        
    finally:
        # Cleanup temp upload file
        if os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except Exception as cleanup_err:
                print(f"Warning: Failed to delete temp file {temp_file_path}: {cleanup_err}", file=sys.stderr)

if __name__ == "__main__":
    print(f"Starting server on {args.host}:{args.port}", file=sys.stderr)
    uvicorn.run(app, host=args.host, port=args.port)
