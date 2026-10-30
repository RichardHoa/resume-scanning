"""
Assembly: joins the Strips of each Region and the Regions of an Issue into Items, in reading order across columns
and pages, pairs each Article's Footnote calls with its Footnotes, and writes the Issue as Markdown and its Articles
as a CSV. An Item never runs across Issues: each run assembles one Issue.
"""
import csv
import re

from src.nugioichung.placed import PlacedText
from src.nugioichung.regions import ARTICLE, FOOTNOTES, KINDS, warning
from src.nugioichung.transcribe import ends_paragraph, starts_paragraph

NEWSPAPER = "Nữ-Giới-Chung"
FLAG = "⚠"

# Lines of a transcription that are Markdown structure, never the tail or head of a paragraph cut by a boundary
_STRUCTURE = re.compile(r"^(#|\||- |\* |\d+\. |> |\[Hình\])")
# A Footnote call in an Article's text, e.g. "(7)"
_CALL = re.compile(r"\((\d{1,3})\)")
# What parts two blocks of an Item's text
_BLANK_LINE = re.compile(r"\n[ \t]*\n\s*")
# The old datasheet's columns, Chủ đề (topic) left empty
CSV_COLUMNS = ["Chủ đề", "Bài viết", "Tác giả", "Chuyên mục", "Số báo", "Ngày xuất bản", "Nội dung"]


def issue_title(issue):
    return f"{NEWSPAPER} — Số {issue['number']}, {issue['date']}"


def title_key(title):
    """Titles compare without case, hyphens, spacing or closing punctuation, as the layout pass copies them loosely."""
    return re.sub(r"\s+", " ", title.lower().replace("-", " ")).strip(" .:;,")


def _find_item(items, region):
    """The Item a Region carries on, or None if it begins a new one."""
    key = title_key(region.title)
    if key:
        for item in reversed(items):
            # Footnotes with no Article before them make an Item of their own, which only Footnotes carry on
            if title_key(item["title"]) == key and (item["kind"] != FOOTNOTES or region.kind == FOOTNOTES):
                return item
    if region.kind == FOOTNOTES:
        return next((i for i in reversed(items) if i["kind"] == ARTICLE), None)
    if region.continues:
        return next((i for i in reversed(items) if i["kind"] == region.kind), None)
    return None


def join_items(layouts):
    """
    `layouts`: {pdf page: PageLayout}. Returns the Items in reading order, each with its kind, title, section,
    author, pages ((pdf page, printed page number), in order), and its `body` and `footnotes` Regions.
    """
    items = []
    for page in sorted(layouts):
        on_page = (page, layouts[page].printed_page)
        for region in layouts[page].regions:
            is_footnotes = region.kind == FOOTNOTES
            item = _find_item(items, region) if region.continues or is_footnotes else None
            if item is None:
                item = {"kind": region.kind, "title": "", "section": "", "author": "", "pages": [],
                        "body": [], "footnotes": []}
                items.append(item)
            item["title"] = item["title"] or region.title
            item["section"] = item["section"] or region.section
            item["author"] = item["author"] or region.author
            if on_page not in item["pages"]:
                item["pages"].append(on_page)
            item["footnotes" if is_footnotes and item["kind"] != FOOTNOTES else "body"].append(region)
    return items


def _joins(text, piece, prev, answer):
    """
    Whether `piece`, the text of `answer`, carries on the paragraph `text` ends with, across a Strip or Region
    boundary from the cut whose answer is `prev` (None after a gap): when both cuts' printed lines matched, if the
    last line before stops at the right edge and the first after is not indented; else as the read answers flag it.
    """
    if not text or prev is None:
        return False
    if prev["printed"] and answer["printed"]:
        runs_on = not ends_paragraph(prev["printed"][-1]) and not starts_paragraph(answer["printed"][0])
    else:
        runs_on = prev["ends_mid_paragraph"] or answer["starts_mid_paragraph"]
    return runs_on and not _STRUCTURE.match(text.text.rsplit("\n", 1)[-1]) and not _STRUCTURE.match(piece.text)


