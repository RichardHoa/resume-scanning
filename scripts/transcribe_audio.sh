#!/bin/bash
# -----------------------------------------------------------------------------
# Transcribe one recording into timestamped, speaker-labelled lines (docs/audio-transcribe.md).
#
# Usage (on a compute node with a GPU, with the audio venv from requirements-audio.txt active):
#   bash scripts/transcribe_audio.sh path/to/audio.m4a [--no-speakers] [--context FILE | --phowhisper]
#
# Writes <audio-stem>.transcript.txt next to the input (<audio-stem>.phowhisper.transcript.txt with --phowhisper,
# which transcribes with vinai/PhoWhisper-large instead of Qwen3-ASR). Speaker labels need HF_TOKEN.
# -----------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ $# -lt 1 ]; then
  echo "Usage: bash $0 path/to/audio.m4a [--no-speakers] [--context FILE | --phowhisper]" >&2
  exit 1
fi

exec python "$SCRIPT_DIR/../src/cli/transcribe_audio.py" "$@"
