#!/bin/bash
#SBATCH --job-name=nugioichung_vllm
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=32G
#SBATCH --partition=student9696
#SBATCH --gres=gpu:nvidia_rtx_pro_6000_blackwell_server_edition_4g.96gb:1
#SBATCH --time=4:00:00
#SBATCH --output=logging/slurm_nugioichung_%j.out
#SBATCH --error=logging/slurm_nugioichung_%j.err

# -----------------------------------------------------------------------------
# Nữ Giới Chung: transcribe one scanned Issue PDF (src/nugioichung/cli.py)
#
# A layout pass splits each page into Regions, a transcription pass reads each Region from the 300 dpi scan, and
# the code joins them into the Issue's Markdown (src/nugioichung/docs/adr/0001-two-pass-vlm-no-ocr-draft.md).
#
# Usage:
#   sbatch scripts/nugioichung/submit.sh <issue.pdf> [--model <key>] [cli.py flags]
#   sbatch scripts/nugioichung/submit.sh vsc-project/NuGioiChung/So1_Feb1_1918.pdf --pages 1,2,6,13   # a trial
#   sbatch scripts/nugioichung/submit.sh <issue.pdf> --run-dir vsc-project/NuGioiChung/runs/<issue>/<time>
#                                                                       # finish a run's missing requests
#   bash scripts/nugioichung/submit.sh <issue.pdf> --dry-run           # on the login node: token counts, no GPU
#
# The model profile is served with vision on for this job only (profiles serve text only), and with at most
# NUGIOICHUNG_CONCURRENCY requests in flight (scripts/lib/vision_job.sh).
# -----------------------------------------------------------------------------

NUGIOICHUNG_CONCURRENCY=40    # the default profile's
MAX_IMAGES_PER_PROMPT=1    # a layout request sends its page; a transcription request its Region's crop

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

source "$LIB_DIR/vision_job.sh"
run_vision_job nugioichung "Nữ Giới Chung" src.nugioichung.cli "$NUGIOICHUNG_CONCURRENCY" "$MAX_IMAGES_PER_PROMPT" "$@"
exit $?
