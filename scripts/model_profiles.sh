#!/bin/bash
# -----------------------------------------------------------------------------
# Per-Model Profiles for vLLM-backed Jobs
#
# Sourced by SLURM scripts. `load_model_profile <key>` sets:
#   MODEL                      HuggingFace model ID served by vLLM
#   MODEL_KEY                  Short key (also names the bias-result/<key>/ folder)
#   CONCURRENCY                Max requests in flight to vLLM from one process, shared by every caller
#                              (no default: every branch must set it)
#   MAX_EVAL_PER_SHUFFLE_KIND  Cap on evaluations per shuffle kind (bias suite, default 200)
#   VLLM_ENABLE_THINKING       1 = let the model think (chat_template_kwargs), 0 = off
#   VLLM_REASONING_STRENGTH    System-prompt effort level for models that always reason ("" = unset)
#   VLLM_EXTRA_ARGS            Bash array of extra `vllm serve` flags
#   VLLM_VISION                1 = the checkpoint can see images (default 0). Profiles still serve text only;
#                              a job that needs images turns vision on with `serve_vision_on`
#
# To add a model: add a case branch below and its key to MODEL_PROFILE_KEYS.
# -----------------------------------------------------------------------------

DEFAULT_MODEL_KEY="sea-lion-v4.5-27b"
MODEL_PROFILE_KEYS="qwen3.5-35b-a3b qwen2.5-32b gemma4-26b-a4b glm4.7-flash qwen3.6-35b-a3b qwen3.8-27b gemma4-31b muse-glimmer-30b sea-lion-v4.5-27b"

load_model_profile() {
  local key="${1:-$DEFAULT_MODEL_KEY}"

  # Defaults; a branch only sets what differs. CONCURRENCY has none: it is model-specific
  CONCURRENCY=""
  MAX_EVAL_PER_SHUFFLE_KIND=200
  VLLM_ENABLE_THINKING=0
  VLLM_REASONING_STRENGTH=""
  VLLM_EXTRA_ARGS=()
  VLLM_VISION=0

  case "$key" in
    qwen3.5-35b-a3b)
      MODEL="Qwen/Qwen3.5-35B-A3B"
      VLLM_VISION=1
      CONCURRENCY=100
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
      VLLM_VISION=1
      CONCURRENCY=100
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
      VLLM_EXTRA_ARGS=(
        --reasoning-parser glm45
      )
      ;;
    qwen3.6-35b-a3b)
      # Vision-language checkpoint: --language-model-only skips the vision encoder
      MODEL="Qwen/Qwen3.6-35B-A3B"
      VLLM_VISION=1
      CONCURRENCY=100
      VLLM_EXTRA_ARGS=(
        --language-model-only
        --reasoning-parser qwen3
      )
      ;;
    qwen3.8-27b)
      # Dense 27B vision-language checkpoint; thinks by default, VLLM_ENABLE_THINKING=0 turns it off
      MODEL="Qwen/Qwen3.8-27B"
      VLLM_VISION=1
      CONCURRENCY=80
      VLLM_EXTRA_ARGS=(
        --language-model-only
        --reasoning-parser qwen3
      )
      ;;
    gemma4-31b)
      # Dense 31B multimodal checkpoint: disable image/audio inputs to skip encoder memory reservation
      MODEL="google/gemma-4-31B-it"
      VLLM_VISION=1
      CONCURRENCY=20
      VLLM_EXTRA_ARGS=(
        --limit-mm-per-prompt.image 0
        --limit-mm-per-prompt.audio 0
        --reasoning-parser gemma4
      )
      ;;
    muse-glimmer-30b)
      # Dense 30B vision-language checkpoint (vLLM >= 0.28). Reasoning cannot be turned off, only set to
      # low/medium/high/xhigh; the reasoning and tool parsers share the channel framing, so run both
      MODEL="meta-models/Muse-Glimmer-30B"
      VLLM_VISION=1
      CONCURRENCY=200
      VLLM_REASONING_STRENGTH="low"
      VLLM_EXTRA_ARGS=(
        --limit-mm-per-prompt.image 0
        --reasoning-parser muse_glimmer
        --enable-auto-tool-choice
        --tool-call-parser muse_glimmer
      )
      ;;
    sea-lion-v4.5-27b)
      # Dense 27B Qwen3.6 fine-tune (vision-language): --language-model-only skips the vision encoder
      MODEL="aisingapore/Qwen-SEA-LION-v4.5-27B-IT"
      VLLM_VISION=1
      CONCURRENCY=40
      VLLM_EXTRA_ARGS=(
        --language-model-only
        --reasoning-parser qwen3
      )
      ;;
    *)
      echo "[ERROR] Unknown model key '$key'. Valid keys: $MODEL_PROFILE_KEYS" >&2
      return 1
      ;;
  esac

  if [[ -z "$CONCURRENCY" ]]; then
    echo "[ERROR] Model profile '$key' does not set CONCURRENCY" >&2
    return 1
  fi

  MODEL_KEY="$key"
  export MODEL MODEL_KEY CONCURRENCY MAX_EVAL_PER_SHUFFLE_KIND VLLM_ENABLE_THINKING VLLM_REASONING_STRENGTH VLLM_VISION
  return 0
}

# `resolve_model_arg <arg>`: a profile key, or nothing for the default profile, loads that profile;
# anything else is taken as a raw HuggingFace model ID served without a profile.
resolve_model_arg() {
  local arg="$1"
  if [[ -z "$arg" || " $MODEL_PROFILE_KEYS " == *" $arg "* ]]; then
    load_model_profile "$arg"
    return $?
  fi
  MODEL="$arg"
  VLLM_VISION=0  # no profile says the model can see images
  export MODEL VLLM_VISION
  return 0
}

# Combined Extraction shows at most this many page images per resume (COMBINED_MAX_PAGES in src/core/config.py)
COMBINED_MAX_PAGES=6

# `require_vision_profile`: fails, naming the profiles that can see images, unless the loaded profile can
require_vision_profile() {
  if [[ "${VLLM_VISION:-0}" == "1" ]]; then
    return 0
  fi
  local vision_keys=() key
  for key in $MODEL_PROFILE_KEYS; do
    ( load_model_profile "$key" >/dev/null 2>&1 && [[ "$VLLM_VISION" == "1" ]] ) && vision_keys+=("$key")
  done
  echo "[ERROR] '$MODEL' cannot see images, so it cannot run Combined Extraction (--combined)." >&2
  echo "[ERROR] Profiles that can: ${vision_keys[*]}" >&2
  return 1
}

# `serve_vision_on <max_images>`: drops the profile's text-only and image-limit flags from VLLM_EXTRA_ARGS, then
# allows up to <max_images> images (and no video) per prompt
serve_vision_on() {
  local max_images="$1" arg skip_next=0
  local serve_args=()
  for arg in "${VLLM_EXTRA_ARGS[@]}"; do
    if [ $skip_next -eq 1 ]; then
      skip_next=0
      continue
    fi
    case "$arg" in
      --language-model-only) ;;
      --limit-mm-per-prompt*=*) ;;
      --limit-mm-per-prompt*) skip_next=1 ;;
      *) serve_args+=("$arg") ;;
    esac
  done
  VLLM_EXTRA_ARGS=("${serve_args[@]}" --limit-mm-per-prompt.image "$max_images" --limit-mm-per-prompt.video 0)
}
