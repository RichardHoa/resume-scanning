#!/bin/bash
# ---------------------------------------------------------------------------
# Centralized Shell Configuration for Resume Scanning Engine
# ---------------------------------------------------------------------------

# Resolve repository root directory
_CONFIG_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
_ROOT_DIR="$(cd "$_CONFIG_DIR/.." && pwd)"

# Ensure commands execute from project root directory
cd "$_ROOT_DIR" || exit 1

# Export project root, script directory, and PYTHONPATH for all child processes
export PROJECT_ROOT="$_ROOT_DIR"
export SCRIPT_DIR="$_CONFIG_DIR"
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
