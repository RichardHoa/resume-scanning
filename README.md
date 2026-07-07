# Vietnamese Resume Extractor Agent

This project implements the first component (the **Resume Extractor Agent**) of the multi-agent resume screening framework outlined in the research paper. It extracts structured information (position, level, self-evaluation, skills, work experience, basic info, and education) from Vietnamese PDF resumes using a large language model.

The system is designed to run efficiently on a SLURM-managed High-Performance Computing (HPC) GPU cluster (e.g., equipped with NVIDIA Blackwell GPUs).

---

## 🔧 Choosing an Inference Backend

The extractor supports two inference backends. **Pick the one that matches your use-case:**

| | HuggingFace Transformers (default) | vLLM Server |
|---|---|---|
| **When to use** | CLI batch processing — one resume at a time | Web server (`server.py`) serving concurrent browser requests |
| **Setup** | Zero extra setup — model loads in-process | Must start vLLM server first (`scripts/start_vllm.sh`) |
| **Performance** | Fastest for sequential (batch-size = 1) workloads | Fastest when handling multiple simultaneous requests via continuous batching |
| **VRAM** | Uses only what the model needs (~14–20 GB) | Pre-allocates a configurable % of VRAM for KV-cache at startup |
| **Flag** | `--backend transformers` (default, can be omitted) | `--backend vllm --vllm-url http://localhost:8100/v1` |

> **Rule of thumb:** If you're running `step_1_extractor.py` from the command line, use the default. If you're deploying `server.py` for users to upload resumes through a web browser, use vLLM.

---

## 🚀 Quick Start

### Option A: HuggingFace Transformers (Default — Recommended for CLI)

No extra server needed. Just run the extractor directly:

```bash
# Single PDF
python src/step_1_extractor.py \
    --pdf pdfs/vietnamese_resume_1.pdf \
    --output output_jsons/vietnamese_resume_1.json

# Batch — all PDFs in a directory
python src/step_1_extractor.py \
    --dir pdfs/ \
    --output output_jsons/

# With a specific model
python src/step_1_extractor.py \
    --dir pdfs/ \
    --output output_jsons/ \
    --model-name Qwen/Qwen3.6-27B-FP8

# Vision mode (send page images instead of extracted text)
python src/step_1_extractor.py \
    --pdf pdfs/complex_layout_resume.pdf \
    --output out.json \
    --image
```

### Option B: vLLM Server (For the Web Server / Concurrent Requests)

**Step 1 — Start the vLLM server:**

```bash
bash scripts/start_vllm.sh                           # default model
bash scripts/start_vllm.sh Qwen/Qwen2.5-7B-Instruct  # or specify a model
```

Wait for it to load (watch with `tail -f logs/vllm.log` until you see `Started server process`).

**Step 2 — Start the web server:**

```bash
python src/server.py --backend vllm --vllm-url http://localhost:8100/v1
```

Open `http://localhost:8005` in your browser to upload resumes through the UI.

**Or use the CLI with vLLM directly:**

```bash
python src/step_1_extractor.py \
    --dir pdfs/ \
    --output output_jsons/ \
    --backend vllm \
    --vllm-url http://localhost:8100/v1
```

**Stop the vLLM server when done:**

```bash
kill $(cat logs/vllm.pid)
```

---

## 📋 CLI Reference

### `step_1_extractor.py` — Resume Extraction

| Flag | Default | Description |
|---|---|---|
| `--pdf PATH` | — | Path to a single PDF resume |
| `--dir PATH` | — | Path to a directory of PDF resumes (batch mode) |
| `--output PATH` | — | Output JSON file (single mode) or directory (batch mode). **Required** for `--dir` |
| `--model-name NAME` | `Qwen/Qwen2.5-7B-Instruct` | HuggingFace model repo ID or local path |
| `--backend` | `transformers` | `transformers` (in-process HF) or `vllm` (HTTP to vLLM server) |
| `--vllm-url URL` | `http://localhost:8100/v1` | vLLM server URL (only used with `--backend vllm`) |
| `--image` | off | Vision-only mode: send PDF page images to the model instead of extracted text |
| `--mock` | off | Return mock JSON without loading the model (for testing) |
| `--arr NUMS` | — | Comma-separated resume numbers to process, e.g. `--arr=6,7,8,10` |
| `--approved` | off | Only process PDFs with a corresponding ground truth JSON in `approved_jsons/` |

### `server.py` — Web Server

| Flag | Default | Description |
|---|---|---|
| `--backend` | `vllm` | `transformers` or `vllm` |
| `--vllm-url URL` | `http://localhost:8100/v1` | vLLM server URL |
| `--model NAME` | auto-detected | Model name (auto-discovered from vLLM if not set) |
| `--image` | off | Vision-only mode |
| `--mock` | off | Mock mode for testing |
| `--host` | `0.0.0.0` | Server bind address |
| `--port` | `8005` | Server bind port |

### `evaluate.py` — Evaluation

Compares extracted JSON outputs against approved ground truth JSONs using embedding-based similarity scoring.

```bash
python src/evaluate.py --extracted output_jsons/ --ground-truth approved_jsons/
```

---

## 🖥️ SLURM / HPC Cluster Setup

### Step 1: Connect to the Login Node

1. Ensure your VPN (NetBird) is running and active.
2. SSH into the login node:
   ```bash
   ssh slurmdang14@100.84.19.126
   ```

### Step 2: Set Up the Conda Environment

> **Note:** Since home directory disk quotas can be limited, we configure the Conda environments and package downloads to use the 2TB SSD compute scratch space (`/compute_home`) to prevent download corruption.

```bash
# Load Miniconda
module load miniconda3

# Create a Python 3.11 environment
conda create -n resume_env python=3.11 -y

# Activate the environment (using source activate for SLURM compatibility)
source activate resume_env

# Install the required Python packages
pip install -r requirements.txt
```

### Step 3: Open an Interactive Shell on the Compute Node

Model inference must be performed on the GPU compute node (`fuvaiislurm0`). Do not run inference workloads directly on the shared login node.

To request a GPU session under the **Student Partition** (1 GPU, 4 CPU cores, 16GB RAM, max 2 hours):

```bash
srun --partition=student --gres=gpu:1 --cpus-per-task=4 --mem=16G --time=02:00:00 --pty bash
```

### Step 4: Run the Extractor

Inside the interactive session on the compute node:

```bash
module load miniconda3
source activate resume_env

# Default HF backend
python src/step_1_extractor.py --dir pdfs/ --output output_jsons/
```