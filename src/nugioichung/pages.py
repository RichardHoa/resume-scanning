"""
Page images of an Issue PDF, rendered with PyMuPDF in grayscale: the whole page small for the layout pass, and a
Region cut at full scan resolution for the transcription pass. Both are PNG, as sent to the model.

Also the analysis of the bilevel scan at full resolution: snapping a Region's box edges onto column gaps and printed
rules with a margin of blank paper, cutting a tall Region into Strips at blank gaps between lines, and finding printed
text outside every Region.
Boxes are [left, top, right, bottom] in thousandths of the page, as the layout pass gives them.
"""
import math
import threading

import fitz
import numpy as np
from scipy import ndimage

from src.nugioichung.settings import CROP_DPI, LAYOUT_LONG_SIDE, SNAP_REACH, STRIP_HEIGHT

# PyMuPDF documents are not thread-safe, and requests build their images in the phase's worker threads
_render_lock = threading.Lock()

# A pixel of the scan darker than this is ink
INK_LEVEL = 128
# A line of pixels across a box is blank when at most this share of it, or BLANK_PX pixels, is ink (specks)...
BLANK_SHARE = 0.002
BLANK_PX = 2
# ...and a printed rule when at least this share of it is ink
RULE_SHARE = 0.5
# A box edge with no gap within reach may still land on a speckled gap: a run of lines as long as a gap, each at most
# this share ink (or BLANK_PX pixels), as a column gap is where the scan is speckled and no line through text is
SPECKLED_SHARE = 0.02
# A gap between printed lines, or between columns, is a run of at least this many blank pixel lines: shorter runs
# are inside a line of text (between a tone mark and its letter, or between two letters)
MIN_LINE_GAP_PX = 5
MIN_COLUMN_GAP_PX = 10
# Moving a box edge inward, which may leave a line out of its Region, costs this many times moving it outward
INWARD_COST = 2
# A snapped box edge is moved outward by up to this many thousandths of the page while it stays on blank or speckled
# paper, so a Region's crop has a margin around its outermost letters without reaching a rule or the next Region's text
EDGE_PAD = 6

# Text outside any Region: ink within this many thousandths of the page's edges is the scan's border, not print
EDGE_MARGIN = 25
# A patch of ink wholly within this many thousandths of the page's top is the running header and page number
HEADER_BAND = 60
# Ink is looked at in square blocks of this many pixels, and blocks close enough to belong to one line or one
# paragraph are joined: each block reaches 2 blocks across and 1 down, so blocks up to 4 apart across or 2 down join
OUTSIDE_BLOCK = 6
OUTSIDE_JOIN = (3, 5)
# A patch of fewer ink pixels than this is a speck, not text (a short word is about 300)
MIN_TEXT_INK = 300
# A patch touching the edge margin that is at least this share ink is the scan's dark border
SOLID_SHARE = 0.35


def layout_image(doc, page):
    """PDF page `page` (1-based) whole, about LAYOUT_LONG_SIDE px on its long side. Rendering it from the 300 dpi
    scan antialiases the bilevel print into gray."""
    with _render_lock:
        p = doc[page - 1]
        zoom = LAYOUT_LONG_SIDE / max(p.rect.width, p.rect.height)
        return p.get_pixmap(matrix=fitz.Matrix(zoom, zoom), colorspace=fitz.csGRAY).tobytes("png")


def crop_image(doc, page, box):
    """The part of PDF page `page` (1-based) under `box` [left, top, right, bottom] in thousandths of the page, at
    CROP_DPI."""
    with _render_lock:
        p = doc[page - 1]
        r = p.rect
        left, top, right, bottom = box
        clip = fitz.Rect(r.x0 + r.width * left / 1000, r.y0 + r.height * top / 1000,
                         r.x0 + r.width * right / 1000, r.y0 + r.height * bottom / 1000)
        zoom = CROP_DPI / 72
        return p.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip, colorspace=fitz.csGRAY).tobytes("png")


