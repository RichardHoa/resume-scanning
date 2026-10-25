#!/bin/bash
# ---------------------------------------------------------------------------
# Centralized Shell Configuration for Resume Scanning Engine
# ---------------------------------------------------------------------------

# Resolve repository root directory (this file is scripts/lib/config.sh)
_CONFIG_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_ROOT_DIR="$(cd "$_CONFIG_DIR/../.." && pwd)"

# Ensure commands execute from project root directory
cd "$_ROOT_DIR" || exit 1

# Export project root, scripts directory, and PYTHONPATH for all child processes
export PROJECT_ROOT="$_ROOT_DIR"
export SCRIPT_DIR="$_ROOT_DIR/scripts"
if [ -n "$PYTHONPATH" ]; then
  export PYTHONPATH="$_ROOT_DIR:$PYTHONPATH"
else
  export PYTHONPATH="$_ROOT_DIR"
fi

# Dynamically fetch VLLM_MAX_MODEL_LEN from Python src.core.config (Single Source of Truth)
VLLM_MAX_MODEL_LEN=$(python3 -c "import sys; sys.path.insert(0, '$_ROOT_DIR'); from src.core.config import VLLM_MAX_MODEL_LEN; print(VLLM_MAX_MODEL_LEN)" 2>/dev/null || echo 32768)
# Note: Do not export VLLM_MAX_MODEL_LEN as vLLM 0.27+ warns about unrecognized VLLM_* env vars

# Evaluation never builds or changes the HR RAG: HR sets it on the website's RAG page before a run. Call this
# before starting the vLLM server, so a run with no HR RAG stops before spending GPU time
require_hr_rag() {
  if python3 -c "import sys; from src.providers.rag_engine import stored_criteria_count; sys.exit(0 if stored_criteria_count() > 0 else 1)"; then
    return 0
  fi
  echo "[ERROR] No HR RAG is stored in '$PROJECT_ROOT/rag'. Set the HR requirements on the website's RAG page (decompose them and review the Criteria) before running an evaluation." >&2
  return 1
}

# Run folders (docs/adr/0010-run-folders.md): every output of one pipeline job lives in runs/batch-cnb, or
# runs/batch-tech for the Tech resume set. Exports RUN_DIR (which src/core/config.py builds every path from) and
# the folder's subfolders. Call with the dataset, "CnB" or "Tech"
use_pipeline_run_dir() {
  _use_run_dir batch "$1"
}

# A consistency check's run folder: runs/<check>-consistency-cnb, or -tech for the Tech resume set. Exports the same
# variables as use_pipeline_run_dir. Call with the check, "extractor" or "evaluator", and the dataset
use_consistency_run_dir() {
  _use_run_dir "$1-consistency" "$2"
}

# The Bias Check's run folder, runs/bias-cnb: it only ever tests one CnB resume
use_bias_run_dir() {
  _use_run_dir bias CnB
}

# Exports RUN_DIR as runs/<prefix>-cnb or runs/<prefix>-tech, and its subfolders
_use_run_dir() {
  if [ "$2" = "Tech" ]; then
    export RUN_DIR="$PROJECT_ROOT/runs/$1-tech"
  else
    export RUN_DIR="$PROJECT_ROOT/runs/$1-cnb"
  fi
  RUN_LOGS_DIR="$RUN_DIR/logs"
  PROMPT_LOGS_DIR="$RUN_DIR/prompt_logs"
  EXTRACTION_JSON_DIR="$RUN_DIR/extraction_json"
  EVALUATION_JSON_DIR="$RUN_DIR/evaluation_json"
}

# Refuses any folder but the pipeline and consistency run folders, so a wrong or empty RUN_DIR never reaches rm -rf
_require_pipeline_run_dir() {
  case "$RUN_DIR" in
    "$PROJECT_ROOT/runs/batch-cnb"|"$PROJECT_ROOT/runs/batch-tech") return 0 ;;
    "$PROJECT_ROOT/runs/extractor-consistency-cnb"|"$PROJECT_ROOT/runs/extractor-consistency-tech") return 0 ;;
    "$PROJECT_ROOT/runs/evaluator-consistency-cnb"|"$PROJECT_ROOT/runs/evaluator-consistency-tech") return 0 ;;
    "$PROJECT_ROOT/runs/bias-cnb") return 0 ;;
  esac
  echo "[CRITICAL ERROR] Refusing to wipe '$RUN_DIR': not a runs/batch-*, runs/*-consistency-* or runs/bias-cnb folder under $PROJECT_ROOT." >&2
  return 1
}

# Empties the whole run folder, so it holds exactly one pass
reset_run_dir() {
  _require_pipeline_run_dir || return 1
  rm -rf "${RUN_DIR:?}"
  mkdir -p "$RUN_LOGS_DIR" "$PROMPT_LOGS_DIR" "$EXTRACTION_JSON_DIR" "$EVALUATION_JSON_DIR"
}

# Empties only the run folder's evaluations (their JSONs, prompt logs, token usage and the eval logs), keeping the
# extractions they are made from
reset_run_dir_evaluations() {
  _require_pipeline_run_dir || return 1
  mkdir -p "$RUN_LOGS_DIR" "$PROMPT_LOGS_DIR" "$EXTRACTION_JSON_DIR" "$EVALUATION_JSON_DIR"
  python3 -m src.core.run_files --clear-evaluations || return 1
  rm -f "$RUN_LOGS_DIR/eval.log" "$RUN_LOGS_DIR/eval_job.log" "$RUN_LOGS_DIR/vllm_eval.log"
}