def _carry_on(text, piece):
    """`text` carried on by `piece`, joined as printed lines are: a hyphen at the end joins with no space."""
    return text + piece if text.endswith("-") else text + " " + piece


def locate(cuts, place):
    """(PDF page, box) of a place in the text: its printed line's box, or its cut's. `cuts`: {cut key: Cut}."""
    key, line = place
    cut = cuts[key]
    return cut.page, (cut.lines[line].box if line is not None else cut.box)


def _gap(cut, why, warnings):
    """The ⚠ gap a request with no transcription leaves in its Item, with its Warning in `warnings`."""
    warnings.append(warning("not_transcribed", cut.key, f"{cut.label} not transcribed: {why}", cut.page, cut.box))
    return PlacedText.at(f"{FLAG} *[{cut.label} not transcribed: {why}]*", (cut.key, None))


def _join_text(regions, transcriptions, warnings, calls=None):
    """
    The text of a list of Regions, Strip by Strip, with a paragraph cut by a Strip or Region boundary joined back
    into one, and a ⚠ gap for each request with no transcription. `calls` rewrites the Footnote calls of each answer.
    """
    text, prev = PlacedText(), None
    for region in regions:
        for cut in region.cuts:
            answer, why = transcriptions[cut.key]
            if answer is None:
                piece = _gap(cut, why, warnings)
                text, prev = (text + "\n\n" + piece if text else piece), None
                continue
            piece = answer["text"]
            if not piece:
                continue
            if calls:
                piece = calls(piece)
            if _joins(text, piece, prev, answer):
                text = _carry_on(text, piece)
            else:
                text = text + "\n\n" + piece if text else piece
            prev = answer
    return text


def _join_footnotes(regions, transcriptions, warnings):
    """
    The Footnotes of a list of Footnotes Regions in printed order, as [number, text], a Footnote cut by a Strip or
    Region boundary (given back with number 0) joined to the one before; [None, ⚠ gap] for a request with no
    transcription.
    """
    notes = []
    for region in regions:
        for cut in region.cuts:
            answer, why = transcriptions[cut.key]
            if answer is None:
                notes.append([None, _gap(cut, why, warnings)])
                continue
            for i, note in enumerate(answer["footnotes"]):
                if i == 0 and note["number"] == 0 and notes and notes[-1][0]:
                    notes[-1][1] = _carry_on(notes[-1][1], note["text"])
                else:
                    notes.append([note["number"], note["text"]])
    return notes


def _place_name(place):
    """A place as part of a Warning's id."""
    key, line = place
    return key if line is None else f"{key}-l{line + 1:02d}"


