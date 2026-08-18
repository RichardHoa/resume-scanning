#!/bin/bash
#SBATCH --job-name=eval_transformer
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
# SLURM Batch Job Script for Resume Evaluation (Transformers Backend)
# -----------------------------------------------------------------------------

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
source "$SCRIPT_DIR/config.sh"

# Load cluster modules (miniconda3)
module load miniconda3 2>/dev/null || true
module load cuda 2>/dev/null || module load cuda13.0 2>/dev/null || true

# Activate Conda environment
eval "$(conda shell.bash hook 2>/dev/null)" || true
source activate resume_env 2>/dev/null || conda activate resume_env 2>/dev/null || true

# Ensure output & log directories exist
mkdir -p evaluation_json logging output_jsons pdfs

MODEL="${1:-Qwen/Qwen3.5-35B-A3B}"

# Print GPU info on compute node
echo "=== Node & GPU Allocation Info ==="
echo "Node: $(hostname)"
echo "Target Model: $MODEL"
nvidia-smi 2>/dev/null || echo "nvidia-smi not available"

JSON_COUNT=$(find output_jsons/ -maxdepth 1 -name "*.json" 2>/dev/null | wc -l | tr -d ' ')
if [ "$JSON_COUNT" -eq 0 ]; then
  echo "=== [Step 1 Auto-Run] 'output_jsons/' is empty. Extracting PDF resumes from 'pdfs/' via transformers backend... ==="
  python3 -u src/step_1_extractor.py \
    --dir pdfs \
    --output output_jsons \
    --backend transformers \
    --model-name "$MODEL"
fi

echo "=== Starting Batch Evaluation via HuggingFace Transformers Backend ==="
python3 -u src/step_2_evaluate.py \
  --model-name "$MODEL" \
  --backend transformers \
  --dir output_jsons \
  --job-req hr-requirement.txt \
  --output evaluation_json

echo "=== Batch Evaluation Job Finished ==="
