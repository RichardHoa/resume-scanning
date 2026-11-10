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
# for a long note and stops a runaway answer (p042-L02 ran to it in newlines on all 3 attempts; the server now forbids
# whitespace between JSON tokens, scripts/khotangtucngu/submit.sh)
SPAN_MAX_TOKENS = 4096
# An Entry Span answer ends at the first of these, which its JSON never holds (Blocks hold no object or array, and the
# book prints no brackets or braces): a runaway of closing brackets ("}]}}", "]]]]") fails in a few tokens, not at
# SPAN_MAX_TOKENS
SPAN_STOP = ("}}", "]]")
# Apple Vision reads every printed line and every whole page on a Mac before the job runs (vision_ocr.py;
# docs/adr/0004-apple-vision-reads-each-page.md and 0005-two-reads-and-model-edits.md beside the GLOSSARY). Language
# correction is off, as the book's own spelling is what is copied, and it made no difference in the trial
VISION_REVISION = 3
VISION_LANGUAGE = "vi-VT"
VISION_LANGUAGE_CORRECTION = False
# A line is read from its crop at PAGE_DPI on white, with this many px of padding on every side, and a page whole at
# this dpi: the two reads failed on different words in the trial
VISION_LINE_PAD_PX = 45
VISION_PAGE_DPI = 400
# Seconds to wait for Vision's answer on one image before its page fails: well past the 30 s its model takes to load
VISION_READ_TIMEOUT = 300
# A line's crop: its ink band grown up over the ink just above it, then OCR_PAD_PX around and beyond its ink ends.
# A mark over a capital (the hook of Ả) can have too little ink for its rows to count in the band (a fixed 8 px above
# cut it off on p036-L02), so the crop takes in the ink between the line's ends above its band, row by row up to
# OCR_ABOVE_GAP_PX of blank rows, within OCR_ABOVE_SHARE of the median line height and below the line before
OCR_ABOVE_SHARE = 0.4
OCR_ABOVE_GAP_PX = 10
OCR_PAD_PX = 4
# ...and this many px under its band, as far as the next line's ink: a dot under a letter can have too little ink for its
# rows to count in the band either, and with only OCR_PAD_PX under it the line read lost the dot 11 times on 15 pages
# (thụ→thu, mặn→măn) where the page read never did
OCR_BELOW_PX = 20
# The crops each line is read from once more, each (px under its band, zoom), to tell how stable its reads are: an Agreed
# Syllable every one of them also reads is Stable. Vision's reads held like this where the model was more often wrong to
# change them (làn on A 42, muộn on C 508), and flipped where it was right (chẳng on A 28)
VISION_STABILITY_CROPS = ((12, 1), (12, 2), (20, 2), (12, 3))
# Seconds to wait for one request's answer before it fails and is retried: past the 150-210 s a runaway Entry Span
# answer takes to reach SPAN_MAX_TOKENS, so it fails as cut short, not as a timeout
REQUEST_TIMEOUT = 300
# Every first attempt is at temperature 0 (vlm_requests); retries sample, as an identical prompt at temperature 0
# fails the same way
RETRY_TEMPERATURE = 0.3
# No repetition penalty: vLLM applies it to every token of the prompt too, the reads included, so it pushes a copyist off
# the very word it is copying and onto one the prompt doesn't hold (lần→làn on A 42, VCVN→VCSVN on A 10)
REPETITION_PENALTY = 1.0
# The review server shows each page about this many px on its long side
PAGE_IMAGE_LONG_SIDE = 2000
# The export's Entry Images are cut at this dpi in grayscale: a body line is about 33 px tall, its tone marks and dots
# under letters still clear, and a 3-line span about 11 KB of PNG against 18 KB at PAGE_DPI. Zipping PNGs saves only
# about 3%, so this is what sets their storage
ENTRY_IMAGE_DPI = 200
# An Entry Image running onto a later page has this many px of white between its pages' crops, with a rule
# ENTRY_IMAGE_RULE_PX tall in this grey across its middle
ENTRY_IMAGE_PAGE_GAP_PX = 24
ENTRY_IMAGE_RULE_PX = 2
ENTRY_IMAGE_RULE_GREY = 128