def _render_item(n, item, transcriptions, cuts, warnings):
    """
    Item number `n`'s blocks: each paragraph (or heading, table, ⚠ gap) of its body, then each of its Footnotes, as
    {kind "paragraph" or "footnote", text as PlacedText, label: the Markdown footnote label of a paired Footnote}.
    Each call "(k)" with a Footnote k of the same Item becomes the Markdown footnote [^n-k] (labels must be unique in
    the Issue); an unpaired call or Footnote is marked ⚠ and given a Warning. Calls are looked for only in an Item
    that has Footnotes.
    """
    where = f"{item_heading(item)} ({pages_label(item['pages'])})"
    first_page = item["pages"][0][0]
    called = set()
    if item["kind"] == FOOTNOTES:
        notes, text = _join_footnotes(item["body"], transcriptions, warnings), PlacedText()
    else:
        notes = _join_footnotes(item["footnotes"], transcriptions, warnings)
        numbers = {k for k, _ in notes if k}

        def calls(piece):
            def call(m):
                k = int(m.group(1))
                if k in numbers:
                    called.add(k)
                    return f"[^{n}-{k}]"
                place = piece.place_at(m.start())
                page, box = locate(cuts, place) if place else (first_page, None)
                warnings.append(warning("unpaired_call", f"{_place_name(place) if place else n}:({k})",
                                        f"Footnote call ({k}) has no Footnote {k}, in {where}", page, box))
                return m.group(0) + FLAG
            return piece.sub(_CALL, call)

        text = _join_text(item["body"], transcriptions, warnings, calls if notes else None)

    blocks = [{"kind": "paragraph", "text": block, "label": None}
              for block in (b.strip() for b in text.split(_BLANK_LINE)) if block]
    written = set()
    for k, note in notes:
        if k is None:
            blocks.append({"kind": "footnote", "text": note, "label": None})
            continue
        if item["kind"] == FOOTNOTES:
            why = "Footnotes with no Article to pair with"
        elif not k:
            why = "Footnote with no number"
        elif k in written:
            why = f"a second Footnote {k}"
        elif k not in called:
            why = f"Footnote {k} has no call ({k}) in the text"
        else:
            written.add(k)
            blocks.append({"kind": "footnote", "text": f"[^{n}-{k}]: " + note, "label": f"{n}-{k}"})
            continue
        place = note.places()[0] if note.places() else None
        page, box = locate(cuts, place) if place else (first_page, None)
        warnings.append(warning("unpaired_footnote", f"{_place_name(place) if place else n}:({k or '?'})",
                                f"{why}, in {where}", page, box))
        blocks.append({"kind": "footnote", "text": f"{FLAG} ({k or '?'}) " + note, "label": None})
    return blocks


def render_items(items, transcriptions, cuts):
    """
    Each Item's blocks (see `_render_item`), and the Warnings of the requests with no transcription and of the
    Footnote calls and Footnotes left unpaired. `transcriptions`: {request key: (answer or None, why it has none)};
    `cuts`: {cut key: Cut}.
    """
    warnings = []
    blocks = [_render_item(n, item, transcriptions, cuts, warnings) for n, item in enumerate(items, 1)]
    return blocks, warnings


def item_text(blocks):
    """An Item's Markdown text, from its blocks."""
    return "\n\n".join(block["text"].text for block in blocks)


def page_numbers(pages):
    """An Item's printed page numbers if every one of its pages prints one, else its PDF page numbers, so a label
    never mixes the two; and the word the label starts with."""
    if all(printed for _, printed in pages):
        return [printed for _, printed in pages], "page"
    return [str(pdf) for pdf, _ in pages], "PDF page"


def pages_label(pages):
    labels, word = page_numbers(pages)
    if len(labels) == 1:
        return f"{word} {labels[0]}"
    if all(label.isdigit() for label in labels):
        nums = [int(label) for label in labels]
        if nums == list(range(nums[0], nums[0] + len(nums))):
            return f"{word}s {nums[0]}–{nums[-1]}"
    return f"{word}s " + ", ".join(labels)


def item_heading(item):
    """Its printed title, or its kind and first page if it has none."""
    labels, word = page_numbers(item["pages"])
    return item["title"] or f"{KINDS[item['kind']].label}, {word} {labels[0]}"


def item_byline(item):
    """The line under its heading: its kind, section, author and pages."""
    return " · ".join(x for x in (KINDS[item["kind"]].label, item["section"], item["author"],
                                  pages_label(item["pages"])) if x)


def issue_markdown(issue, items, texts):
    """The Issue as Markdown, from its Items and their texts (`item_text`)."""
    out = [f"# {issue_title(issue)}"]
    for item, text in zip(items, texts):
        out.append(f"## {item_heading(item)}")
        out.append(f"*{item_byline(item)}*")
        if text:
            out.append(text)
    return "\n\n".join(out) + "\n"


def write_articles_csv(path, issue, items, texts):
    """One row per Article, in the old datasheet's columns. UTF-8 with a BOM, so spreadsheets read the diacritics."""
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        out = csv.writer(f)
        out.writerow(CSV_COLUMNS)
        for item, text in zip(items, texts):
            if item["kind"] == ARTICLE:
                out.writerow(["", item["title"], item["author"], item["section"], issue["number"],
                              issue["published"], text])
