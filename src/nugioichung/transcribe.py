"""
Transcription pass: each Region is cut from the full 300 dpi scan and transcribed as a Faithful Transcription, whole
or Strip by Strip if it is tall, in two requests: a read request copies its printed lines exactly, and a format
request writes the same text as Markdown. Code checks the format request changed no letter. A Footnotes Region needs
no format request: code splits its lines into Footnotes.
"""
import re
import unicodedata

from src.nugioichung.pages import crop_image
from src.nugioichung.prompts import (
    FORMAT_SYSTEM_PROMPT, READ_SYSTEM_PROMPT, format_schema, format_user_text, read_schema, read_user_text
)
from src.nugioichung.regions import FOOTNOTES
from src.providers.vlm_requests import Request, data_url, image_messages, sha1

# A run of more than three dots, spaces between them or not. The prompt asks for `...`; a run the model copies dot by
# dot anyway is collapsed here, not by a schema pattern: vLLM's grammar engine computes a regex this ambiguous on the
# CPU for every token of every request, which slowed decoding about 60-fold
DOT_RUN = re.compile(r"\.(?: *\.){3,}")
# A line of `text` that starts on a line of its own: a heading, table row, list item, line of verse or picture
_OWN_LINE = re.compile(r"^\s*(#|\||- |\* |\d+\. |> |\[Hình\])")
# A line the next line never joins: all of the above but a list item, which a wrapped entry carries on
_ENDS_LINE = re.compile(r"^\s*(#|\||> |\[Hình\])")
# What the letter check ignores: what formatting adds or moves (whitespace, Markdown marks), and hyphens and dots,
# which the format request may drop at a joined line's end or between a table's label and figure
_NOT_LETTERS = re.compile(r"[\s#>*_|`\\:.\-]")
# A read line that begins a Footnote: its number in parentheses
_FOOTNOTE = re.compile(r"^\((\d{1,3})\)\s*")


def _crop_request(doc, region, cut, system, text, schema, stamp):
    """A request that sends a Region's or Strip's crop of `doc`, the Issue PDF, with `text`."""
    label = f"{'Strip' if cut.strip else 'Region'} cut from PDF page {region.page}:"
    return Request(cut.key, (
        lambda page=region.page, box=cut.box: image_messages(
            system, [(label, data_url(crop_image(doc, page, box), "image/png"))], text)
    ), schema, stamp)


def read_stamp(region, cut):
    """What a read answer depends on beyond the pass's stamp: its crop and its prompt."""
    return {"user_sha1": sha1(read_user_text(region, cut)), "box": cut.box}


def format_stamp(region, cut, read):
    """What a format answer depends on beyond the pass's stamp: its crop and its prompt, the read lines included."""
    return {"user_sha1": sha1(format_user_text(region, cut, read["lines"])), "box": cut.box}


def needs_format(region, read):
    return region.kind != FOOTNOTES and bool(read["lines"])


def read_requests(doc, layouts, pages):
    """One read request per Region, or per Strip of a tall Region, of each of `pages` that has a layout."""
    schema = read_schema()
    for page in pages:
        for region in layouts[page].regions if page in layouts else []:
            for cut in region.cuts:
                yield _crop_request(doc, region, cut, READ_SYSTEM_PROMPT, read_user_text(region, cut), schema,
                                    read_stamp(region, cut))


def format_requests(doc, layouts, pages, reads):
    """One format request per cut of `pages` with a read answer to format. `reads`: {cut key: (read or None, why)}."""
    schema = format_schema()
    for page in pages:
        for region in layouts[page].regions if page in layouts else []:
            for cut in region.cuts:
                read, _ = reads[cut.key]
                if read is None or not needs_format(region, read):
                    continue
                yield _crop_request(doc, region, cut, FORMAT_SYSTEM_PROMPT,
                                    format_user_text(region, cut, read["lines"]), schema,
                                    format_stamp(region, cut, read))


def check_read(answer):
    """A read answer: its non-empty `lines`, dot runs collapsed, and its two flags."""
    lines = [DOT_RUN.sub("...", line or "").strip() for line in answer.get("lines") or []]
    return {
        "lines": [line for line in lines if line],
        "starts_mid_paragraph": bool(answer.get("starts_mid_paragraph")),
        "ends_mid_paragraph": bool(answer.get("ends_mid_paragraph")),
    }


def transcription(region, read, formatted, why):
    """
    A Region's or Strip's transcription from its read answer and, unless it needs none, its format answer
    (`formatted`, or None and `why` it has none): `text`, or for a Footnotes Region `footnotes` as {number, text},
    with the read answer's two flags. Also why the format answer was not used, or None.
    """
    checked = {k: read[k] for k in ("starts_mid_paragraph", "ends_mid_paragraph")}
    if region.kind == FOOTNOTES:
        checked["footnotes"] = _split_footnotes(read["lines"])
        return checked, None
    if not needs_format(region, read):
        checked["text"] = ""
        return checked, None
    if formatted is not None:
        text = _join_lines(DOT_RUN.sub("...", formatted.get("text") or "").strip())
        if _letters(text) == _letters("".join(read["lines"])):
            checked["text"] = text
            return checked, None
        why = "the format answer changed the read letters"
    else:
        why = f"no format answer ({why})"
    checked["text"] = _join_lines("\n".join(read["lines"]))
    return checked, f"{why}: its read lines are joined by code instead"


def _letters(text):
    return _NOT_LETTERS.sub("", unicodedata.normalize("NFC", text))


def _carry_on(text, line):
    """`text` carried on by the printed line after it: a hyphen at the end joins with no space."""
    if not text:
        return line
    return text + line if text.endswith("-") else text + " " + line


def _split_footnotes(lines):
    """A Footnotes Region's read lines as Footnotes, one begun at each "(n)" at a line's start; lines before the
    first are a Footnote carried on from before, number 0."""
    notes = []
    for line in lines:
        m = _FOOTNOTE.match(line)
        if m:
            notes.append({"number": int(m.group(1)), "text": line[m.end():]})
        elif notes:
            notes[-1]["text"] = _carry_on(notes[-1]["text"], line)
        else:
            notes.append({"number": 0, "text": line})
    return [note for note in notes if note["text"]]


def _join_lines(text):
    """
    `text` with each paragraph on one line. The model often keeps the printed line breaks inside a paragraph, which
    cut its sentences in the Issue's Markdown: a line carries on the line before it, with a space or, after a hyphen,
    none, unless either is Markdown structure or a blank line parts them.
    """
    lines = []
    for line in text.split("\n"):
        line = line.rstrip()
        if line and lines and lines[-1] and not _OWN_LINE.match(line) and not _ENDS_LINE.match(lines[-1]):
            lines[-1] = _carry_on(lines[-1], line.lstrip())
        else:
            lines.append(line)
    return "\n".join(lines)
