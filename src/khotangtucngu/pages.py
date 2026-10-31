"""
Page images of a PDF Part and the printed lines on them: each page's lines found on the 300 dpi scan, the page with
their Line Numbers for the layout request, each Entry Span and each of its lines cut from the scan for their own
requests, and the page smaller for the review server. Places on the page are in px of the 300 dpi scan: a line is [top, bottom, left, right] and a
crop [left, top, right, bottom], bottom and right exclusive.
"""
from io import BytesIO

import fitz
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

from src.khotangtucngu.settings import (
    EDGE_PX, LABEL_COLOUR, LABEL_PX, LABEL_STRIP_PX, MISSED_INK, MISSED_JOIN_PX, PAGE_DPI, PAGE_IMAGE_LONG_SIDE,
    SPAN_EDGE_GAP_PX, SPAN_MARGIN_PX
)
from src.providers.page_images import (
    RENDER_LOCK, line_bands, line_ends, page_ink, rule_columns, whole_page, whole_page_at_dpi
)


def page_key(page):
    """A PDF page's name in the store: its requests and its page images."""
    return f"p{page:03d}"


def span_key(page, first):
    """An Entry Span's name in the store: its page and the Line Number it starts on."""
    return f"{page_key(page)}-L{first:02d}"


def line_key(page, n):
    """A printed line's name in the store (its OCR Reading): its page and its Line Number."""
    return f"{page_key(page)}-L{n:02d}"


def _sides(lines, width):
    """The left and right edges of every Entry Span of a page: SPAN_MARGIN_PX beyond the furthest ink of its lines."""
    return (max(0, min(line[2] for line in lines) - SPAN_MARGIN_PX),
            min(width, max(line[3] for line in lines) + SPAN_MARGIN_PX))


def _missed(area, lines):
    """The patches of ink in `area` (the page's ink, its vertical rules left out) outside the page's text block (from
    its first line's top to SPAN_MARGIN_PX under its last line, between `_sides`) and the page's edges, each with at
    least MISSED_INK pixels, as crops."""
    h, w = area.shape
    free = area.copy()
    free[:EDGE_PX], free[h - EDGE_PX:], free[:, :EDGE_PX], free[:, w - EDGE_PX:] = False, False, False, False
    if lines:
        left, right = _sides(lines, w)
        free[lines[0][0]:lines[-1][1] + SPAN_MARGIN_PX, left:right] = False
    labels, n = ndimage.label(ndimage.maximum_filter(free.astype(np.uint8), size=MISSED_JOIN_PX))
    if not n:
        return []
    amounts = ndimage.sum(free, labels, index=range(1, n + 1))
    return [[s[1].start, s[0].start, s[1].stop, s[0].stop]
            for s, amount in zip(ndimage.find_objects(labels), amounts) if amount >= MISSED_INK]


def find_lines(doc, page):
    """
    PDF page `page` (1-based) read on its 300 dpi scan: {"size": [width, height], "lines": the printed lines top to
    bottom, Line Number n being lines[n - 1], "missed": the patches of ink outside the page's text block}. A line is a
    band of page_images.line_bands with its ends; one with no run of ink big enough to have ends is left out.
    """
    ink = page_ink(doc, page, PAGE_DPI)
    h, w = ink.shape
    area = ink & ~rule_columns(ink)
    bands, height = line_bands(area)
    lines = []
    for top, bottom, core_top, core_bottom in bands:
        left, right = line_ends(area[core_top:core_bottom].sum(axis=0), round(height / 2))
        if right > left:
            lines.append([top, bottom, left, right])
    return {"size": [w, h], "lines": lines, "missed": _missed(area, lines)}


def layout_image(doc, page, lines):
    """PDF page `page` (1-based) whole at PAGE_DPI, in colour, with a white strip LABEL_STRIP_PX wide added on its
    right, where each of `lines` has its Line Number ("L1", "L2", ...) in red, a tick from the line's right end to it."""
    scan = Image.open(BytesIO(whole_page_at_dpi(doc, page, PAGE_DPI))).convert("RGB")
    w, h = scan.size
    image = Image.new("RGB", (w + LABEL_STRIP_PX, h), "white")
    image.paste(scan, (0, 0))
    draw = ImageDraw.Draw(image)
    font = ImageFont.load_default(size=LABEL_PX)
    for n, (top, bottom, _, right) in enumerate(lines, 1):
        y = (top + bottom) // 2
        draw.line([(right + 12, y), (w + 6, y)], fill=LABEL_COLOUR, width=2)
        draw.text((w + 14, y), f"L{n}", fill=LABEL_COLOUR, font=font, anchor="lm")
    out = BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