def page_ink(doc, page):
    """PDF page `page` (1-based) whole at CROP_DPI, as a bool array (rows, columns), True where there is ink."""
    with _render_lock:
        pix = doc[page - 1].get_pixmap(matrix=fitz.Matrix(CROP_DPI / 72, CROP_DPI / 72), colorspace=fitz.csGRAY)
    gray = np.frombuffer(pix.samples, np.uint8).reshape(pix.height, pix.stride)[:, :pix.width]
    return gray < INK_LEVEL


def _px(t, size):
    """The two pixel lines (or one) that a box edge at `t` thousandths of a `size`-pixel side runs along."""
    x = t * size / 1000
    return min(int(x), size - 1), min(math.ceil(x), size - 1)


def _line_ink(profile, t):
    """The ink a box edge at `t` thousandths would cut, from `profile`: the ink count of each pixel line."""
    a, b = _px(t, len(profile))
    return max(profile[a], profile[b])


def _gap_lines(profile, extent, min_gap, share=BLANK_SHARE):
    """
    For each pixel line of `profile` (the ink count of each line, `extent` pixels long), whether it is in a run of at
    least `min_gap` lines each at most `share` of it ink, or BLANK_PX pixels.
    """
    blank = profile <= max(BLANK_PX, extent * share)
    gaps = np.zeros(len(profile), bool)
    edges = np.flatnonzero(np.diff(np.concatenate(([0], blank.astype(np.int8), [0]))))
    for start, stop in zip(edges[::2], edges[1::2]):
        if stop - start >= min_gap:
            gaps[start:stop] = True
    return gaps


def _safe_lines(profile, extent, min_gap):
    """
    For each pixel line of `profile` (the ink count of each line, `extent` pixels long), whether a box edge can run
    along it without cutting text: it is in a run of at least `min_gap` blank lines, or on a printed rule.
    """
    return _gap_lines(profile, extent, min_gap) | (profile >= extent * RULE_SHARE)


def _is_safe(safe, t):
    a, b = _px(t, len(safe))
    return safe[a] and safe[b]


def _span(t0, t1, size):
    """The pixel lines from a box edge at `t0` to one at `t1`, both included."""
    return slice(_px(t0, size)[0], _px(t1, size)[1] + 1)


def _snap_edge(safe, speckled, edge, outward):
    """
    `edge` moved to the nearest place within SNAP_REACH where it runs along a gap or a printed rule (`safe`, from
    `_safe_lines`), so it cuts no line of text; if there is none, to the nearest speckled gap (`speckled`, from
    `_gap_lines` with SPECKLED_SHARE); unmoved if there is neither. Moving inward costs INWARD_COST times moving
    outward. Then, unless it is on a rule, moved on outward by up to EDGE_PAD while it stays on a blank or speckled gap.
    `outward`: -1 for a left or top edge, +1 for a right or bottom one.
    """
    def cost(t):
        return abs(t - edge) * (1 if (t - edge) * outward >= 0 else INWARD_COST)

    reach = range(max(0, edge - SNAP_REACH), min(1000, edge + SNAP_REACH) + 1)
    places = [t for t in reach if _is_safe(safe, t)] or [t for t in reach if _is_safe(speckled, t)]
    if not places:
        return edge
    snapped = min(places, key=cost)
    if not _is_safe(speckled, snapped):
        return snapped      # on a rule: the margin beyond it is the next Region's
    padded = snapped
    for t in range(snapped + outward, snapped + outward * (EDGE_PAD + 1), outward):
        if not (0 <= t <= 1000 and _is_safe(speckled, t)):
            break
        padded = t
    return padded


def _snap_pair(profile, extent, min_gap, low, high):
    """A box's low and high edges along one axis, snapped by `_snap_edge` onto `profile`, the ink count of each pixel
    line across the box (`extent` pixels long), whose gaps are runs of at least `min_gap` lines."""
    safe = _safe_lines(profile, extent, min_gap)
    speckled = _gap_lines(profile, extent, min_gap, SPECKLED_SHARE)
    return _snap_edge(safe, speckled, low, -1), _snap_edge(safe, speckled, high, +1)


