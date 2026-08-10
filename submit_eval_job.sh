#!/bin/bash
#SBATCH --job-name=eval_resumes
#SBATCH --partition=researcher
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --gres=gpu:1
#SBATCH --time=12:00:00
#SBATCH --output=logging/slurm_%j.out
#SBATCH --error=logging/slurm_%j.err

# -----------------------------------------------------------------------------
# SLURM Batch Job Script for Resume Evaluation on Compute Node (fuvaiislurm0)
# -----------------------------------------------------------------------------

# Load cluster modules (miniconda3)
module load miniconda3
# Attempt loading cuda module if available, ignore if already default
module load cuda 2>/dev/null || module load cuda13.0 2>/dev/null || true

# Activate Conda environment
source activate resume_env

# Ensure output & log directories exist
mkdir -p evaluation_json logging

# Print GPU info on compute node
echo "=== Node & GPU Allocation Info ==="
echo "Node: $(hostname)"
nvidia-smi

echo "=== Starting Batch Evaluation ==="
python3 src/step_2_evaluate.py \
  --model-name Qwen/Qwen3.5-35B-A3B \
  --backend transformers \
  --dir output_jsons \
  --job-req hr-requirement.txt \
  --output evaluation_json

echo "=== Batch Evaluation Job Finished ==="
