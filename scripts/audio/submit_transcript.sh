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
# Transcript of vsc-project/audio-transcribe/1.m4a, fused and checked by Qwen3-Omni (docs/audio-transcribe.md)
#
#   1. Qwen3-ASR (with the glossary) and PhoWhisper transcribe the same Segments (src/cli/transcribe_audio.py
#      --with-phowhisper, in the audio venv), writing 1.transcript.txt and 1.phowhisper.transcript.txt. Existing
#      ones are first renamed to <name>.<time>.txt.
#   2. Qwen3-Omni, served by vLLM in resume_env, hears each line's clip and writes what it hears from the two drafts
#      (src/cli/review_transcript.py), writing 1.reviewed.transcript.txt and 1.review.jsonl.
#   3. On the same server, it fixes misheard names over the whole interview (src/cli/fix_names.py), writing
#      1.final.transcript.txt and 1.names.jsonl.
#   4. If the reference grouth_truth.txt exists, the four transcripts are scored against it
#      (src/cli/score_transcript.py) into the job log.
#
# Usage (no flags; HF_TOKEN must be set in the shell you submit from):
#   sbatch scripts/audio/submit_transcript.sh
# -----------------------------------------------------------------------------

REVIEW_MODEL="Qwen/Qwen3-Omni-30B-A3B-Instruct"
REVIEW_CONCURRENCY=16
AUDIO_VENV="$HOME/venvs/audio-transcribe"
AUDIO_REL="vsc-project/audio-transcribe/1.m4a"
CONTEXT_REL="vsc-project/audio-transcribe/1.context.txt"
REFERENCE_REL="vsc-project/audio-transcribe/grouth_truth.txt"

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
source "$LIB_DIR/config.sh"
source "$LIB_DIR/vllm_utils.sh"

if [ -z "$PROJECT_ROOT" ]; then
  echo "[CRITICAL ERROR] PROJECT_ROOT is not set after sourcing config.sh!" >&2
  exit 1
fi

cd "$PROJECT_ROOT" || exit 1
AUDIO="$PROJECT_ROOT/$AUDIO_REL"
CONTEXT="$PROJECT_ROOT/$CONTEXT_REL"
REFERENCE="$PROJECT_ROOT/$REFERENCE_REL"
TRANSCRIPT="${AUDIO%.*}.transcript.txt"
SECOND="${AUDIO%.*}.phowhisper.transcript.txt"
REVIEWED="${AUDIO%.*}.reviewed.transcript.txt"
FINAL="${AUDIO%.*}.final.transcript.txt"

# Check everything step 1 needs before renaming the old transcripts
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

echo "[$(date +'%H:%M:%S')] STEP 2: Transcribing $AUDIO_REL with Qwen3-ASR and PhoWhisper (audio venv)..."
STAMP="$(date +'%Y%m%d-%H%M%S')"
for f in "$TRANSCRIPT" "$SECOND"; do
  if [ -f "$f" ]; then
    mv "$f" "${f%.txt}.$STAMP.txt"
    echo "[$(date +'%H:%M:%S')] Renamed the existing $(basename "$f") to $(basename "${f%.txt}.$STAMP.txt")"
  fi
done
source "$AUDIO_VENV/bin/activate"
python -u "$PROJECT_ROOT/src/cli/transcribe_audio.py" "$AUDIO" --context "$CONTEXT" --with-phowhisper
STATUS=$?
deactivate
if [ $STATUS -ne 0 ] || [ ! -f "$TRANSCRIPT" ] || [ ! -f "$SECOND" ]; then
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
  --second "$SECOND" \
  --context "$CONTEXT" \
  --model-name "$MODEL" \
  --vllm-url "http://127.0.0.1:$PORT/v1"
STATUS=$?

if [ $STATUS -eq 0 ]; then
  echo "=== STEP 5: Fixing names in $REVIEWED ==="
  python3 -u "$PROJECT_ROOT/src/cli/fix_names.py" "$REVIEWED" \
    --context "$CONTEXT" \
    --model-name "$MODEL" \
    --vllm-url "http://127.0.0.1:$PORT/v1"
  STATUS=$?
fi

stop_vllm_server

if [ $STATUS -eq 0 ] && [ -f "$REFERENCE" ]; then
  echo "=== STEP 6: Scoring against $REFERENCE_REL ==="
  python3 -u "$PROJECT_ROOT/src/cli/score_transcript.py" "$REFERENCE" \
    "$TRANSCRIPT" "$SECOND" "$REVIEWED" "$FINAL" --context "$CONTEXT"
fi
echo "=== [$(date +'%Y-%m-%d %H:%M:%S')] Transcript Review Finished ==="
exit $STATUS
