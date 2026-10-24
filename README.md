# Vietnamese Resume Extractor Agent

An automated system to extract structured information (personal details, skills, work experience, education, etc.) from Vietnamese PDF resumes into clean JSON data using Large Language Models (LLMs).

---

## 💡 Our Approach

1. **Layout Extraction**: We use **PyMuPDF4LLM** to parse the PDF resume into a layout-aware Markdown format (Docling was tried and rejected: it could not detect tables, see ADR 0008). A scanned PDF (no page has text) is rejected and HR is asked to get a text PDF from the candidate; no OCR is run.
2. **Structured JSON Extraction**: We pass the Markdown representation to an LLM (such as `Qwen/Qwen3.5-9B` or `Qwen/Qwen3.5-35B-A3B`) which parses and formats the information according to predefined JSON schemas.

*Recommended models for best extraction performance:*
- **Qwen/Qwen3.5-35B-A3B**: Best accuracy when GPU memory is available.
- **Qwen/Qwen3.5-9B**: Great balance of performance and lower memory usage.

---

## 📁 Project Structure

Here is an overview of what each key file and folder does in this repository:

- `src/step_1_extractor.py`: The main extraction script. Converts PDF resumes to Markdown using PyMuPDF4LLM and uses an LLM to generate structured JSON output.
- `src/server.py`: A web server (FastAPI) that provides a user-friendly browser interface for uploading resumes and viewing extracted JSON results.
- `src/evaluate.py`: Evaluates the accuracy of extracted JSON output by comparing it against ground-truth data using semantic similarity scoring.
- `src/ground_truth.py`: A web-based tool for reviewing and validating ground-truth resume extractions.
- `schemas/`: Contains JSON schema definitions (`qwen_schema.json`, `nuextract_schema.json`) that define the required extraction output format.
- `pdfs/`: Directory for input PDF resume files.
- `approved_jsons/`: Directory for verified ground-truth JSON files used for testing and evaluation.

---

## 🚀 How to Run the Code

### 1. Run Extraction via Command Line

**Process a single PDF resume:**
```bash
python3 src/step_1_extractor.py --pdf pdfs/sample_resume.pdf --output output.json
```

**Process a whole folder of PDF resumes:**
```bash
python3 src/step_1_extractor.py --dir pdfs/ --output runs/batch-cnb/extraction_json/
```

### 2. Run the Web Application

If you prefer using a browser user interface:

```bash
python3 src/server.py
```

Then open your browser and navigate to `http://localhost:8005`.

### Where outputs go

Every output lives in one run folder under `runs/` (see `docs/adr/0010-run-folders.md`): `batch-cnb` and
`batch-tech` for the SLURM pipeline jobs (which must be given `--cnb` or `--tech`), `web-cnb` and `web-tech` for the
website (`server.sh --cnb` or `--tech`), and `web` for a website started with neither flag, which loads no dataset:
no evaluation order and no pipeline results. Each holds `logs/`, `prompt_logs/<resume>/<category>/`, `extraction_markdown/`, `extraction_json/`, `evaluation_json/`
and `resumes_pdf/`. A pipeline job wipes its run folder before it starts; the website's is never wiped. The
website also shows the matching pipeline run folder's results, read-only, and each candidate's "Chi tiết cho nhà
phát triển" panel shows everything stored for that resume.

### 3. Evaluate Results

To score your extracted JSON files against ground truth files:

```bash
python3 src/evaluate.py --extracted runs/batch-cnb/extraction_json/ --ground-truth approved_jsons/
```

### 4. AI Proofreading Pass (scanned books)

`scripts/submit_correction.sh` has a model transcribe every page of a scanned book from its scan, with the OCR
text as a draft, and joins the pages into a new text of the book.

1. In the vsc repo, run `python -m vsc_ocr prepare-ai <book>` and copy the folder it makes, `data-for-ai/<book>/`,
   here as `vsc-project/`.
2. Run the pass:

```bash
bash scripts/submit_correction.sh --dry-run              # login node: checks every task fits the context window
sbatch scripts/submit_correction.sh --pages 10-40         # a trial slice
sbatch scripts/submit_correction.sh --pages 10-40 --no-ocr-hint   # the same slice from the images only
sbatch scripts/submit_correction.sh                       # the whole book
sbatch scripts/submit_correction.sh --run-dir vsc-project/ai-pass/<time>   # finish a run's failed tasks
```

3. Copy `book.ai.md`, `ai_corrections.jsonl` and `boxes.jsonl` from the run folder `vsc-project/ai-pass/<time>/`
   back to `data/books/<book>/ai/` in the vsc repo and review them there with `python -m vsc_ocr review <book> --ai`.

`coverage.jsonl` in the run folder lists, page by page, the OCR lines the model left out (put back, marked
`⚠ ai-missed?`) and the text it wrote that the OCR didn't see (marked ⚠). To choose between sending the OCR draft
or not, compare two runs of the same slice against the reviewer's own corrections:

```bash
python3 scripts/compare_ocr_hint.py vsc-project/ai-pass/<with-hint> vsc-project/ai-pass/<without>
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

# Activate the environment
source activate resume_env

# Install the required Python packages
pip install -r requirements.txt
```

> **Note:** `requirements.txt` pins `vllm` and the CUDA packages, and some shared dependencies (e.g. `fastapi`, `numpy`) are held at the versions `vllm` requires. It is meant to be installed only in this GPU compute-node environment.

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

# Process a directory of resumes
python3 src/step_1_extractor.py --dir pdfs/ --output runs/batch-cnb/extraction_json/
```