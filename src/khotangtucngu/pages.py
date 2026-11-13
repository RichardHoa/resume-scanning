"""
Page images of a PDF Part and the printed lines on them: each page's lines found on the 300 dpi scan, the page with
their Line Numbers for the layout request, each Entry Span and each of its lines cut from the scan for their own
requests, each Proverb Entry's Entry Image for the export, and the page smaller for the review server. Places on the
page are in px of the 300 dpi scan: a line is [top, bottom, left, right] and a crop [left, top, right, bottom], bottom
and right exclusive.
"""
import os
import unicodedata
from io import BytesIO

import fitz
import numpy as np
from PIL import Image, ImageDraw, ImageFont
from scipy import ndimage

from src.khotangtucngu.settings import (
    BOOK_DIR, EDGE_PX, ENTRY_IMAGE_DPI, ENTRY_IMAGE_PAGE_GAP_PX, ENTRY_IMAGE_RULE_GREY, ENTRY_IMAGE_RULE_PX,
    LABEL_COLOUR, LABEL_PX, LABEL_STRIP_PX, MISSED_INK, MISSED_JOIN_PX, OCR_ABOVE_GAP_PX, OCR_ABOVE_SHARE, OCR_BELOW_PX,
    OCR_PAD_PX, PAGE_DPI, PAGE_IMAGE_LONG_SIDE, SPAN_EDGE_GAP_PX, SPAN_MARGIN_PX
)
from src.providers.page_images import (
    RENDER_LOCK, line_bands, line_ends, page_ink, rule_columns, whole_page, whole_page_at_dpi
)


def part_pdf(name):
    """The path of a Part's PDF in BOOK_DIR, whichever way the file system spells its accents (composed on Linux,
    as copied; decomposed if copied from macOS), or None."""
    for form in ("NFC", "NFD"):
        path = os.path.join(BOOK_DIR, unicodedata.normalize(form, name))
        if os.path.exists(path):
            return path
    return None


def open_pdf(pdf, part):
    """The PDF at `pdf`, of `part` (a settings.Part), with each of its turned_pages turned back straight about its
    centre: its scan is drawn turned, so every image of the page, from its lines to its Entry Images, is of it
    straight."""
    doc = fitz.open(pdf)
    for page, degrees in part.turned_pages:
        p = doc[page - 1]
        box = p.mediabox
        cx, cy = (box.x0 + box.x1) / 2, (box.y0 + box.y1) / 2
        m = fitz.Matrix(1, 0, 0, 1, -cx, -cy) * fitz.Matrix(degrees) * fitz.Matrix(1, 0, 0, 1, cx, cy)
        contents, xref = p.read_contents(), p.get_contents()[0]
        doc.update_stream(xref, f"q {m.a:f} {m.b:f} {m.c:f} {m.d:f} {m.e:f} {m.f:f} cm\n".encode() + contents + b"\nQ")
        p.set_contents(xref)
    return doc


def page_key(page):
    """A PDF page's name in the store: its requests and its page images."""
    return f"p{page:03d}"


def span_key(page, first):
    """An Entry Span's name in the store: its page and the Line Number it starts on."""
    return f"{page_key(page)}-L{first:02d}"


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


def _ink_tops(area, lines, height):
    """For each of `lines`, the top of its ink with the ink just above its band between its ends: rows up from its
    band's top while no more than OCR_ABOVE_GAP_PX of them in a row are blank, within OCR_ABOVE_SHARE of `height` (the
    median line's) and below the line before. A mark over a capital (the hook of Ả) can have too little ink for its
    rows to count in the band."""
    tops, floor = [], 0
    for top, bottom, left, right in lines:
        start = max(floor, top - round(OCR_ABOVE_SHARE * height))
        inked = area[start:top, left:right].any(axis=1)
        ink_top, blank = top, 0
        for row in range(top - 1, start - 1, -1):
            if inked[row - start]:
                ink_top, blank = row, 0
            else:
                blank += 1
                if blank > OCR_ABOVE_GAP_PX:
                    break
        tops.append(ink_top)
        floor = bottom
    return tops


