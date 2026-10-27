"""
Transcription pass: each Region is cut from the full 300 dpi scan and transcribed whole as a Faithful Transcription.
"""
from src.nugioichung.pages import crop_image
from src.nugioichung.prompts import TRANSCRIBE_SYSTEM_PROMPT, transcribe_schema, transcribe_user_text
from src.providers.vlm_requests import Request, data_url, image_messages, sha1


def region_stamp(region):
    """What a Region's transcription depends on beyond the pass's stamp: its crop and its prompt."""
    return {"user_sha1": sha1(transcribe_user_text(region)), "box": region.box}


def transcribe_requests(doc, layouts, pages):
    """One request per Region of each of `pages` that has a layout."""
    schema = transcribe_schema()
    for page in pages:
        if page not in layouts:
            continue
        for region in layouts[page].regions:
            text = transcribe_user_text(region)
            yield Request(region.key, (
                lambda page=page, box=region.box, text=text: image_messages(
                    TRANSCRIBE_SYSTEM_PROMPT,
                    [(f"Region cut from PDF page {page}:", data_url(crop_image(doc, page, box), "image/png"))], text)
            ), schema, region_stamp(region))


def check_transcription(answer):
    return {
        "text": (answer.get("text") or "").strip(),
        "starts_mid_paragraph": bool(answer.get("starts_mid_paragraph")),
        "ends_mid_paragraph": bool(answer.get("ends_mid_paragraph")),
    }
