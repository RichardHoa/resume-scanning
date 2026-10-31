"""
Page images of a scanned PDF, rendered with PyMuPDF in grayscale PNG, shared by Nữ Giới Chung (src/nugioichung) and
Kho tàng tục ngữ (src/khotangtucngu).

Also the printed-line finder both use on the bilevel scan: a page (or part of one) as a bool ink array, its vertical
and horizontal rules left out, cut into bands of rows that are each one printed line, tone marks and dots under
letters included.
"""
import math
import threading

import fitz
import numpy as np

# PyMuPDF documents are not thread-safe, and requests build their images in the phase's worker threads
RENDER_LOCK = threading.Lock()

# A pixel of the scan darker than this is ink
INK_LEVEL = 128
# A row of pixels with at most BLANK_PX of ink is blank (specks)...
BLANK_PX = 2
# ...and a printed rule when at least this share of it is ink
RULE_SHARE = 0.5
# A column of pixels with an unbroken run of ink this long (half an inch at 300 dpi, three lines or more) is a vertical
# rule; it and RULE_PAD columns either side are left out of the lines
MIN_RULE_RUN_PX = 150
RULE_PAD = 3
# A run of rows at least RULE_SHARE ink, at most this many thick, is a horizontal rule (a picture's dark rows are more)
MAX_RULE_PX = 12
# A line's ends are those of its runs of ink with at least this much ink (a full stop alone is about 40 pixels), so
# specks in the margin beside it don't move them; a band with less ink in all is a speck, not a line
LINE_END_INK = 40
# Tuned on Nữ Giới Chung Số 1 (src/nugioichung/docs/adr/0002-paragraphs-from-line-geometry.md). Lines touch where
# accents and descenders meet, so a row of pixels is between lines when it holds at most this share of the ink of a
# busy row of the area (its 90th percentile)
LINE_GAP_SHARE = 0.08
# A band about two or more lines tall is lines that touch, cut where a row holds at most this share of the band's
# median row ink
VALLEY_SHARE = 0.35
# A band of ink thinner than this share of the area's median line (a row of tone marks, a dot under a letter, a speck)
# is merged into the line next to it
TONE_BAND_SHARE = 0.5


def whole_page(doc, page, long_side):
    """PDF page `page` (1-based) whole, about `long_side` px on its long side."""
    with RENDER_LOCK:
        p = doc[page - 1]
        zoom = long_side / max(p.rect.width, p.rect.height)
        return p.get_pixmap(matrix=fitz.Matrix(zoom, zoom), colorspace=fitz.csGRAY).tobytes("png")


def whole_page_at_dpi(doc, page, dpi):
    """PDF page `page` (1-based) whole at `dpi`."""
    with RENDER_LOCK:
        zoom = dpi / 72
        return doc[page - 1].get_pixmap(matrix=fitz.Matrix(zoom, zoom), colorspace=fitz.csGRAY).tobytes("png")


def page_ink(doc, page, dpi):
    """PDF page `page` (1-based) whole at `dpi`, as a bool array (rows, columns), True where there is ink."""
    with RENDER_LOCK:
        pix = doc[page - 1].get_pixmap(matrix=fitz.Matrix(dpi / 72, dpi / 72), colorspace=fitz.csGRAY)
    gray = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.stride)[:, :pix.width]
    return gray < INK_LEVEL


def rule_columns(area):
    """For each column of `area` (a bool ink array), whether it is on a vertical rule or within RULE_PAD of one."""
    edges = np.diff(np.pad(area.astype(np.int8), ((1, 1), (0, 0))), axis=0).T
    cols, starts = np.nonzero(edges == 1)
    _, stops = np.nonzero(edges == -1)
    longest = np.zeros(area.shape[1], int)
    np.maximum.at(longest, cols, stops - starts)
    rules = (longest >= MIN_RULE_RUN_PX).astype(int)
    return np.convolve(rules, np.ones(2 * RULE_PAD + 1, int), "same") > 0


