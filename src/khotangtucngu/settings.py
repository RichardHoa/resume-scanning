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

# Each page is sent whole at the scan's 300 dpi, in grayscale PNG, so every diacritic and every subscript is readable
PAGE_DPI = 300
PAGE_IMAGE = "grayscale png"
# A page's answer is its Blocks: about a dozen entries at most, in Vietnamese, which tokenises long. The cap also stops
# a runaway answer
PAGE_MAX_TOKENS = 6144
# Seconds to wait for one request's answer before it fails and is retried
REQUEST_TIMEOUT = 180
# Retries after the first attempt sample, as an identical prompt at temperature 0 fails the same way
RETRY_TEMPERATURE = 0.3
# The review server shows each page about this many px on its long side
PAGE_IMAGE_LONG_SIDE = 2000
