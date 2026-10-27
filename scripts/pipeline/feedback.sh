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
# Usage: sbatch scripts/pipeline/feedback.sh [REPORT_DIR] [MODEL]
#   REPORT_DIR  directory of evaluation reports (default: runs/batch-cnb/evaluation_json)
#   MODEL       model profile key or HuggingFace model ID (default: the default profile)
#
# Runs the Review Panel only on reports whose Candidate Feedback is missing, skipped or failed, and
# writes candidate_feedback back into each report. Scores are never re-computed. Failed Evaluations
# are skipped and listed at the end. Rerunning on a finished directory makes no LLM calls.
#
# When REPORT_DIR is the evaluation_json of a run folder (runs/batch-*, runs/web*), the Review Panel's prompt logs
# and token usage go to that run folder (docs/adr/0004-run-folders.md); otherwise to runs/batch-cnb. Nothing in the
# run folder is wiped: the printed token stats cover the whole run folder, the Review Panel step included. The vLLM
# log is logs/vllm_batch.log.
# -----------------------------------------------------------------------------

REPORT_DIR="${1:-runs/batch-cnb/evaluation_json}"
RAW_MODEL="$2"
INITIAL_CWD="$(pwd)"

# Resolve the report directory against the submitting directory, before config.sh moves to the project root
if [[ "$REPORT_DIR" != /* && -d "$INITIAL_CWD/$REPORT_DIR" ]]; then
  REPORT_DIR="$(cd "$INITIAL_CWD/$REPORT_DIR" && pwd)"
fi

# -----------------------------------------------------------------------------
# Location of the shared helpers (scripts/lib). SLURM runs a copy of this script, so under sbatch they are found
# from the submitting directory, the repository root; run with bash, from the script's own folder
# -----------------------------------------------------------------------------
LIB_DIR="${SLURM_SUBMIT_DIR:-$(pwd)}/scripts/lib"
[ -f "$LIB_DIR/config.sh" ] || LIB_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/../lib" 2>/dev/null && pwd)"
if [ ! -f "$LIB_DIR/config.sh" ]; then
  echo "[CRITICAL ERROR] Cannot locate 'scripts/lib/config.sh'. Submit from the repository root. Submitting directory: ${SLURM_SUBMIT_DIR:-$(pwd)}" >&2
  exit 1
fi

# -----------------------------------------------------------------------------
# STEP 1: Load Cluster Modules & Activate Conda Environment FIRST (config.sh reads src/core/config.py with python3)
# -----------------------------------------------------------------------------
echo "[$(date +'%H:%M:%S')] STEP 1: Loading system environment modules and activating Conda environment 'resume_env'..."
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

eval "$(conda shell.bash hook 2>/dev/null)" || true
source activate resume_env 2>/dev/null || conda activate resume_env 2>/dev/null || true
echo "[$(date +'%H:%M:%S')] Active Python: $(which python3 2>/dev/null || echo 'python3 not found')"

# -----------------------------------------------------------------------------
# STEP 2: Source Configuration & vLLM Helpers (Python environment is active)
# -----------------------------------------------------------------------------
source "$LIB_DIR/config.sh"
source "$LIB_DIR/vllm_utils.sh"
source "$LIB_DIR/model_profiles.sh"

if [ -z "$PROJECT_ROOT" ]; then
  echo "[CRITICAL ERROR] PROJECT_ROOT is not set after sourcing config.sh!" >&2
  exit 1
fi

# Force execution strictly from project repository root directory
cd "$PROJECT_ROOT" || exit 1

# Setup optimization & threading environment variables
setup_vllm_env

# Review Panel prompt logs and token usage go to the run folder the reports are in (docs/adr/0004-run-folders.md)
case "$(basename "$(dirname "$REPORT_DIR")")" in
  batch-cnb|batch-tech|web|web-cnb|web-tech) export RUN_DIR="$(dirname "$REPORT_DIR")" ;;
esac
mkdir -p "$PROJECT_ROOT/logs" "$PROJECT_ROOT/logging"

# -----------------------------------------------------------------------------
# STEP 3: Start the vLLM Server
# -----------------------------------------------------------------------------
echo "====================================================================="
echo "[$(date +'%Y-%m-%d %H:%M:%S')] STEP 3: Inspecting GPU hardware allocation..."
nvidia-smi 2>/dev/null || echo "nvidia-smi not available"
echo "====================================================================="

PORT=$(find_free_port)
resolve_model_arg "$RAW_MODEL" || exit 1

echo "[$(date +'%H:%M:%S')] Project Root: $PROJECT_ROOT"
echo "[$(date +'%H:%M:%S')] Report Directory: $REPORT_DIR"
echo "[$(date +'%H:%M:%S')] Run Folder: ${RUN_DIR:-runs/batch-cnb (default)}"
echo "[$(date +'%H:%M:%S')] Target Model: $MODEL"
echo "[$(date +'%H:%M:%S')] Allocated Server Port: $PORT"
echo "[$(date +'%H:%M:%S')] HF Cache Path: ${HF_HOME:-default}"

start_vllm_server "$MODEL" "$PORT" "$PROJECT_ROOT/logs/vllm_batch.log" || exit 1

# -----------------------------------------------------------------------------
# STEP 4: Backfill Candidate Feedback
# -----------------------------------------------------------------------------
echo "=== [$(date +'%H:%M:%S')] STEP 4: Backfilling Candidate Feedback in '$REPORT_DIR' ==="
python3 -u "$PROJECT_ROOT/src/cli/backfill_feedback.py" \
  --model-name "$MODEL" \
  --vllm-url "http://127.0.0.1:$PORT/v1" \
  --dir "$REPORT_DIR"

stop_vllm_server
python3 "$PROJECT_ROOT/scripts/checks/token_stats.py"
echo "=== [$(date +'%Y-%m-%d %H:%M:%S')] Feedback Backfill Job Finished ==="
