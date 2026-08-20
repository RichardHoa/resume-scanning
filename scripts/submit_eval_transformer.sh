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

RAW_MODEL="$1"
INITIAL_CWD="$(pwd)"

# -----------------------------------------------------------------------------
# Robust Location of config.sh
# Under SLURM, scripts are copied to /var/spool/slurmd/jobXXXXX/slurm_script,
# so BASH_SOURCE[0] points to the spool directory. We locate config.sh via
# SLURM_SUBMIT_DIR, BASH_SOURCE, or CWD.
# -----------------------------------------------------------------------------
FIND_CONFIG_DIR=""
if [ -n "$SLURM_SUBMIT_DIR" ]; then
  if [ -f "$SLURM_SUBMIT_DIR/scripts/config.sh" ]; then
    FIND_CONFIG_DIR="$SLURM_SUBMIT_DIR/scripts"
  elif [ -f "$SLURM_SUBMIT_DIR/config.sh" ]; then
    FIND_CONFIG_DIR="$SLURM_SUBMIT_DIR"
  fi
fi

if [ -z "$FIND_CONFIG_DIR" ]; then
  CANDIDATE_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" 2>/dev/null && pwd)"
  if [ -f "$CANDIDATE_DIR/config.sh" ]; then
    FIND_CONFIG_DIR="$CANDIDATE_DIR"
  elif [ -f "$CANDIDATE_DIR/scripts/config.sh" ]; then
    FIND_CONFIG_DIR="$CANDIDATE_DIR/scripts"
  fi
fi

if [ -z "$FIND_CONFIG_DIR" ]; then
  if [ -f "$INITIAL_CWD/scripts/config.sh" ]; then
    FIND_CONFIG_DIR="$INITIAL_CWD/scripts"
  elif [ -f "$INITIAL_CWD/config.sh" ]; then
    FIND_CONFIG_DIR="$INITIAL_CWD"
  fi
fi

if [ -z "$FIND_CONFIG_DIR" ] || [ ! -f "$FIND_CONFIG_DIR/config.sh" ]; then
  echo "[CRITICAL ERROR] Cannot locate 'config.sh'. Submitting directory: ${SLURM_SUBMIT_DIR:-$INITIAL_CWD}" >&2
  exit 1
fi

SCRIPT_DIR="$FIND_CONFIG_DIR"
source "$SCRIPT_DIR/config.sh"

if [ -z "$PROJECT_ROOT" ]; then
  echo "[CRITICAL ERROR] PROJECT_ROOT is not set after sourcing config.sh!" >&2
  exit 1
fi

# Force execution strictly from project repository root directory
cd "$PROJECT_ROOT" || exit 1

# Load cluster modules (miniconda3)
module load miniconda3 2>/dev/null || true
module load cuda 2>/dev/null || module load cuda13.0 2>/dev/null || true

# Activate Conda environment
eval "$(conda shell.bash hook 2>/dev/null)" || true
source activate resume_env 2>/dev/null || conda activate resume_env 2>/dev/null || true

# Ensure output & log directories exist at project root
mkdir -p "$PROJECT_ROOT/evaluation_json" "$PROJECT_ROOT/logging" "$PROJECT_ROOT/output_jsons" "$PROJECT_ROOT/pdfs" "$PROJECT_ROOT/logs"

MODEL="${RAW_MODEL:-Qwen/Qwen3.5-35B-A3B}"

# Print GPU info on compute node
echo "=== Node & GPU Allocation Info ==="
echo "Node: $(hostname)"
echo "Project Root: $PROJECT_ROOT"
echo "Target Model: $MODEL"
nvidia-smi 2>/dev/null || echo "nvidia-smi not available"

JSON_COUNT=$(find "$PROJECT_ROOT/output_jsons/" -maxdepth 1 -name "*.json" 2>/dev/null | wc -l | tr -d ' ')
if [ "$JSON_COUNT" -eq 0 ]; then
  echo "=== [Step 1 Auto-Run] 'output_jsons/' is empty. Extracting PDF resumes from 'pdfs/' via transformers backend... ==="
  python3 -u "$PROJECT_ROOT/src/step_1_extractor.py" \
    --dir pdfs \
    --output output_jsons \
    --backend transformers \
    --model-name "$MODEL"
fi

echo "=== Starting Batch Evaluation via HuggingFace Transformers Backend ==="
python3 -u "$PROJECT_ROOT/src/step_2_evaluate.py" \
  --model-name "$MODEL" \
  --backend transformers \
  --dir output_jsons \
  --job-req hr-requirement.txt \
  --output evaluation_json

echo "=== Batch Evaluation Job Finished ==="
