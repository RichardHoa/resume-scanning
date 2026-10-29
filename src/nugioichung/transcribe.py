"""
Transcription pass: each Region is cut from the full 300 dpi scan and transcribed as a Faithful Transcription, whole
or Strip by Strip if it is tall. A Footnotes Region answers as a list of Footnotes.
"""
import re

from src.nugioichung.pages import crop_image
from src.nugioichung.prompts import (
    TRANSCRIBE_SYSTEM_PROMPT, footnotes_schema, transcribe_schema, transcribe_user_text
)
from src.nugioichung.regions import FOOTNOTES
from src.providers.vlm_requests import Request, data_url, image_messages, sha1

# A run of more than three dots, spaces between them or not. The prompt asks for `...`; a run the model copies dot by
# dot anyway is collapsed here, not by a schema pattern: vLLM's grammar engine computes a regex this ambiguous on the
# CPU for every token of every request, which slowed decoding about 60-fold
DOT_RUN = re.compile(r"\.(?: *\.){3,}")


def cut_stamp(region, cut):
    """What a Region's or Strip's transcription depends on beyond the pass's stamp: its crop and its prompt."""
    return {"user_sha1": sha1(transcribe_user_text(region, cut)), "box": cut.box}


def transcribe_requests(doc, layouts, pages):
    """One request per Region, or per Strip of a tall Region, of each of `pages` that has a layout."""
    for page in pages:
        if page not in layouts:
            continue
        for region in layouts[page].regions:
            schema = footnotes_schema() if region.kind == FOOTNOTES else transcribe_schema()
            for cut in region.cuts:
                text = transcribe_user_text(region, cut)
                label = f"{'Strip' if cut.strip else 'Region'} cut from PDF page {page}:"
                yield Request(cut.key, (
                    lambda page=page, box=cut.box, label=label, text=text: image_messages(
                        TRANSCRIBE_SYSTEM_PROMPT, [(label, data_url(crop_image(doc, page, box), "image/png"))], text)
                ), schema, cut_stamp(region, cut))


def check_transcription(region, answer):
    """A Region's or Strip's answer, with `text`, or for a Footnotes Region `footnotes` as {number, text}."""
    checked = {
        "starts_mid_paragraph": bool(answer.get("starts_mid_paragraph")),
        "ends_mid_paragraph": bool(answer.get("ends_mid_paragraph")),
    }
    if region.kind == FOOTNOTES:
        checked["footnotes"] = [{"number": max(0, int(f.get("number") or 0)), "text": _clean(f.get("text"))}
                                for f in answer.get("footnotes") or [] if _clean(f.get("text"))]
    else:
        checked["text"] = _clean(answer.get("text"))
    return checked


def _clean(text):
    return DOT_RUN.sub("...", text or "").strip()
