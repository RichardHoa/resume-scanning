#!/bin/bash
#SBATCH --job-name=khotangtucngu_vllm
#SBATCH --nodes=1
#SBATCH --ntasks=1
#SBATCH --cpus-per-task=16
#SBATCH --mem=32G
#SBATCH --partition=student9696
#SBATCH --gres=gpu:nvidia_rtx_pro_6000_blackwell_server_edition_4g.96gb:1
#SBATCH --time=4:00:00
#SBATCH --output=logging/slurm_khotangtucngu_%j.out
#SBATCH --error=logging/slurm_khotangtucngu_%j.err

# -----------------------------------------------------------------------------
# Kho tàng tục ngữ người Việt: transcribe the Proverb Entries of one PDF Part (src/khotangtucngu/cli.py)
#
# A layout request per PDF page sees its 300 dpi scan with each printed line's Line Number and answers where each
# Proverb Entry starts; one request per Entry Span then reads its Blocks from its crop of the scan. The code groups the
# Blocks of every page saved in the Part's store into verbatim Proverb Entries and Warnings.
#
# Usage:
#   sbatch scripts/khotangtucngu/submit.sh --part-<n> [--model <key>] [cli.py flags]    # Parts: src/khotangtucngu/settings.py
#   sbatch scripts/khotangtucngu/submit.sh --part-1 --pages 36-45,420-421   # a trial; with no --pages, every proverb page
#   bash scripts/khotangtucngu/submit.sh --part-1 --dry-run                 # on the login node: token counts, no GPU
#
# The model profile is served with vision on for this job only (profiles serve text only), and with at most
# KHOTANGTUCNGU_CONCURRENCY requests in flight (scripts/lib/vision_job.sh).
# -----------------------------------------------------------------------------

KHOTANGTUCNGU_CONCURRENCY=40    # the default profile's
MAX_IMAGES_PER_PROMPT=1    # a layout request sends its page, an Entry Span request its crop

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
run_vision_job khotangtucngu "Kho tàng tục ngữ" src.khotangtucngu.cli "$KHOTANGTUCNGU_CONCURRENCY" \
  "$MAX_IMAGES_PER_PROMPT" "$@"
exit $?
