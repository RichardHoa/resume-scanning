"""
Layout pass: the model sees each whole page small and returns its Regions in reading order, each with a box, a
kind, its Item's title, section and author, and whether it continues the previous Region of its Item. Code then
moves each box's edges onto column gaps and printed rules, cuts a tall Region into Strips, and finds printed text the
Regions missed.
"""
from src.nugioichung.pages import layout_image, page_ink, snap_box, strip_boxes, text_outside
from src.nugioichung.prompts import LAYOUT_SYSTEM_PROMPT, layout_schema, layout_user_text
from src.nugioichung.regions import ARTICLE, KINDS, PageLayout, Region, page_key, region_label
from src.providers.vlm_requests import Request, data_url, image_messages, sha1

# A box narrower or shorter than this, in thousandths of the page, holds no line of text
MIN_BOX_SIZE = 5


def page_stamp(page):
    """What a page's layout answer depends on beyond the pass's stamp."""
    return {"user_sha1": sha1(layout_user_text(page))}


def layout_requests(doc, pages):
    schema = layout_schema()
    for page in pages:
        text = layout_user_text(page)
        yield Request(page_key(page), (
            lambda page=page, text=text: image_messages(
                LAYOUT_SYSTEM_PROMPT, [(f"Scan of PDF page {page}:", data_url(layout_image(doc, page), "image/png"))],
                text)
        ), schema, page_stamp(page))


def _usable(box):
    return len(box) == 4 and box[2] - box[0] >= MIN_BOX_SIZE and box[3] - box[1] >= MIN_BOX_SIZE


def check_layout(doc, page, answer):
    """
    A page's layout answer as a PageLayout, each Region numbered by its place in the answer (the reading order), its
    box snapped onto the scan's gaps and rules (kept as given if snapping would leave no box) and cut into Strips if
    tall, with the printed text outside every Region; and the problems with Regions it left out, as dropped log rows.
    """
    ink = page_ink(doc, page)
    regions, problems = [], []
    for n, r in enumerate(answer.get("regions") or [], 1):
        box = [min(1000, max(0, int(v))) for v in (r.get("box") or [])]
        if not _usable(box):
            problems.append({"task": region_label(page, n), "why": f"unusable box {r.get('box')}"})
            continue
        snapped = snap_box(ink, box)
        if not _usable(snapped):
            snapped = box
        regions.append(Region(
            page=page,
            n=n,
            kind=r.get("kind") if r.get("kind") in KINDS else ARTICLE,
            title=(r.get("title") or "").strip(),
            section=(r.get("section") or "").strip(),
            author=(r.get("author") or "").strip(),
            continues=bool(r.get("continues")),
            box=snapped,
            layout_box=box,
            strips=strip_boxes(ink, snapped),
        ))
    outside = text_outside(ink, [r.box for r in regions])
    return PageLayout((answer.get("printed_page") or "").strip(), regions, outside), problems
