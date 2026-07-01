# Vietnamese Resume Extractor Agent

This project implements the first component (the **Resume Extractor Agent**) of the multi-agent resume screening framework outlined in the research paper. It extracts structured information (position, level, self-evaluation, skills, work experience, basic info, and education) from Vietnamese PDF resumes using the **Qwen2.5-7B-Instruct** large language model.

The system is designed to run efficiently on a SLURM-managed High-Performance Computing (HPC) GPU cluster (e.g., equipped with NVIDIA Blackwell GPUs).

---

## 🚀 Setup & Execution Guide

Follow these step-by-step instructions to connect to the cluster, prepare your environment, and execute the resume extractor.

### Step 1: Connect to the Login Node
1. Ensure your VPN (NetBird) is running and active.
2. Open your local terminal on your Mac and SSH into the login node:
   ```bash
   ssh slurmdang14@100.84.19.126
   ```

### Step 2: Set Up the Conda Environment
Once logged into the login node, create your personal Python environment and install the required dependencies.

> [!NOTE]
> Since home directory disk quotas can be limited, we configure the Conda environments and package downloads to use the 2TB SSD compute scratch space (`/compute_home`) to prevent download corruption.

```bash
# 1. Load Miniconda
module load miniconda3

# 3. Create a python 3.11 environment
conda create -n resume_env python=3.11 -y

# 4. Activate the environment (using source activate for SLURM compatibility)
source activate resume_env

# 5. Install the required Python packages
pip install -r requirements.txt
```

### Step 3: Open an Interactive Shell on the Compute Node
Model inference must be performed on the GPU compute node (`fuvaiislurm0`). Do not run inference workloads directly on the shared login node.

To request a GPU session under the **Student Partition** (1 GPU, 4 CPU cores, 16GB RAM, max 2 hours):
```bash
srun --partition=student --gres=gpu:1 --cpus-per-task=4 --mem=16G --time=02:00:00 --pty bash
```
Your terminal prompt will change, indicating that you have successfully moved to the compute node.

### Step 4: Run the Extractor Agent
Inside the interactive session on the compute node, re-activate your environment and run the python script:

```bash
# 1. Activate conda environment
module load miniconda3
source activate resume_env