def find_lines(doc, page):
    """
    PDF page `page` (1-based) read on its 300 dpi scan: {"size": [width, height], "lines": the printed lines top to
    bottom, Line Number n being lines[n - 1], "ocr_tops": the top of each line's ink with the ink just above its band
    (`_ink_tops`), for its OCR crop, "missed": the patches of ink outside the page's text block}. A line is a band of
    page_images.line_bands with its ends; one with no run of ink big enough to have ends is left out.
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
    return {"size": [w, h], "lines": lines, "ocr_tops": _ink_tops(area, lines, height),
            "missed": _missed(area, lines)}


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


def in_band(line, bands):
    """Whether the centre of `line` falls inside one of `bands`, a page's Confirmed Spans' [top, bottom] pixel rows."""
    centre = (line[0] + line[1]) / 2
    return any(top <= centre < bottom for top, bottom in bands)


def _clear_of(top, bottom, bands):
    """The pixel rows [top, bottom] cut back off `bands`: a line whose centre is outside a band may still touch it, if
    the line finder changed since the band was made."""
    for band_top, band_bottom in bands:
        if band_top < bottom and top < band_bottom:
            if band_top + band_bottom < top + bottom:
                top = band_bottom
            else:
                bottom = band_top
    return [top, bottom]


def entry_spans(found, answer, bands=()):
    """
    The Entry Spans of a page left to read, top to bottom, from its lines (`found`, from `find_lines`), its checked
    layout answer and `bands`, the [top, bottom] pixel rows of its Confirmed Spans, which own every line whose centre
    falls in them: {"first", "last" (its first and last Line Numbers), "leading" (it begins at no start the model named:
    the lines from body_start above the first start, or below a band, which continue the Proverb Entry above), "box" (its
    crop), "band" (its pixel rows)}. Starts inside a band are ignored, and the first line below one is forced to be a
    start. Every line from body_start down is in exactly one of these or in a band.
    """
    lines, (w, h) = found["lines"], found["size"]
    starts = set(answer["starts"])
    free = [n for n in range(answer["body_start"], len(lines) + 1) if not in_band(lines[n - 1], bands)]
    firsts = [n for k, n in enumerate(free) if n in starts or k == 0 or free[k - 1] != n - 1]
    left, right = _sides(lines, w)
    open_lines, begins = set(free), set(firsts)
    spans = []
    for first in firsts:
        last = first
        while last + 1 in open_lines and last + 1 not in begins:
            last += 1
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
                      "box": [left, max(0, top), right, min(h, bottom)],
                      "band": _clear_of(lines[i][0], lines[j][1], bands)})
    return spans


def line_box(found, n, below_px=OCR_BELOW_PX):
    """The crop of Line Number `n` of a page (`found`, from `find_lines`) for its OCR Reading: its ink band grown up to
    its ocr_top and `below_px` down, for the tone marks and dots under letters the band leaves out, stopping at the
    next line's ocr_top; OCR_PAD_PX around and beyond its own ink ends, so the crop holds the line itself, not the blank
    width of the Entry Span."""
    (w, h), lines = found["size"], found["lines"]
    _, bottom, left, right = lines[n - 1]
    below = bottom + below_px
    if n < len(lines):
        below = max(bottom + OCR_PAD_PX, min(below, found["ocr_tops"][n]))
    return [max(0, left - OCR_PAD_PX), max(0, found["ocr_tops"][n - 1] - OCR_PAD_PX), min(w, right + OCR_PAD_PX),
            min(h, below)]


def index_line_box(found, n):
    """The crop of Line Number `n` of a Topic Index page (`found`, from `find_lines`) for its own request, cut as an
    Entry Span's: across the page's lines and SPAN_MARGIN_PX beyond, and down from its ink's top (its ocr_top) or half
    a margin above its band to half a margin below it, never nearer its neighbours' ink than SPAN_EDGE_GAP_PX, so it
    holds no number of another line."""
    lines, (w, h) = found["lines"], found["size"]
    top, bottom = lines[n - 1][:2]
    left, right = _sides(lines, w)
    half = SPAN_MARGIN_PX // 2
    up = top - half if n == 1 else max(lines[n - 2][1] + SPAN_EDGE_GAP_PX, top - half)
    down = bottom + half if n == len(lines) else min(lines[n][0] - SPAN_EDGE_GAP_PX, bottom + half)
    return [left, max(0, min(up, found["ocr_tops"][n - 1])), right, min(h, max(down, bottom))]


def _crop(doc, page, box, dpi):
    """The part of PDF page `page` (1-based) under `box`, px of its 300 dpi scan, at `dpi` in grayscale, as PNG."""
    with RENDER_LOCK:
        p = doc[page - 1]
        r, scale = p.rect, 72 / PAGE_DPI
        left, top, right, bottom = box
        clip = fitz.Rect(r.x0 + left * scale, r.y0 + top * scale, r.x0 + right * scale, r.y0 + bottom * scale)
        zoom = dpi / 72
        return p.get_pixmap(matrix=fitz.Matrix(zoom, zoom), clip=clip, colorspace=fitz.csGRAY).tobytes("png")


def span_image(doc, page, box):
    """The part of PDF page `page` (1-based) under `box`, px of its 300 dpi scan, at PAGE_DPI in grayscale."""
    return _crop(doc, page, box, PAGE_DPI)


def entry_image(doc, crops):
    """A Proverb Entry's Entry Image, as PNG: `crops`, [(PDF page, box)], one per page in page order, at ENTRY_IMAGE_DPI
    in grayscale, stacked top to bottom with a rule between pages, each padded with white on its right to the widest."""
    pngs = [_crop(doc, page, box, ENTRY_IMAGE_DPI) for page, box in crops]
    if len(pngs) == 1:
        return pngs[0]
    images = [Image.open(BytesIO(png)) for png in pngs]
    width, gap = max(im.width for im in images), ENTRY_IMAGE_PAGE_GAP_PX
    out = Image.new("L", (width, sum(im.height for im in images) + gap * (len(images) - 1)), 255)
    draw, y = ImageDraw.Draw(out), 0
    for k, im in enumerate(images):
        if k:
            rule = y + (gap - ENTRY_IMAGE_RULE_PX) // 2
            draw.rectangle([0, rule, width - 1, rule + ENTRY_IMAGE_RULE_PX - 1], fill=ENTRY_IMAGE_RULE_GREY)
            y += gap
        out.paste(im, (0, y))
        y += im.height
    buf = BytesIO()
    out.save(buf, "PNG")
    return buf.getvalue()


def review_image(doc, page):
    """PDF page `page` (1-based) whole, about PAGE_IMAGE_LONG_SIDE px on its long side, for the review server."""
    return whole_page(doc, page, PAGE_IMAGE_LONG_SIDE)
