"""Nữ Giới Chung settings, kept apart from the resume pipeline's src/core/config.py."""

# The layout pass sees the whole page small: enough to see columns, rules and titles, not to read every word
LAYOUT_LONG_SIDE = 1600
# Each Region is cut from the scan at its own 300 dpi, so every diacritic is readable
CROP_DPI = 300
# The layout pass answers without thinking: when it thinks, it works its boxes out as round figures in words instead
# of placing them on the scan. A page's answer is a few dozen Regions, with titles in Vietnamese, which tokenises long
LAYOUT_MAX_TOKENS = 8192
# A read or format answer is the text of one Region or Strip, a few hundred to a few thousand tokens. The cap also
# stops a runaway answer (a row of leader dots copied dot by dot)
TRANSCRIBE_MAX_TOKENS = 8192
# Seconds to wait for one request's answer before it fails and is retried
REQUEST_TIMEOUT = 180
# Retries after the first attempt sample, as an identical prompt at temperature 0 fails the same way
RETRY_TEMPERATURE = 0.3
# How far, in thousandths of the page, a Region's box edge may move to land on a column gap or printed rule. The
# layout pass's edges are often 30-40 off (it guesses round figures), under half a column's width
SNAP_REACH = 60
# A Region taller than this, in thousandths of the page (about a third), is cut into Strips no taller than about this
STRIP_HEIGHT = 333
# Printed lines of a Region or Strip (docs/adr/0002-paragraphs-from-line-geometry.md), tuned on Số 1. Its lines touch
# where accents and descenders meet, so a row of pixels is between lines when it holds at most this share of the ink
# of a busy row of the Cut (its 90th percentile)
LINE_GAP_SHARE = 0.08
# A band about two or more lines tall is lines that touch, cut where a row holds at most this share of the band's
# median row ink
VALLEY_SHARE = 0.35
# A band of ink thinner than this share of the Cut's median line (a row of tone marks, a dot under a letter, a speck)
# is merged into the line next to it
TONE_BAND_SHARE = 0.5
# A band of ink this many times as tall as the median line, and at least this share ink, is a printed picture; a
# taller band with less ink is a line of large type
PICTURE_LINES = 3
PICTURE_INK = 0.3
# A line starts a paragraph when its left end is more than this share of the Cut's median line height (accents and
# descenders included) right of the Cut's usual left edge: Số 1 indents a paragraph about a line height, and the
# ends of other lines vary by about a seventh of one...
INDENT_LINES = 0.5
# ...and ends one when its right end stops more than this share of the Cut's width short of its usual right edge
SHORT_LINE_SHARE = 0.15
# A line is centred, a line of its own, when both its margins are wider than this many median line heights and differ
# by at most this share of the wider
CENTRED_LINES = 2
CENTRED_SKEW = 0.35
# The review viewer shows each page about this many px on its long side
PAGE_IMAGE_LONG_SIDE = 2000
