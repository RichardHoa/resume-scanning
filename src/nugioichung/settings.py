"""Nữ Giới Chung settings, kept apart from the resume pipeline's src/core/config.py."""

# The layout pass sees the whole page small: enough to see columns, rules and titles, not to read every word
LAYOUT_LONG_SIDE = 1600
# Each Region is cut from the scan at its own 300 dpi, so every diacritic is readable
CROP_DPI = 300
# The layout pass thinks before it answers (reading order, continuations), so it gets room for both
LAYOUT_MAX_TOKENS = 16384
# A transcription answer is the text of one Region
TRANSCRIBE_MAX_TOKENS = 4096
# Retries after the first attempt sample, as an identical prompt at temperature 0 fails the same way
RETRY_TEMPERATURE = 0.3
# How far, in thousandths of the page, a Region's box edge may move to land on a column gap or printed rule
SNAP_REACH = 25
# A Region taller than this, in thousandths of the page (about a third), is cut into Strips no taller than about this
STRIP_HEIGHT = 333
