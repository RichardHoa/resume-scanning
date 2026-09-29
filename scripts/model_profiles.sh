#!/bin/bash
# -----------------------------------------------------------------------------
# Per-Model Profiles for vLLM-backed Jobs
#
# Sourced by SLURM scripts. `load_model_profile <key>` sets:
#   MODEL                      HuggingFace model ID served by vLLM
#   MODEL_KEY                  Short key (also names the bias-result/<key>/ folder)
#   CONCURRENCY                Concurrent evaluation workers
#   MAX_EVAL_PER_SHUFFLE_KIND  Cap on evaluations per shuffle kind (bias suite)
#   VLLM_ENABLE_THINKING       1 = let the model think (chat_template_kwargs), 0 = off
#   VLLM_EXTRA_ARGS            Bash array of extra `vllm serve` flags
#
# To add a model: add a case branch below and its key to MODEL_PROFILE_KEYS.
# -----------------------------------------------------------------------------

DEFAULT_MODEL_KEY="qwen3.5-35b-a3b"
MODEL_PROFILE_KEYS="qwen3.5-35b-a3b qwen2.5-32b gemma4-26b-a4b glm4.7-flash"

load_model_profile() {
  local key="${1:-$DEFAULT_MODEL_KEY}"

  VLLM_ENABLE_THINKING=0
  VLLM_EXTRA_ARGS=()

  case "$key" in
    qwen3.5-35b-a3b)
      MODEL="Qwen/Qwen3.5-35B-A3B"
      CONCURRENCY=100
      MAX_EVAL_PER_SHUFFLE_KIND=1000
      ;;
    qwen2.5-32b)
      # Dense 32B: every parameter is active per token, so keep concurrency low
      MODEL="Qwen/Qwen2.5-32B-Instruct"
      CONCURRENCY=15
      MAX_EVAL_PER_SHUFFLE_KIND=300
      ;;
    gemma4-26b-a4b)
      # Multimodal checkpoint: disable image/audio inputs to skip encoder memory reservation
      MODEL="google/gemma-4-26B-A4B-it"
      CONCURRENCY=100
      MAX_EVAL_PER_SHUFFLE_KIND=1000
      VLLM_EXTRA_ARGS=(
        --limit-mm-per-prompt.image 0
        --limit-mm-per-prompt.audio 0
        --reasoning-parser gemma4
      )
      ;;
    glm4.7-flash)
      # Thinks by default; VLLM_ENABLE_THINKING=0 turns it off per request
      MODEL="zai-org/GLM-4.7-Flash"
      CONCURRENCY=100
      MAX_EVAL_PER_SHUFFLE_KIND=1000
      VLLM_EXTRA_ARGS=(
        --reasoning-parser glm45
      )
      ;;
    *)
      echo "[ERROR] Unknown model key '$key'. Valid keys: $MODEL_PROFILE_KEYS" >&2
      return 1
      ;;
  esac

  MODEL_KEY="$key"
  export MODEL MODEL_KEY CONCURRENCY MAX_EVAL_PER_SHUFFLE_KIND VLLM_ENABLE_THINKING
  return 0
}
