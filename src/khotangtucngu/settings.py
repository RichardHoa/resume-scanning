"""Kho tàng tục ngữ người Việt settings, kept apart from the resume pipeline's src/core/config.py."""
import os
from typing import NamedTuple, Tuple

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
BOOK_DIR = os.path.join(_PROJECT_ROOT, "vsc-project", "khoTangTucNguoiNguoiViet")
# The transcribed Front Matter: its Bảng chữ tắt I lists the 63 Source Abbreviations
FRONT_MATTER = os.path.join(BOOK_DIR, "front-matter.md")
# The Back Matter transcribed by hand: the Topic Index's title page and Lời dẫn (PDF 543-546 of Part 4's PDF) and the
# compilers' page (PDF 816), which the pipeline never reads
BACK_MATTER = os.path.join(BOOK_DIR, "back-matter.md")
# One store per PDF Part, <STORE_DIR>/<its key>/
STORE_DIR = os.path.join(BOOK_DIR, "store")


class Part(NamedTuple):
    pdf: str                            # its file name in BOOK_DIR
    proverb_pages: Tuple[int, int]      # the first and last PDF page of its Proverb Entries, past the Front Matter
    book_page_offset: int               # book page = PDF page + this
    # PDF pages the book misprints, never read or answered even when --pages names them
    skipped_pages: Tuple[int, ...] = ()
    # Jumps in the numbering the PDF holds, (letter, number, the next number in it): the numbers between are lost in
    # the book or its scan, and the export doesn't count them missing
    number_jumps: Tuple[Tuple[str, int, int], ...] = ()
    # Book pages the scan lost, (the PDF page it resumes on, how many book pages it lost before it): the book page
    # offset grows by them from that PDF page on, and nothing carries over to it, as after a skipped page
    scan_gaps: Tuple[Tuple[int, int], ...] = ()
    # PDF pages scanned askew, (PDF page, degrees anticlockwise): each is turned back by its angle whenever the PDF is
    # opened (pages.open_pdf), so its lines are found and everything is cut from it straight. Askew, a page's lines
    # overlap in their rows and the line finder takes several as one
    turned_pages: Tuple[Tuple[int, float], ...] = ()


# By the key the CLI takes as a flag (--part-1) and names its store by
PARTS = {
    # PDF page 671 is printed again with C 1841-1846 from an earlier page, so C 1855 on page 670 is followed by the end
    # of an entry and C 1862 on page 672: C 1856-1861 are lost in the book, not in the pipeline
    "part-1": Part("kho tàng tục ngữ người việt tập 1 - p1.pdf", (36, 865), -1,
                   skipped_pages=(671,), number_jumps=(("C", 1855, 1862),)),
    # Its Front Matter is a title and a credits page: the D heading opens PDF page 5 (book page 865, after Part 1's
    # 864), and PDF page 818 (book page 1678) is the last before the colophon
    "part-2": Part("Kho tàng tục ngữ người việt tập 1 - p2.pdf", (5, 818), 860),
    # Tập 2 opens with the M heading on PDF page 5 (book page 1679, after Part 2's 1678). The scan lost book pages
    # 1707-1722: PDF page 32 (book page 1706) ends with M 140, and PDF page 33 (book page 1723) opens with the end of
    # M 237's note, then M 238. Its last proverb page is PDF page 736 (book page 2426). PDF page 612 is scanned 1.6°
    # clockwise: as scanned, its 29 printed lines were found as 18, and entry 13's first line was in none of them
    "part-3": Part("kho tàng tục ngư người việt tập 2  - p1.pdf", (5, 736), 1674,
                   number_jumps=(("M", 140, 238),), scan_gaps=((33, 16),), turned_pages=((612, 1.6),)),
    # The T heading opens PDF page 5 (book page 2427), and PDF page 542 (book page 2964) is the last before the
    # Hệ thống tra cứu theo chủ đề and the other indexes
    "part-4": Part("kho tàng tục ngữ người việt tập 2 - p2.pdf", (5, 542), 2422),
}

# Sections of a PDF Part that are not Proverb Entries, by the key the CLI takes as a flag (--part-4-final-section) and
# names its store by, apart from PARTS so that the Parts' export and See-also lookups never take one for a Part. Each is
# a Part's fields, its proverb_pages being its own pages. The Topic Index (Hệ thống tra cứu theo chủ đề, topics.py)
# opens with chủ đề I on PDF page 547 of Part 4's PDF and ends on PDF page 674 (book page 3096); its title page and Lời
# dẫn before it, PDF 543-546, are in BACK_MATTER
SECTIONS = {
    "part-4-final-section": Part(PARTS["part-4"].pdf, (547, 674), PARTS["part-4"].book_page_offset),
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
# An Index Line's answer: a heading's text, or a row letter and about a dozen numbers. The cap stops a runaway run of
# numbers ("1385, 1386, ...") in a few seconds, as an answer cut short
INDEX_MAX_TOKENS = 512
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
