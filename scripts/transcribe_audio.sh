#!/bin/bash
# -----------------------------------------------------------------------------
# Transcribe one recording into timestamped, speaker-labelled lines (docs/audio-transcribe.md).
#
# Usage (on a compute node with a GPU, with the audio venv from requirements-audio.txt active):
#   bash scripts/transcribe_audio.sh path/to/audio.m4a [--no-speakers]
#
# Writes <audio-stem>.transcript.txt next to the input. Speaker labels need HF_TOKEN.
# -----------------------------------------------------------------------------
set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

if [ $# -lt 1 ]; then
  echo "Usage: bash $0 path/to/audio.m4a [--no-speakers]" >&2
  exit 1
fi

if ! command -v ffmpeg >/dev/null 2>&1; then
  echo "[ERROR] ffmpeg is not on the PATH (try 'module load ffmpeg', see docs/audio-transcribe.md)." >&2
  exit 1
fi

exec python "$SCRIPT_DIR/../src/cli/transcribe_audio.py" "$@"
