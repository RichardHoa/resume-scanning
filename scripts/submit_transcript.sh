#!/bin/bash
#SBATCH --job-name=transcript_omni
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=32G
#SBATCH --partition=student9696
#SBATCH --gres=gpu:nvidia_rtx_pro_6000_blackwell_server_edition_4g.96gb:1
#SBATCH --time=4:00:00
#SBATCH --output=logging/slurm_transcript_%j.out
#SBATCH --error=logging/slurm_transcript_%j.err

# -----------------------------------------------------------------------------
# Transcript of vsc-project/audio-transcribe/1.m4a, reviewed by Qwen3-Omni (docs/audio-transcribe.md)
#
#   1. Qwen3-ASR transcribes the recording with its glossary (src/cli/transcribe_audio.py, in the audio venv),
#      writing 1.transcript.txt. An existing 1.transcript.txt is first renamed to 1.transcript.<time>.txt.
#   2. Qwen3-Omni, served by vLLM in resume_env, hears each line's clip and fixes misheard words
#      (src/cli/review_transcript.py), writing 1.reviewed.transcript.txt and 1.review.jsonl.
#
# Usage (no flags; HF_TOKEN must be set in the shell you submit from):
#   sbatch scripts/submit_transcript.sh
# -----------------------------------------------------------------------------

REVIEW_MODEL="Qwen/Qwen3-Omni-30B-A3B-Instruct"
REVIEW_CONCURRENCY=16
AUDIO_VENV="$HOME/venvs/audio-transcribe"
AUDIO_REL="vsc-project/audio-transcribe/1.m4a"
CONTEXT_REL="vsc-project/audio-transcribe/1.context.txt"

INITIAL_CWD="$(pwd)"

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

if [ -z "$PROJECT_ROOT" ]; then
  echo "[CRITICAL ERROR] PROJECT_ROOT is not set after sourcing config.sh!" >&2
  exit 1
fi

cd "$PROJECT_ROOT" || exit 1
AUDIO="$PROJECT_ROOT/$AUDIO_REL"
CONTEXT="$PROJECT_ROOT/$CONTEXT_REL"
TRANSCRIPT="${AUDIO%.*}.transcript.txt"

# Check everything step 1 needs before renaming the old transcript
for f in "$AUDIO" "$CONTEXT" "$AUDIO_VENV/bin/activate"; do
  if [ ! -f "$f" ]; then
    echo "[ERROR] Not found: $f (see docs/audio-transcribe.md)" >&2
    exit 1
  fi
done
if [ -z "$HF_TOKEN" ]; then
  echo "[ERROR] HF_TOKEN is not set: speaker labels need it. Set it in the shell you run sbatch from." >&2
  exit 1
fi

# Review model profile: audio in, no images or video, text out
MODEL="$REVIEW_MODEL"
VLLM_EXTRA_ARGS=(
  --limit-mm-per-prompt.audio 1
  --limit-mm-per-prompt.image 0
  --limit-mm-per-prompt.video 0
)
CONCURRENCY=$REVIEW_CONCURRENCY
VLLM_ENABLE_THINKING=0
VLLM_REASONING_STRENGTH=""
export MODEL CONCURRENCY VLLM_ENABLE_THINKING VLLM_REASONING_STRENGTH

setup_vllm_env
mkdir -p "$PROJECT_ROOT/logs" "$PROJECT_ROOT/logging"

echo "[$(date +'%H:%M:%S')] STEP 1: Loading system environment modules..."
module load miniconda3 2>/dev/null || true
module load cuda 2>/dev/null || module load cuda13.0 2>/dev/null || true

echo "====================================================================="
nvidia-smi 2>/dev/null || echo "nvidia-smi not available"
echo "====================================================================="

echo "[$(date +'%H:%M:%S')] STEP 2: Transcribing $AUDIO_REL with Qwen3-ASR (audio venv)..."
if [ -f "$TRANSCRIPT" ]; then
  BACKUP="${TRANSCRIPT%.txt}.$(date +'%Y%m%d-%H%M%S').txt"
  mv "$TRANSCRIPT" "$BACKUP"
  echo "[$(date +'%H:%M:%S')] Renamed the existing transcript to $BACKUP"
fi
source "$AUDIO_VENV/bin/activate"
python -u "$PROJECT_ROOT/src/cli/transcribe_audio.py" "$AUDIO" --context "$CONTEXT"
STATUS=$?
deactivate
if [ $STATUS -ne 0 ] || [ ! -f "$TRANSCRIPT" ]; then
  echo "[ERROR] Transcription failed (exit $STATUS); no review." >&2
  exit 1
fi

if ! command -v conda &>/dev/null; then
  for c_path in /compute_home/$USER/miniconda3/bin/conda /compute_home/$USER/anaconda3/bin/conda /opt/miniconda3/bin/conda /opt/anaconda3/bin/conda; do
    if [ -x "$c_path" ]; then
      export PATH="$(dirname "$c_path"):$PATH"
      break
    fi
  done
fi

echo "[$(date +'%H:%M:%S')] STEP 3: Activating Conda environment 'resume_env'..."
eval "$(conda shell.bash hook 2>/dev/null)" || true
source activate resume_env 2>/dev/null || conda activate resume_env 2>/dev/null || true
echo "[$(date +'%H:%M:%S')] Step 3 complete. Active Python: $(which python3 2>/dev/null || echo 'python3 not found')"

PORT=$(find_free_port)
echo "[$(date +'%H:%M:%S')] Review Model: $MODEL (concurrency $CONCURRENCY, audio on)"
echo "[$(date +'%H:%M:%S')] Allocated Server Port: $PORT"

start_vllm_server "$MODEL" "$PORT" "$PROJECT_ROOT/logs/vllm_transcript.log" || exit 1

echo "=== vLLM Server Ready! STEP 4: Reviewing $TRANSCRIPT ==="
python3 -u "$PROJECT_ROOT/src/cli/review_transcript.py" "$AUDIO" "$TRANSCRIPT" \
  --context "$CONTEXT" \
  --model-name "$MODEL" \
  --vllm-url "http://127.0.0.1:$PORT/v1"
STATUS=$?

stop_vllm_server
echo "=== [$(date +'%Y-%m-%d %H:%M:%S')] Transcript Review Finished ==="
exit $STATUS