def snap_box(ink, box):
    """`box` with its left and right edges moved onto the nearest column gap or vertical rule, then its top and
    bottom onto the nearest blank line or horizontal rule, each with a margin of blank paper. `ink`: the page from
    `page_ink`."""
    h, w = ink.shape
    left, top, right, bottom = box
    rows = _span(top, bottom, h)
    left, right = _snap_pair(ink[rows, :].sum(axis=0), rows.stop - rows.start, MIN_COLUMN_GAP_PX, left, right)
    cols = _span(left, right, w)
    top, bottom = _snap_pair(ink[:, cols].sum(axis=1), cols.stop - cols.start, MIN_LINE_GAP_PX, top, bottom)
    return [left, top, right, bottom]


def strip_boxes(ink, box):
    """
    The Strips of a Region taller than STRIP_HEIGHT, top to bottom, [] for a shorter one. The Region is cut into as
    few even Strips as keep each about STRIP_HEIGHT or less, each cut moved to the nearest gap between printed lines
    (or the emptiest line, if there is none) within a quarter Strip. Strips meet at their cuts and never overlap.
    """
    left, top, right, bottom = box
    height = bottom - top
    if height <= STRIP_HEIGHT:
        return []
    n = math.ceil(height / STRIP_HEIGHT)
    cols = _span(left, right, ink.shape[1])
    lines = ink[:, cols].sum(axis=1)
    blank = max(BLANK_PX, (cols.stop - cols.start) * BLANK_SHARE)
    gaps = _safe_lines(lines, cols.stop - cols.start, MIN_LINE_GAP_PX)
    reach = height // (4 * n)
    cuts = [top]
    for k in range(1, n):
        target = top + round(height * k / n)
        options = range(max(cuts[-1] + 1, target - reach), min(bottom - 1, target + reach) + 1)
        cuts.append(min(options, key=lambda t: (not _is_safe(gaps, t), max(_line_ink(lines, t), blank),
                                                abs(t - target))))
    cuts.append(bottom)
    return [[left, a, right, b] for a, b in zip(cuts, cuts[1:])]


def text_outside(ink, boxes):
    """
    The boxes of printed text on the page that falls inside none of `boxes`, ignoring specks, the page's edges (the
    scan's border) and the running header at the top.
    """
    h, w = ink.shape
    free = ink.copy()
    my, mx = EDGE_MARGIN * h // 1000, EDGE_MARGIN * w // 1000
    free[:my], free[h - my:], free[:, :mx], free[:, w - mx:] = False, False, False, False
    for left, top, right, bottom in boxes:
        free[_span(top, bottom, h), _span(left, right, w)] = False

    b = OUTSIDE_BLOCK
    hb, wb = h // b, w // b
    counts = free[:hb * b, :wb * b].reshape(hb, b, wb, b).sum(axis=(1, 3))
    labels, _ = ndimage.label(ndimage.maximum_filter((counts > 0).astype(np.uint8), size=OUTSIDE_JOIN))
    found = []
    for i, (ys, xs) in enumerate(ndimage.find_objects(labels), 1):
        mine = counts[ys, xs] * (labels[ys, xs] == i)
        amount = mine.sum()
        if amount < MIN_TEXT_INK:
            continue
        # The patch's own ink, without the reach that joined it
        rows, cols = np.nonzero(mine)
        y0, y1 = ys.start + rows.min(), ys.start + rows.max() + 1
        x0, x1 = xs.start + cols.min(), xs.start + cols.max() + 1
        top, bottom = y0 * b * 1000 // h, math.ceil(y1 * b * 1000 / h)
        left, right = x0 * b * 1000 // w, math.ceil(x1 * b * 1000 / w)
        if bottom <= HEADER_BAND:
            continue
        at_edge = (top <= EDGE_MARGIN + 1 or left <= EDGE_MARGIN + 1
                   or bottom >= 1000 - EDGE_MARGIN - 1 or right >= 1000 - EDGE_MARGIN - 1)
        if at_edge and amount >= SOLID_SHARE * (y1 - y0) * (x1 - x0) * b * b:
            continue
        found.append([int(left), int(top), min(1000, int(right)), min(1000, int(bottom))])
    return found
