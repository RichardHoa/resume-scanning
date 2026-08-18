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
VLLM_MAX_MODEL_LEN=$(python3 -c "import sys; sys.path.insert(0, '$_ROOT_DIR'); from src.core.config import VLLM_MAX_MODEL_LEN; print(VLLM_MAX_MODEL_LEN)" 2>/dev/null || echo 20000)
export VLLM_MAX_MODEL_LEN
