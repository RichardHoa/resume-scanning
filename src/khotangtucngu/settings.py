"""Kho tàng tục ngữ người Việt settings, kept apart from the resume pipeline's src/core/config.py."""
import os
from typing import NamedTuple, Tuple

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BOOK_DIR = os.path.join(_PROJECT_ROOT, "vsc-project", "khoTangTucNguoiNguoiViet")
# The transcribed Front Matter: its Bảng chữ tắt I lists the 63 Source Abbreviations
FRONT_MATTER = os.path.join(BOOK_DIR, "front-matter.md")
# One store per PDF Part, <STORE_DIR>/<its key>/
STORE_DIR = os.path.join(BOOK_DIR, "store")


class Part(NamedTuple):
    pdf: str                            # its file name in BOOK_DIR
    proverb_pages: Tuple[int, int]      # the first and last PDF page of its Proverb Entries, past the Front Matter
    book_page_offset: int               # book page = PDF page + this


# By the key the CLI takes as a flag (--part-1) and names its store by. Parts 2-4 are added here when they are run
PARTS = {
    "part-1": Part("kho tàng tục ngữ người việt tập 1 - p1.pdf", (36, 865), -1),
}

# Pages are read at the scan's 300 dpi, in grayscale PNG, so every diacritic and every subscript is readable
# (docs/adr/0001-entry-spans-from-numbered-lines.md beside the GLOSSARY): the layout request sees the whole page with
# its Line Numbers, and each Entry Span is cut from it
PAGE_DPI = 300
PAGE_IMAGE = "grayscale png"
# The layout image: the page with a white strip this many px wide added on its right, where each printed line's Line
# Number is written ("L12") in red, LABEL_PX tall, with a tick from the line's right end to it. Body lines at 300 dpi are
# about 50 px apart
LABEL_STRIP_PX = 200
LABEL_PX = 36
LABEL_COLOUR = (220, 0, 0)
LAYOUT_IMAGE = f"colour png, Line Numbers in a {LABEL_STRIP_PX} px strip, {LABEL_PX} px, rgb{LABEL_COLOUR}"
# An Entry Span's crop reaches across the gap above and below it to this many px short of the next line's ink, so
# no tone mark or dot under a letter is clipped and no letter of a neighbour comes in...
SPAN_EDGE_GAP_PX = 2
# ...and this many px (5 mm) beyond the furthest ink of the page's lines on the left and right, and above or below
# where no line is next to it
SPAN_MARGIN_PX = 60
# Ink outside the page's text block (its found lines, with the Entry Spans' margins), which no Entry Span holds, is
# text the line finder missed when a patch of it, its pixels joined across MISSED_JOIN_PX, holds at least this many ink
# pixels (a short word is about 300); ink within EDGE_PX of the page's edges is the scan's border
MISSED_INK = 300
MISSED_JOIN_PX = 9
EDGE_PX = 40
# The layout answer is a page number and a dozen Line Numbers
LAYOUT_MAX_TOKENS = 512
# An Entry Span's answer is the Blocks of one Proverb Entry, about 100-300 tokens in Vietnamese; the cap leaves room
# for a long note and stops a runaway answer (p042-L02 once ran to 2048 tokens of newlines before a retry answered in
# 133)
SPAN_MAX_TOKENS = 4096
# The OCR model reads each printed line of an Entry Span on its own before the Entry Span request, which gets its OCR
# Readings with the crop (docs/adr/0002-ocr-readings-of-each-line.md and 0003-vietocr-reads-each-line.md beside the
# GLOSSARY): VietOCR's vgg_transformer (pbcquoc/vietocr), a recogniser of one Vietnamese line, run in the CLI's own
# process on the GPU (ocr.py). Its weights are downloaded once, beside the HuggingFace cache vllm_utils.sh finds
OCR_MODEL = "vietocr vgg_transformer"
OCR_WEIGHTS_URL = "https://vocr.vn/data/vietocr/vgg_transformer.pth"
OCR_WEIGHTS = os.path.join(os.environ.get("HF_HOME") or os.path.expanduser("~/.cache"), "vietocr",
                           "vgg_transformer.pth")
# A line's crop: its ink band, OCR_PAD_TOP_PX above (a tone mark over a capital stands tallest) and OCR_PAD_PX below
# and beyond its ink ends. VietOCR scales it to OCR_IMAGE_HEIGHT, the height its weights were trained at, keeping its
# aspect up to OCR_IMAGE_MAX_WIDTH: its encoder reads one of its 1024 positions per 2 px of width, so 2048 is the
# most it holds. A line about 60-90 px tall and up to 1700 px wide at 300 dpi keeps its tone marks about 4-5 px tall,
# where VietOCR's own 512 px cap would leave them 2-3 px
OCR_PAD_TOP_PX = 8
OCR_PAD_PX = 4
OCR_IMAGE_HEIGHT = 32
OCR_IMAGE_MIN_WIDTH = 32
OCR_IMAGE_MAX_WIDTH = 2048
OCR_IMAGE = f"grayscale png, one line's ink, {OCR_PAD_TOP_PX} px above and {OCR_PAD_PX} px around"
# Beam search (4 beams, one line at a time) makes fewer errors than greedy decoding
OCR_BEAM_SEARCH = True
# Seconds to wait for one request's answer before it fails and is retried: past the 150-210 s a runaway Entry Span
# answer takes to reach SPAN_MAX_TOKENS, so it fails as cut short, not as a timeout
REQUEST_TIMEOUT = 300
# Every first attempt is at temperature 0 (vlm_requests); retries sample, as an identical prompt at temperature 0
# fails the same way
RETRY_TEMPERATURE = 0.3
# The review server shows each page about this many px on its long side
PAGE_IMAGE_LONG_SIDE = 2000
