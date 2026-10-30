"""
Page images of a scanned PDF, rendered with PyMuPDF in grayscale PNG, shared by Nữ Giới Chung (src/nugioichung) and
Kho tàng tục ngữ (src/khotangtucngu).
"""
import threading

import fitz

# PyMuPDF documents are not thread-safe, and requests build their images in the phase's worker threads
RENDER_LOCK = threading.Lock()


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
