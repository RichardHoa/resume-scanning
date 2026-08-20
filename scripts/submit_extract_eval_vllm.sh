#!/bin/bash
#SBATCH --job-name=extract_eval_vllm
#SBATCH --partition=researcher
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=32G
#SBATCH --gres=gpu:1
#SBATCH --time=03:00:00
#SBATCH --output=logging/slurm_extract_eval_%j.out
#SBATCH --error=logging/slurm_extract_eval_%j.err

# -----------------------------------------------------------------------------
# SLURM Batch Job Script for Combined Extraction & Evaluation with vLLM
#
# Resets workspace folders to simulate starting from a completely blank state,
# spins up a vLLM server instance, runs batch extraction (Step 1), and then
# runs batch evaluation (Step 2) using the active vLLM server.
# Log outputs are captured in dedicated log files under logs/.
# -----------------------------------------------------------------------------

RAW_PDF_DIR="$1"
RAW_MODEL="$2"
RAW_OUTPUT_DIR="$3"
RAW_EVAL_DIR="$4"
RAW_JOB_REQ="$5"
INITIAL_CWD="$(pwd)"

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

# -----------------------------------------------------------------------------
# STEP 1: Load Cluster Modules & Activate Conda Environment FIRST
# -----------------------------------------------------------------------------
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
echo "[$(date +'%H:%M:%S')] Active Python: $(which python3 2>/dev/null || echo 'python3 not found')"

# -----------------------------------------------------------------------------
# STEP 2: Source Configuration & vLLM Helpers (Python environment is active)
# -----------------------------------------------------------------------------
source "$SCRIPT_DIR/config.sh"
source "$SCRIPT_DIR/vllm_utils.sh"

if [ -z "$PROJECT_ROOT" ]; then
  echo "[CRITICAL ERROR] PROJECT_ROOT is not set after sourcing config.sh!" >&2
  exit 1
fi

# Force execution strictly from project repository root directory
cd "$PROJECT_ROOT" || exit 1

# Setup optimization & threading environment variables
setup_vllm_env

# Ensure critical evaluation dependencies (sentence-transformers, chromadb) are installed
if ! python3 -c "import sentence_transformers, chromadb" 2>/dev/null; then
  echo "[NOTICE] 'sentence-transformers' or 'chromadb' package missing in Conda environment 'resume_env'."
  echo "[NOTICE] Auto-installing missing evaluation dependencies via pip..."
  python3 -m pip install sentence-transformers chromadb 2>/dev/null || pip install sentence-transformers chromadb 2>/dev/null || true
fi

