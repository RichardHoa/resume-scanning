"""
Layout pass: the model sees each whole page small and returns its Regions in reading order, each with a box, a
kind, its Item's title, section and author, and whether it continues the previous Region of its Item.
"""
from src.nugioichung.pages import layout_image
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


def check_layout(page, answer):
    """
    A page's layout answer as a PageLayout, each Region numbered by its place in the answer (the reading order),
    and the problems with Regions it left out, as dropped log rows.
    """
    regions, problems = [], []
    for n, r in enumerate(answer.get("regions") or [], 1):
        box = [min(1000, max(0, int(v))) for v in (r.get("box") or [])]
        if len(box) != 4 or box[2] - box[0] < MIN_BOX_SIZE or box[3] - box[1] < MIN_BOX_SIZE:
            problems.append({"task": region_label(page, n), "why": f"unusable box {r.get('box')}"})
            continue
        regions.append(Region(
            page=page,
            n=n,
            kind=r.get("kind") if r.get("kind") in KINDS else ARTICLE,
            title=(r.get("title") or "").strip(),
            section=(r.get("section") or "").strip(),
            author=(r.get("author") or "").strip(),
            continues=bool(r.get("continues")),
            box=box,
        ))
    return PageLayout((answer.get("printed_page") or "").strip(), regions), problems