def line_bands(area):
    """
    The printed lines of `area` (a bool ink array, its vertical rules already left out), top to bottom, as
    [top, bottom, core top, core bottom] rows (bottoms exclusive), and the median line height; ([], None) if it has
    none. Its horizontal rules left out, a line is a band of rows each with more ink than LINE_GAP_SHARE of a busy row;
    a band thinner than TONE_BAND_SHARE of the median line (tone marks above capitals, a dot under a letter, a speck,
    a dotted rule) is merged into the line nearest it, and a band about two or more lines tall is cut at its valleys.
    A line's core is its band before thin ones were merged into it, which alone gives its ends: a dotted rule under it
    or a speck beside it would move them.
    """
    profile = area.sum(axis=1)
    ruled = profile >= RULE_SHARE * area.shape[1]
    edges = np.flatnonzero(np.diff(np.concatenate(([0], ruled.astype(np.int8), [0]))))
    for a, b in zip(edges[::2], edges[1::2]):
        if b - a <= MAX_RULE_PX:
            profile[a:b] = 0
    inked = profile > max(BLANK_PX, LINE_GAP_SHARE * np.percentile(profile, 90))
    edges = np.flatnonzero(np.diff(np.concatenate(([0], inked.astype(np.int8), [0]))))
    bands = [[int(a), int(b)] for a, b in zip(edges[::2], edges[1::2]) if profile[a:b].sum() >= LINE_END_INK]
    if not bands:
        return [], None
    heights = np.array([b - a for a, b in bands])
    line = np.median(heights)
    line = float(np.median(heights[heights >= TONE_BAND_SHARE * line]))
    # Lines that touch make one band about a whole number of lines tall: it is cut at the emptiest row near each place
    # a line should end, where that row is a valley (a tall line of large type has none)
    touching, bands = bands, []
    for a, b in touching:
        n = round((b - a) / line)
        start, middle, reach = a, np.median(profile[a:b]), round(line / 3)
        for k in range(1, n):
            target = a + round((b - a) * k / n)
            lo, hi = max(start + 1, target - reach), min(b - 1, target + reach)
            if lo < hi:
                gap = lo + int(np.argmin(profile[lo:hi]))
                if profile[gap] <= VALLEY_SHARE * middle:
                    bands.append([start, gap])
                    start = gap + 1
        bands.append([start, b])
    bands = [[a, b, a, b] for a, b in bands]
    while len(bands) > 1:
        thin = [i for i, (a, b, _, _) in enumerate(bands) if b - a < TONE_BAND_SHARE * line]
        if not thin:
            break
        i = thin[0]
        above = bands[i][0] - bands[i - 1][1] if i > 0 else math.inf
        below = bands[i + 1][0] - bands[i][1] if i + 1 < len(bands) else math.inf
        lo, hi = (i - 1, i) if above < below else (i, i + 1)
        core = max(bands[lo], bands[hi], key=lambda band: band[3] - band[2])[2:]
        bands[lo:hi + 1] = [[bands[lo][0], bands[hi][1]] + core]
    return bands, line


def line_ends(ink_cols, reach):
    """A line's left and right ends (the right one exclusive), from `ink_cols`, the ink in each of its columns: the
    ends of its ink in runs of columns less than `reach` apart (a word space is less than half a line's height),
    leaving out runs with less than LINE_END_INK (specks). (0, 0) if it has none."""
    inked = np.flatnonzero(ink_cols)
    if not len(inked):
        return 0, 0
    breaks = np.flatnonzero(np.diff(inked) > reach)
    starts = np.concatenate(([inked[0]], inked[breaks + 1]))
    stops = np.concatenate((inked[breaks], [inked[-1]])) + 1
    total = np.concatenate(([0], np.cumsum(ink_cols)))
    kept = [(a, b) for a, b in zip(starts, stops) if total[b] - total[a] >= LINE_END_INK]
    if not kept:
        return 0, 0
    return int(kept[0][0]), int(kept[-1][1])
