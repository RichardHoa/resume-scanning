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
# for a long note and stops a runaway answer
SPAN_MAX_TOKENS = 2048
# The OCR model, served beside the default model (scripts/khotangtucngu/submit.sh), reads each printed line of an
# Entry Span on its own before the Entry Span request, which gets its OCR Readings with the crop
# (docs/adr/0002-ocr-readings-of-each-line.md beside the GLOSSARY). It is asked only "OCR:", its model card's prompt
# for text, at no repetition penalty: a line repeats its words as printed
OCR_MODEL = "PaddlePaddle/PaddleOCR-VL-1.6"
OCR_PROMPT = "OCR:"
OCR_REPETITION_PENALTY = 1.0
# A line crop: as tall as the gaps to the lines above and below allow (as an Entry Span's, SPAN_EDGE_GAP_PX short of
# their ink), as wide as the page's Entry Spans. About 2000 x 60 px, under the model's own pixel budget
# (1280 x 28 x 28), so it is read at the scan's 300 dpi
OCR_IMAGE = f"grayscale png, one line, {SPAN_EDGE_GAP_PX} px from its neighbours"
# A printed line is about 15-30 tokens; the cap stops a runaway answer
OCR_MAX_TOKENS = 256
# Seconds to wait for one request's answer before it fails and is retried
REQUEST_TIMEOUT = 180
# Every first attempt is at temperature 0 (vlm_requests); retries sample, as an identical prompt at temperature 0
# fails the same way
RETRY_TEMPERATURE = 0.3
# The review server shows each page about this many px on its long side
PAGE_IMAGE_LONG_SIDE = 2000
