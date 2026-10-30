"""
Transcription pass: each Region is cut from the full 300 dpi scan and transcribed as a Faithful Transcription, whole
or Strip by Strip if it is tall, in two requests: a read request copies its printed lines exactly, and a format
request writes the same text as Markdown. When the read lines match the printed lines found on the scan one for one,
code first joins them into paragraphs from where each printed line starts and stops, and the format request is given
those paragraphs to refine (docs/adr/0002-paragraphs-from-line-geometry.md). Code checks the format request changed
no letter, and places each stretch of the text on the printed line it was read from. A Footnotes Region needs no
format request: code splits its lines into Footnotes.
"""
import re
import unicodedata

from src.nugioichung.pages import crop_image
from src.nugioichung.placed import PlacedText
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
# How the read request writes a printed picture
PICTURE = "[Hình]"


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
    """What a format answer depends on beyond the pass's stamp: its crop and its prompt, the read lines or the
    paragraphs code joined them into included."""
    return {"user_sha1": sha1(format_user_text(region, cut, read)), "box": cut.box}


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
                yield _crop_request(doc, region, cut, FORMAT_SYSTEM_PROMPT, format_user_text(region, cut, read),
                                    schema, format_stamp(region, cut, read))


def check_read(answer, cut):
    """
    A read answer of `cut`: its non-empty `lines`, dot runs collapsed, and its two flags; `printed`, the cut's printed
    lines if they match the read lines one for one (as many, a picture where `[Hình]` is read), else None; and
    `paragraphs`, the read lines joined by code from the printed lines, or None if they don't match.
    """
    lines = [DOT_RUN.sub("...", line or "").strip() for line in answer.get("lines") or []]
    lines = [line for line in lines if line]
    matched = len(cut.lines) == len(lines) and all(p.picture == (line == PICTURE) for p, line in zip(cut.lines, lines))
    return {
        "lines": lines,
        "starts_mid_paragraph": bool(answer.get("starts_mid_paragraph")),
        "ends_mid_paragraph": bool(answer.get("ends_mid_paragraph")),
        "printed": cut.lines if matched else None,
        "paragraphs": _paragraphs(lines, cut.lines) if matched else None,
    }


def starts_paragraph(line):
    """Whether printed line `line` begins a paragraph: it is indented, centred or a picture."""
    return line.indented or line.centred or line.picture


def ends_paragraph(line):
    """Whether printed line `line` ends a paragraph: it stops short, or is centred or a picture."""
    return line.short or line.centred or line.picture


def _paragraphs(lines, printed):
    """The read `lines` joined into paragraphs at the breaks their `printed` lines show; any other line carries on the
    one before it."""
    paragraphs = []
    for i, line in enumerate(lines):
        if paragraphs and not (starts_paragraph(printed[i]) or ends_paragraph(printed[i - 1])):
            paragraphs[-1] = _carry_on(paragraphs[-1], line)
        else:
            paragraphs.append(line)
    return paragraphs


def transcription(region, cut, read, formatted, why):
    """
    A Region's or Strip's transcription from its read answer and, unless it needs none, its format answer
    (`formatted`, or None and `why` it has none): `text`, or for a Footnotes Region `footnotes` as {number, text},
    as PlacedText, with the read answer's two flags and its matched printed lines (`printed`, or None). Also why the
    format answer was not used, or None. The text with no format answer is the paragraphs code joined, or if the
    printed lines didn't match, the read lines joined by code.
    """
    checked = {k: read[k] for k in ("starts_mid_paragraph", "ends_mid_paragraph", "printed")}
    matched = read["printed"] is not None
    if region.kind == FOOTNOTES:
        checked["footnotes"] = _split_footnotes(read["lines"], cut.key, matched)
        return checked, None
    if not needs_format(region, read):
        checked["text"] = PlacedText()
        return checked, None
    if formatted is not None:
        text = _join_lines(DOT_RUN.sub("...", formatted.get("text") or "").strip())
        if _letters(text) == _letters("".join(read["lines"])):
            checked["text"] = _placed(text, read["lines"], cut.key, matched)
            return checked, None
        why = "the format answer changed the read letters"
    else:
        why = f"no format answer ({why})"
    if matched:
        text, instead = "\n\n".join(read["paragraphs"]), "the paragraphs code joined are used instead"
    else:
        text, instead = _join_lines("\n".join(read["lines"])), "its read lines are joined by code instead"
    checked["text"] = _placed(text, read["lines"], cut.key, matched)
    return checked, f"{why}: {instead}"


def _letters(text):
    return _NOT_LETTERS.sub("", unicodedata.normalize("NFC", text))


def _is_letter(c):
    return not _NOT_LETTERS.match(c)


def _placed(text, lines, key, matched):
    """
    `text`, which has the letters of the read `lines`, as PlacedText of cut `key`: each stretch placed on the read
    line its letters came from, walking its letters against theirs as the letter check counts them, or if the cut's
    printed lines didn't match, all of it on the whole cut. Marks between letters of two lines go with the first up to
    a space and with the second from it; marks before a text line's first letter go with it, and after its last with
    that.
    """
    text = unicodedata.normalize("NFC", text)
    if not matched:
        return PlacedText.at(text, (key, None))
    owner = [i for i, line in enumerate(lines) for c in unicodedata.normalize("NFC", line) if _is_letter(c)]
    line_of, k = [None] * len(text), 0
    for at, c in enumerate(text):
        if _is_letter(c):
            line_of[at] = owner[k] if k < len(owner) else None
            k += 1
    start = 0
    for row in text.split("\n"):
        letters = [at for at in range(start, start + len(row)) if _is_letter(text[at])]
        for before, after in zip([None] + letters, letters + [None]) if letters else []:
            marks = range(start if before is None else before + 1, start + len(row) if after is None else after)
            if before is None or after is None:
                for at in marks:
                    line_of[at] = line_of[after if before is None else before]
                continue
            space = next((at for at in marks if text[at].isspace()), after)
            for at in marks:
                line_of[at] = line_of[before] if at < space else line_of[after]
        start += len(row) + 1
    spans = []
    for at, line in enumerate(line_of):
        if line is None:
            continue
        if spans and spans[-1][1] == at and spans[-1][2] == (key, line):
            spans[-1][1] = at + 1
        else:
            spans.append([at, at + 1, (key, line)])
    return PlacedText(text, [tuple(span) for span in spans])


def _carry_on(text, line):
    """`text` (a string or PlacedText) carried on by the printed line after it: a hyphen at the end joins with no
    space."""
    if not text:
        return line
    return text + line if text.endswith("-") else text + " " + line


def _split_footnotes(lines, key, matched):
    """A Footnotes Region's (or Strip's) read lines as Footnotes, one begun at each "(n)" at a line's start, each
    stretch placed on its line of cut `key` (on the whole cut if its printed lines didn't match); lines before the
    first are a Footnote carried on from before, number 0."""
    notes = []
    for i, line in enumerate(lines):
        place = (key, i if matched else None)
        m = _FOOTNOTE.match(line)
        if m:
            notes.append({"number": int(m.group(1)), "text": PlacedText.at(line[m.end():], place)})
        elif notes:
            notes[-1]["text"] = _carry_on(notes[-1]["text"], PlacedText.at(line, place))
        else:
            notes.append({"number": 0, "text": PlacedText.at(line, place)})
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
