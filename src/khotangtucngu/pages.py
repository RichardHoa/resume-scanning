"""
Page images of a PDF Part: each page whole at PAGE_DPI, as sent to the model, and smaller for the review server.
"""
from src.khotangtucngu.settings import PAGE_DPI, PAGE_IMAGE_LONG_SIDE
from src.providers.page_images import whole_page, whole_page_at_dpi


def page_key(page):
    """A PDF page's name in the store: its request and its page image."""
    return f"p{page:03d}"


def request_image(doc, page):
    """PDF page `page` (1-based) whole at PAGE_DPI."""
    return whole_page_at_dpi(doc, page, PAGE_DPI)


def review_image(doc, page):
    """PDF page `page` (1-based) whole, about PAGE_IMAGE_LONG_SIDE px on its long side, for the review server."""
    return whole_page(doc, page, PAGE_IMAGE_LONG_SIDE)
