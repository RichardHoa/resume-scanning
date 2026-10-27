"""
Page images of an Issue PDF, rendered with PyMuPDF in grayscale: the whole page small for the layout pass, and a
Region cut at full scan resolution for the transcription pass. Both are PNG, as sent to the model.
"""
import threading

import fitz

from src.nugioichung.settings import CROP_DPI, LAYOUT_LONG_SIDE

# PyMuPDF documents are not thread-safe, and requests build their images in the phase's worker threads
_render_lock = threading.Lock()


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
