"""
Assembly: joins the Regions of an Issue into Items, in reading order across columns and pages, and writes the Issue
as Markdown. An Item never runs across Issues: each run assembles one Issue.
"""
import re

from src.nugioichung.regions import ARTICLE, FOOTNOTES, KINDS

NEWSPAPER = "Nữ-Giới-Chung"
FLAG = "⚠"

# Lines of a transcription that are Markdown structure, never the tail or head of a paragraph cut by a boundary
_STRUCTURE = re.compile(r"^(#|\||- |\* |\d+\. |\[Hình\])")


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
            if title_key(item["title"]) == key:
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


def _joins(text, piece, answer, prev_ends):
    """Whether `piece` carries on the paragraph `text` ends with, across a Region boundary."""
    if not text or not (prev_ends or answer["starts_mid_paragraph"]):
        return False
    return not _STRUCTURE.match(text.rsplit("\n", 1)[-1]) and not _STRUCTURE.match(piece)


def _join_regions(parts, transcriptions, gaps):
    """The text of a list of Regions, with a ⚠ gap for each Region that has no transcription."""
    text, prev_ends = "", False
    for region in parts:
        answer, why = transcriptions[region.key]
        if answer is None:
            piece = f"{FLAG} *[Region {region.n} of PDF page {region.page} not transcribed: {why}]*"
            gaps.append({"task": region.label, "why": why})
            text, prev_ends = (text + "\n\n" + piece if text else piece), False
            continue
        piece = answer["text"]
        if not piece:
            continue
        if _joins(text, piece, answer, prev_ends):
            text += piece if text.endswith("-") else " " + piece
        else:
            text = text + "\n\n" + piece if text else piece
        prev_ends = answer["ends_mid_paragraph"]
    return text


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


def issue_markdown(issue, items, transcriptions):
    """
    The Issue as Markdown, and the dropped log rows of its Regions with no transcription. `transcriptions`:
    {Region key: (answer or None, why it has none)}.
    """
    gaps = []
    out = [f"# {issue_title(issue)}"]
    for item in items:
        kind = KINDS[item["kind"]].label
        labels, word = page_numbers(item["pages"])
        heading = item["title"] or f"{kind}, {word} {labels[0]}"
        out.append(f"## {heading}")
        out.append("*" + " · ".join(x for x in (kind, item["section"], item["author"], pages_label(item["pages"])) if x)
                   + "*")
        for parts in (item["body"], item["footnotes"]):
            text = _join_regions(parts, transcriptions, gaps)
            if text:
                out.append(text)
    return "\n\n".join(out) + "\n", gaps