def review_layout_image(layout_png):
    """The layout image about PAGE_IMAGE_LONG_SIDE px on its long side, for the review server."""
    image = Image.open(BytesIO(layout_png))
    zoom = PAGE_IMAGE_LONG_SIDE / max(image.size)
    image = image.resize((round(image.width * zoom), round(image.height * zoom)), Image.Resampling.LANCZOS)
    out = BytesIO()
    image.save(out, "PNG")
    return out.getvalue()


def layout_problem(answer, n_lines):
    """Why a layout answer can't be used on a page of `n_lines` printed lines, or None: its printed page number must
    be text, and its first line below the Running Head and its start lines Line Numbers of the page, the starts
    increasing, none above the first."""
    body, starts = answer.get("body_start"), answer.get("starts")
    if not isinstance(answer.get("printed_page"), str):
        return f"printed_page {answer.get('printed_page')!r} is not text"
    if not isinstance(body, int) or not 1 <= body <= n_lines:
        return f"body_start {body!r} is not a Line Number from 1 to {n_lines}"
    if not isinstance(starts, list) or not all(isinstance(s, int) and 1 <= s <= n_lines for s in starts):
        return f"starts {starts!r} are not Line Numbers from 1 to {n_lines}"
    if any(a >= b for a, b in zip(starts, starts[1:])):
        return f"starts {starts} do not increase"
    if starts and body > starts[0]:
        return f"body_start {body} is below the first start, {starts[0]}"
    return None


def entry_spans(found, answer):
    """
    The Entry Spans of a page, top to bottom, from its lines (`found`, from `find_lines`) and its checked layout
    answer: {"first", "last" (its first and last Line Numbers), "leading" (it is the lines from body_start above the
    first start, which continue the page before), "box" (its crop)}. Every line from body_start down is in exactly one.
    """
    lines, (w, h) = found["lines"], found["size"]
    starts = answer["starts"]
    firsts = ([answer["body_start"]] if not starts or starts[0] > answer["body_start"] else []) + starts
    left, right = _sides(lines, w)
    spans = []
    for k, first in enumerate(firsts):
        last = firsts[k + 1] - 1 if k + 1 < len(firsts) else len(lines)
        i, j = first - 1, last - 1
        if i == 0:
            top = lines[i][0] - SPAN_MARGIN_PX
        elif first == answer["body_start"]:
            # Under the Running Head: no further up than half a margin, so its rule and the gap under it stay out
            top = max(lines[i - 1][1] + SPAN_EDGE_GAP_PX, lines[i][0] - SPAN_MARGIN_PX // 2)
        else:
            top = min(lines[i - 1][1] + SPAN_EDGE_GAP_PX, lines[i][0])
        bottom = (lines[j][1] + SPAN_MARGIN_PX if j == len(lines) - 1
                  else max(lines[j + 1][0] - SPAN_EDGE_GAP_PX, lines[j][1]))
        spans.append({"first": first, "last": last, "leading": first not in starts,
                      "box": [left, max(0, top), right, min(h, bottom)]})
    return spans


def line_box(found, n):
    """The crop of Line Number `n` of a page (`found`, from `find_lines`) for its OCR request: as wide as the page's
    Entry Spans, and from SPAN_EDGE_GAP_PX short of the ink of the lines above and below it, at most half a margin
    beyond its own, so no tone mark or dot under a letter is clipped and no Running Head rule comes in."""
    lines, (w, h) = found["lines"], found["size"]
    top, bottom = lines[n - 1][0], lines[n - 1][1]
    above = lines[n - 2][1] + SPAN_EDGE_GAP_PX if n > 1 else 0
    below = lines[n][0] - SPAN_EDGE_GAP_PX if n < len(lines) else h
    left, right = _sides(lines, w)
    return [left, max(0, min(top, max(above, top - SPAN_MARGIN_PX // 2))),
            right, min(h, max(bottom, min(below, bottom + SPAN_MARGIN_PX // 2)))]


def span_image(doc, page, box):
    """The part of PDF page `page` (1-based) under `box`, px of its 300 dpi scan, at PAGE_DPI in grayscale."""
    with RENDER_LOCK:
        p = doc[page - 1]
        r, scale = p.rect, 72 / PAGE_DPI
        left, top, right, bottom = box
        clip = fitz.Rect(r.x0 + left * scale, r.y0 + top * scale, r.x0 + right * scale, r.y0 + bottom * scale)
        zoom = PAGE_DPI / 72
        return p.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip, colorspace=fitz.csGRAY).tobytes("png")


def review_image(doc, page):
    """PDF page `page` (1-based) whole, about PAGE_IMAGE_LONG_SIDE px on its long side, for the review server."""
    return whole_page(doc, page, PAGE_IMAGE_LONG_SIDE)
