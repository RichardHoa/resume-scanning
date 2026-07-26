# Vietnamese Resume Extractor Agent

An automated system to extract structured information (personal details, skills, work experience, education, etc.) from Vietnamese PDF resumes into clean JSON data using Large Language Models (LLMs).

---

## 💡 Our Approach

1. **Layout Extraction**: We use **Docling** to parse the PDF resume into a layout-aware Markdown format.
2. **Structured JSON Extraction**: We pass the Markdown representation to an LLM (such as `Qwen/Qwen3.5-9B` or `Qwen/Qwen3.5-35B-A3B`) which parses and formats the information according to predefined JSON schemas.

*Recommended models for best extraction performance:*
- **Qwen/Qwen3.5-35B-A3B**: Best accuracy when GPU memory is available.
- **Qwen/Qwen3.5-9B**: Great balance of performance and lower memory usage.

---

## 📁 Project Structure

Here is an overview of what each key file and folder does in this repository:

- `src/step_1_extractor.py`: The main extraction script. Converts PDF resumes to Markdown using Docling and uses an LLM to generate structured JSON output.
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
python3 src/step_1_extractor.py --dir pdfs/ --output output_jsons/
```

### 2. Run the Web Application

If you prefer using a browser user interface:

```bash
python3 src/server.py
```

Then open your browser and navigate to `http://localhost:8005`.

### 3. Evaluate Results

To score your extracted JSON files against ground truth files:

```bash
python3 src/evaluate.py --extracted output_jsons/ --ground-truth approved_jsons/
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
python3 src/step_1_extractor.py --dir pdfs/ --output output_jsons/
```