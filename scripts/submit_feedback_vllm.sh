#!/bin/bash
#SBATCH --job-name=feedback_vllm
#SBATCH --partition=student
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=64G
#SBATCH --gres=gpu:1
#SBATCH --time=12:00:00
#SBATCH --output=logging/slurm_feedback_%j.out
#SBATCH --error=logging/slurm_feedback_%j.err

# -----------------------------------------------------------------------------
# SLURM Batch Job Script: backfill Candidate Feedback into existing evaluation reports
#
# Usage: sbatch scripts/submit_feedback_vllm.sh [REPORT_DIR] [MODEL]
#   REPORT_DIR  directory of evaluation reports (default: runs/full-cnb/evaluation_json)
#   MODEL       model profile key or HuggingFace model ID (default: the default profile)
#
# Runs the Review Panel only on reports whose Candidate Feedback is missing, skipped or failed, and
# writes candidate_feedback back into each report. Scores are never re-computed. Failed Evaluations
# are skipped and listed at the end. Rerunning on a finished directory makes no LLM calls.
# -----------------------------------------------------------------------------

REPORT_DIR="${1:-runs/full-cnb/evaluation_json}"
RAW_MODEL="$2"
INITIAL_CWD="$(pwd)"

# Resolve the report directory against the submitting directory, before config.sh moves to the project root
if [[ "$REPORT_DIR" != /* && -d "$INITIAL_CWD/$REPORT_DIR" ]]; then
  REPORT_DIR="$(cd "$INITIAL_CWD/$REPORT_DIR" && pwd)"
fi

# -----------------------------------------------------------------------------
# Robust Location of config.sh and vllm_utils.sh
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
source "$SCRIPT_DIR/vllm_utils.sh"
source "$SCRIPT_DIR/model_profiles.sh"

if [ -z "$PROJECT_ROOT" ]; then
  echo "[CRITICAL ERROR] PROJECT_ROOT is not set after sourcing config.sh!" >&2
  exit 1
fi

# Force execution strictly from project repository root directory
cd "$PROJECT_ROOT" || exit 1

# Setup optimization & threading environment variables
setup_vllm_env

# Review Panel prompt logs go to the run folder the reports are in (docs/adr/0010-run-folders.md)
case "$(basename "$(dirname "$REPORT_DIR")")" in
  full-cnb|full-tech|full-web-cnb|full-web-tech) export RUN_DIR="$(dirname "$REPORT_DIR")" ;;
esac
mkdir -p "$PROJECT_ROOT/logs" "$PROJECT_ROOT/logging"

# Load cluster modules (miniconda3)
echo "[$(date +'%H:%M:%S')] STEP 1: Loading system environment modules..."
module load miniconda3 2>/dev/null || true
module load cuda 2>/dev/null || module load cuda13.0 2>/dev/null || true

# Check conda binary path
if ! command -v conda &>/dev/null; then
  for c_path in /compute_home/$USER/miniconda3/bin/conda /compute_home/$USER/anaconda3/bin/conda /opt/miniconda3/bin/conda /opt/anaconda3/bin/conda; do
    if [ -x "$c_path" ]; then
      export PATH="$(dirname "$c_path"):$PATH"
      break
    fi
  done
fi

echo "[$(date +'%H:%M:%S')] STEP 2: Activating Conda environment 'resume_env'..."
eval "$(conda shell.bash hook 2>/dev/null)" || true
source activate resume_env 2>/dev/null || conda activate resume_env 2>/dev/null || true
echo "[$(date +'%H:%M:%S')] Step 2 complete. Active Python: $(which python3 2>/dev/null || echo 'python3 not found')"

# Print GPU info on compute node immediately
echo "====================================================================="
echo "[$(date +'%Y-%m-%d %H:%M:%S')] STEP 3: Inspecting GPU hardware allocation..."
nvidia-smi 2>/dev/null || echo "nvidia-smi not available"
echo "====================================================================="

PORT=$(find_free_port)
resolve_model_arg "$RAW_MODEL" || exit 1

echo "[$(date +'%H:%M:%S')] Project Root: $PROJECT_ROOT"
echo "[$(date +'%H:%M:%S')] Target Model: $MODEL"
echo "[$(date +'%H:%M:%S')] Allocated Server Port: $PORT"
echo "[$(date +'%H:%M:%S')] HF Cache Path: ${HF_HOME:-default}"

start_vllm_server "$MODEL" "$PORT" "$PROJECT_ROOT/logs/vllm_batch.log" || exit 1

echo "=== vLLM Server Ready! ==="

rm -f "$PROJECT_ROOT/logging/token_usage.jsonl"
echo "=== Backfilling Candidate Feedback in '$REPORT_DIR' ==="
python3 -u "$PROJECT_ROOT/src/cli/backfill_feedback.py" \
  --model-name "$MODEL" \
  --vllm-url "http://127.0.0.1:$PORT/v1" \
  --dir "$REPORT_DIR"

stop_vllm_server
python3 "$PROJECT_ROOT/scripts/token_stats.py"
echo "=== [$(date +'%Y-%m-%d %H:%M:%S')] Feedback Backfill Job Finished ==="