# -----------------------------------------------------------------------------
# STEP 3: Resolve Parameters & Validate Input Paths
# -----------------------------------------------------------------------------
# Resolve PDF input directory (Default: Vietnamese-dataset/CnB inside project root)
if [ -n "$RAW_PDF_DIR" ]; then
  if [[ "$RAW_PDF_DIR" = /* ]]; then
    PDF_DIR="$RAW_PDF_DIR"
  elif [ -d "$INITIAL_CWD/$RAW_PDF_DIR" ]; then
    PDF_DIR="$(cd "$INITIAL_CWD/$RAW_PDF_DIR" && pwd)"
  else
    PDF_DIR="$PROJECT_ROOT/$RAW_PDF_DIR"
  fi
else
  PDF_DIR="$PROJECT_ROOT/Vietnamese-dataset/CnB"
fi

# Target Model Name (Default: Qwen/Qwen3.5-35B-A3B)
MODEL="${RAW_MODEL:-Qwen/Qwen3.5-35B-A3B}"

# Target Extraction Output Directory (Default: output_jsons inside project root)
if [ -n "$RAW_OUTPUT_DIR" ]; then
  if [[ "$RAW_OUTPUT_DIR" = /* ]]; then
    OUTPUT_DIR="$RAW_OUTPUT_DIR"
  elif [ -d "$INITIAL_CWD/$RAW_OUTPUT_DIR" ]; then
    OUTPUT_DIR="$(cd "$INITIAL_CWD/$RAW_OUTPUT_DIR" && pwd)"
  else
    OUTPUT_DIR="$PROJECT_ROOT/$RAW_OUTPUT_DIR"
  fi
else
  OUTPUT_DIR="$PROJECT_ROOT/output_jsons"
fi

# Target Evaluation JSON Directory (Default: evaluation_json inside project root)
if [ -n "$RAW_EVAL_DIR" ]; then
  if [[ "$RAW_EVAL_DIR" = /* ]]; then
    EVAL_DIR="$RAW_EVAL_DIR"
  elif [ -d "$INITIAL_CWD/$RAW_EVAL_DIR" ]; then
    EVAL_DIR="$(cd "$INITIAL_CWD/$RAW_EVAL_DIR" && pwd)"
  else
    EVAL_DIR="$PROJECT_ROOT/$RAW_EVAL_DIR"
  fi
else
  EVAL_DIR="$PROJECT_ROOT/evaluation_json"
fi

# Job Requirements File (Default: hr-requirement.txt inside project root)
if [ -n "$RAW_JOB_REQ" ]; then
  if [[ "$RAW_JOB_REQ" = /* ]]; then
    JOB_REQ="$RAW_JOB_REQ"
  elif [ -f "$INITIAL_CWD/$RAW_JOB_REQ" ]; then
    JOB_REQ="$(cd "$(dirname "$INITIAL_CWD/$RAW_JOB_REQ")" && pwd)/$(basename "$RAW_JOB_REQ")"
  elif [ -f "$PROJECT_ROOT/$RAW_JOB_REQ" ]; then
    JOB_REQ="$(cd "$(dirname "$PROJECT_ROOT/$RAW_JOB_REQ")" && pwd)/$(basename "$RAW_JOB_REQ")"
  else
    JOB_REQ="$RAW_JOB_REQ"
  fi
else
  JOB_REQ="$PROJECT_ROOT/hr-requirement.txt"
fi

if [ ! -d "$PDF_DIR" ]; then
  echo "[ERROR] PDF directory '$PDF_DIR' does not exist." >&2
  exit 1
fi

if [ ! -f "$JOB_REQ" ]; then
  echo "[ERROR] Job requirement file '$JOB_REQ' does not exist." >&2
  exit 1
fi

# -----------------------------------------------------------------------------
# STEP 4: Reset Workspace to Blank State & Create Target Directories
# -----------------------------------------------------------------------------
echo "====================================================================="
echo "[$(date +'%Y-%m-%d %H:%M:%S')] STEP 4: Resetting workspace to blank state..."
echo "Clearing extraction markdowns, output JSONs, evaluation JSONs, and RAG vector storage."
echo "====================================================================="

mkdir -p "$PROJECT_ROOT/logs" \
         "$PROJECT_ROOT/logging" \
         "$PROJECT_ROOT/pdfs" \
         "$PROJECT_ROOT/extraction_markdown" \
         "$PROJECT_ROOT/eval_results" \
         "$PROJECT_ROOT/broken-json" \
         "$PROJECT_ROOT/approved_jsons" \
         "$PROJECT_ROOT/rag" \
         "$OUTPUT_DIR" \
         "$EVAL_DIR"

rm -rf "${OUTPUT_DIR:?}"/*
rm -rf "${EVAL_DIR:?}"/*
rm -rf "$PROJECT_ROOT/extraction_markdown"/*
rm -rf "$PROJECT_ROOT/eval_results"/*
rm -rf "$PROJECT_ROOT/broken-json"/*
rm -rf "$PROJECT_ROOT/approved_jsons"/*
rm -rf "$PROJECT_ROOT/rag"/*
rm -f "$PROJECT_ROOT/hr_rag.txt"

# -----------------------------------------------------------------------------
# STEP 5: Logging Setup & Server Startup
# -----------------------------------------------------------------------------
JOB_LOG="$PROJECT_ROOT/logs/extract_eval_job.log"
EXTRACT_LOG="$PROJECT_ROOT/logs/extract_step1.log"
EVAL_LOG="$PROJECT_ROOT/logs/eval_step2.log"
VLLM_LOG="$PROJECT_ROOT/logs/vllm_extract_eval.log"

echo "[$(date +'%Y-%m-%d %H:%M:%S')] Combined Extract & Eval Job Started" > "$JOB_LOG"

echo "=====================================================================" | tee -a "$JOB_LOG"
echo "[$(date +'%Y-%m-%d %H:%M:%S')] STEP 5: Inspecting GPU hardware allocation..." | tee -a "$JOB_LOG"
nvidia-smi 2>/dev/null | tee -a "$JOB_LOG" || echo "nvidia-smi not available" | tee -a "$JOB_LOG"
echo "=====================================================================" | tee -a "$JOB_LOG"

PORT=$(find_free_port)

echo "[$(date +'%H:%M:%S')] Project Root: $PROJECT_ROOT" | tee -a "$JOB_LOG"
echo "[$(date +'%H:%M:%S')] Target PDF Directory: $PDF_DIR" | tee -a "$JOB_LOG"
echo "[$(date +'%H:%M:%S')] Target Output Directory: $OUTPUT_DIR" | tee -a "$JOB_LOG"
echo "[$(date +'%H:%M:%S')] Target Evaluation Directory: $EVAL_DIR" | tee -a "$JOB_LOG"
echo "[$(date +'%H:%M:%S')] Target Model: $MODEL" | tee -a "$JOB_LOG"
echo "[$(date +'%H:%M:%S')] Target Job Requirement File: $JOB_REQ" | tee -a "$JOB_LOG"
echo "[$(date +'%H:%M:%S')] Allocated Server Port: $PORT" | tee -a "$JOB_LOG"
echo "[$(date +'%H:%M:%S')] Server Log File: $VLLM_LOG" | tee -a "$JOB_LOG"
echo "[$(date +'%H:%M:%S')] Extractor Log File: $EXTRACT_LOG" | tee -a "$JOB_LOG"
echo "[$(date +'%H:%M:%S')] Evaluator Log File: $EVAL_LOG" | tee -a "$JOB_LOG"
echo "[$(date +'%H:%M:%S')] HF Cache Path: ${HF_HOME:-default}" | tee -a "$JOB_LOG"

start_vllm_server "$MODEL" "$PORT" "$VLLM_LOG" || exit 1

# -----------------------------------------------------------------------------
# STEP 6: Execute Step 1 - Batch Extraction
# -----------------------------------------------------------------------------
echo "=====================================================================" | tee -a "$JOB_LOG"
echo "[$(date +'%Y-%m-%d %H:%M:%S')] === [Step 1/2] Starting Batch Extraction (vLLM) ===" | tee -a "$JOB_LOG"
echo "Processing PDFs from '$PDF_DIR' -> JSONs to '$OUTPUT_DIR' using model '$MODEL'" | tee -a "$JOB_LOG"
echo "Detailed extraction log: $EXTRACT_LOG" | tee -a "$JOB_LOG"
echo "=====================================================================" | tee -a "$JOB_LOG"

python3 -u "$PROJECT_ROOT/src/step_1_extractor.py" \
  --dir "$PDF_DIR" \
  --output "$OUTPUT_DIR" \
  --model-name "$MODEL" \
  --backend vllm \
  --vllm-url "http://127.0.0.1:$PORT/v1" 2>&1 | tee "$EXTRACT_LOG" | tee -a "$JOB_LOG"

EXTRACT_STATUS=${PIPESTATUS[0]}
if [ "$EXTRACT_STATUS" -ne 0 ]; then
  echo "[CRITICAL ERROR] Batch extraction failed with exit code $EXTRACT_STATUS!" | tee -a "$JOB_LOG" >&2
  stop_vllm_server
  exit "$EXTRACT_STATUS"
fi

# -----------------------------------------------------------------------------
# STEP 7: Execute Step 2 - High-Precision Evaluation
# -----------------------------------------------------------------------------
echo "=====================================================================" | tee -a "$JOB_LOG"
echo "[$(date +'%Y-%m-%d %H:%M:%S')] === [Step 2/2] Starting High-Precision Batch Evaluation (vLLM) ===" | tee -a "$JOB_LOG"
echo "Evaluating JSONs from '$OUTPUT_DIR' -> Results to '$EVAL_DIR' using model '$MODEL'" | tee -a "$JOB_LOG"
echo "Detailed evaluation log: $EVAL_LOG" | tee -a "$JOB_LOG"
echo "=====================================================================" | tee -a "$JOB_LOG"

python3 -u "$PROJECT_ROOT/src/step_2_evaluate.py" \
  --model-name "$MODEL" \
  --backend vllm \
  --vllm-url "http://127.0.0.1:$PORT/v1" \
  --dir "$OUTPUT_DIR" \
  --job-req "$JOB_REQ" \
  --output "$EVAL_DIR" \
  --workers 6 2>&1 | tee "$EVAL_LOG" | tee -a "$JOB_LOG"

EVAL_STATUS=${PIPESTATUS[0]}
if [ "$EVAL_STATUS" -ne 0 ]; then
  echo "[CRITICAL ERROR] Batch evaluation failed with exit code $EVAL_STATUS!" | tee -a "$JOB_LOG" >&2
  stop_vllm_server
  exit "$EVAL_STATUS"
fi

stop_vllm_server
echo "=====================================================================" | tee -a "$JOB_LOG"
echo "=== [$(date +'%Y-%m-%d %H:%M:%S')] Combined Extract & Eval Job Finished Successfully ===" | tee -a "$JOB_LOG"
echo "=====================================================================" | tee -a "$JOB_LOG"
