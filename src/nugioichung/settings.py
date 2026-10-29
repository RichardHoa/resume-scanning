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
