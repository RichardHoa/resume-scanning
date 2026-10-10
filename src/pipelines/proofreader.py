"""
AI Proofreading Pass over a scanned book's raw pipeline output (book.raw.md from the vsc OCR pipeline).

The book is a list of blocks (the paragraphs between blank lines). The pass suggests AI Proposals in two
phases, each made of independent tasks run in parallel:

  Phase 1  one task per scanned page: fixes the blocks that start on that page against its image
  Phase 2  one task per Note, on the Phase 1 output: places the Note Call and fixes the Note Definition

This module holds the parts that need no model: applying task results to the blocks and logging each
change as an AI Proposal in the shape of the review tool's corrections.jsonl.
"""
import re
from typing import Dict, List, NamedTuple, Optional

HEADING = re.compile(r"^(#{1,6})\s+(.*)$")
_call = re.compile(r"\[\^([^\]\s]+)\]")
_note_ref = re.compile(r"\[\^[^\]\s]+\]:?")
NOTE_DEF = re.compile(r"^\[\^([^\]\s]+)\]:\s?(.*)$", re.S)
FLAG = "⚠"
_flag_end = re.compile(r"\s*⚠$")
_trailing_comment = re.compile(r"\s*<!--.*?-->\s*$", re.S)


class Applied(NamedTuple):
    blocks: List[str]
    proposals: List[dict]
    # Result items not applied: {task, item, why}
    dropped: List[dict]
    # Each block of `blocks` that is on the scans -> its pages
    pages: Dict[int, List[int]]


def model_text(block: str) -> str:
    """The block as the model sees it: without its trailing `<!-- ... -->` comment, which is pipeline bookkeeping."""
    return _trailing_comment.sub("", block)


def _with_comment(original: str, text: str) -> str:
    """The model's text for a block with the block's trailing comment put back."""
    m = _trailing_comment.search(original)
    return text + m.group(0) if m and "<!--" not in text else text


def _kind(block: str) -> str:
    if HEADING.match(block):
        return "heading"
    if block.startswith("<!--"):
        return "comment"
    if NOTE_DEF.match(block):
        return "note"
    return "text"


def joined(a: str, b: str) -> str:
    """Two blocks as one paragraph, as the vsc pipeline joins a paragraph split by a page."""
    flagged = a.endswith(FLAG) or b.endswith(FLAG)
    a, b = _flag_end.sub("", a), _flag_end.sub("", b)
    b = b[1:] if b.startswith("\\") else b
    if a.endswith("-") and len(a) > 1 and a[-2].isalpha() and b[:1].islower():
        out = a + b
    else:
        out = a + " " + b
    return out + (" " + FLAG if flagged else "")


def _section_titles(blocks: List[str]) -> List[str]:
    """For each block, the title of the heading it falls under (note calls removed), as the review tool names it."""
    titles, title = [], "(trước tiêu đề)"
    for b in blocks:
        m = HEADING.match(b)
        if m:
            title = _note_ref.sub("", m.group(2)).strip()
        titles.append(title)
    return titles


def apply_page_results(blocks: List[str], pages: Dict[int, List[int]], results: Dict[int, List[dict]]) -> Applied:
    """
    Applies Phase 1 results ({page: [{block, action, after, reason}]}) to `blocks`. `pages` maps each block a
    page task may change to the pages it is on; the first is the page that owns it.
    """
    titles = _section_titles(blocks)
    out: List[Optional[str]] = list(blocks)    # None: deleted
    on: List[List[int]] = [list(pages.get(i, [])) for i in range(len(blocks))]
    proposals, dropped, merges = [], [], []
    for page in sorted(results):
        for item in results[page]:
            i = item["block"]
            owner = pages[i][0] if i in pages else None
            if owner != page:
                why = f"block {i} is owned by page {owner}" if owner else f"block {i} is on no page"
                dropped.append({"task": f"page {page}", "item": item, "why": why})
                continue
            if item["action"] == "merge_next":
                merges.append((page, item))
            after = None if item["action"] == "delete" else _with_comment(blocks[i], item["after"])
            if after == blocks[i]:
                continue
            proposals.append({
                "action": "delete" if after is None else "edit", "section": titles[i], "pdf_pages": pages[i],
                "before": [blocks[i]], "after": [] if after is None else [after], "reason": item["reason"]
            })
            out[i] = after

    # Last first, so a paragraph split over three pages joins up whole
    for page, item in sorted(merges, key=lambda m: -m[1]["block"]):
        i = item["block"]
        nxt = i + 1
        if nxt >= len(out) or out[nxt] is None or _kind(out[nxt]) != "text" or _kind(out[i]) != "text":
            dropped.append({"task": f"page {page}", "item": item, "why": f"block {nxt} is not a paragraph to merge into"})
            continue
        before = [out[i], out[nxt]]
        out[i], out[nxt] = joined(out[i], out[nxt]), None
        on[i] = sorted(set(on[i]) | set(on[nxt]))
        proposals.append({
            "action": "merge", "section": titles[i], "pdf_pages": on[i],
            "before": before, "after": [out[i]], "reason": item["reason"]
        })
    kept = [i for i, b in enumerate(out) if b is not None]
    return Applied([out[i] for i in kept], proposals, dropped, {k: on[i] for k, i in enumerate(kept) if on[i]})


def apply_note_results(blocks: List[str], pages: Dict[int, List[int]], results: Dict[str, dict]) -> Applied:
    """
    Applies Phase 2 results ({note_id: {replacements: [{block, find, replace}], definition, reason}}) to the
    Phase 1 output. A replacement applies only where its `find` is in its block exactly once, so several notes
    in one paragraph combine. `definition` (or None) is the Note Definition's new text, without `[^id]: `.
    """
    titles = _section_titles(blocks)
    out = list(blocks)
    proposals, dropped = [], []

    def change(i: int, after: str, reason: str) -> None:
        if after != out[i]:
            proposals.append({"action": "edit", "section": titles[i], "pdf_pages": pages.get(i, []),
                              "before": [out[i]], "after": [after], "reason": reason})
            out[i] = after

    for note_id in sorted(results):
        result = results[note_id]
        for item in result["replacements"]:
            i = item["block"]
            count = out[i].count(item["find"]) if 0 <= i < len(out) and item["find"] else 0
            foreign = sorted(set(_call.findall(item["replace"])) - set(_call.findall(item["find"])) - {note_id})
            if foreign:
                why = f"the replacement adds a call to [^{foreign[0]}], not [^{note_id}]"
            elif count != 1:
                why = f"'{item['find']}' is in block {i} {count} times, not once"
            else:
                why = None
            if why:
                dropped.append({"task": f"note {note_id}", "item": item, "why": why})
                continue
            change(i, out[i].replace(item["find"], item["replace"]), result["reason"])

        d = next((k for k, b in enumerate(out) if b.startswith(f"[^{note_id}]:")), None)
        if d is None:
            continue
        after = out[d]
        if result.get("definition"):
            after = _with_comment(after, f"[^{note_id}]: {result['definition'].strip()}")
        if any(f"[^{note_id}]" in b and k != d for k, b in enumerate(out)):
            after = after.replace(" · call not found", "")
        change(d, after, result["reason"])
    return Applied(out, proposals, dropped, dict(pages))


# -- tasks
NOTE_PAGE = re.compile(r"<!--\s*note pdf (\d+)")
# A story up to this long is shown whole to a note task; a longer one only around the term the note explains
WHOLE_STORY_MAX_CHARS = 30000


def block_pages(manifest: List[dict]) -> Dict[int, List[int]]:
    """Each block in the pages.jsonl manifest -> its pages (the first owns it)."""
    return {o["i"]: o["pages"] for entry in manifest for o in entry["own"]}


def page_task(blocks: List[str], entry: dict) -> dict:
    """
    One Phase 1 task from a pages.jsonl line: the blocks the page owns, every page they are on (the images to
    send), the paragraphs just before and after them and the ones continued from an earlier page (read-only).
    """
    own = [o["i"] for o in entry["own"]]
    images = sorted({p for o in entry["own"] for p in o["pages"]})
    owned = set(own)

    def text_at(i):
        return (i, model_text(blocks[i])) if 0 <= i < len(blocks) and _kind(blocks[i]) == "text" else None

    before = text_at(own[0] - 1) if own[0] - 1 not in owned and own[0] - 1 not in entry["continued"] else None
    after = text_at(own[-1] + 1) if own[-1] + 1 not in owned else None
    return {
        "page": entry["page"], "own": own, "images": images,
        "owned_text": [(i, model_text(blocks[i])) for i in own],
        "continued": [(i, model_text(blocks[i])) for i in entry["continued"]],
        "before": before, "after": after,
    }


def _folded(s: str) -> str:
    """Lower-case letters without diacritics, so "Pụ" finds "pu" and "P Tao-lu-pu" finds "ptaolupu"."""
    import unicodedata
    s = unicodedata.normalize("NFD", s.lower().replace("đ", "d"))
    return "".join(c for c in s if c.isalnum() and not unicodedata.combining(c))


def note_tasks(blocks: List[str], pages: Dict[int, List[int]]) -> List[dict]:
    """
    One Phase 2 task per Note Definition in `blocks`: the definition, the page it is printed on, and the story
    paragraphs the call may be in (the whole story when it is short, else the paragraphs mentioning the term the
    note explains, those on the note's page and the page before, and any already holding the call, each with its
    neighbours).
    """
    titles = _section_titles(blocks)
    tasks = []
    for d, block in enumerate(blocks):
        m = NOTE_DEF.match(block)
        if not m:
            continue
        note_id = m.group(1)
        definition = model_text(m.group(2))
        page_m = NOTE_PAGE.search(block)
        note_page = int(page_m.group(1)) if page_m else (pages.get(d) or [None])[0]
        story = [i for i, b in enumerate(blocks) if titles[i] == titles[d] and _kind(b) in ("text", "heading")]
        whole = sum(len(blocks[i]) for i in story) <= WHOLE_STORY_MAX_CHARS
        if whole:
            chosen = story
        else:
            term = _folded(definition.split(":")[0]) if ":" in definition else ""
            near = {note_page, note_page - 1} if note_page else set()
            hits = [i for i in story
                    if (term and len(term) >= 2 and term in _folded(blocks[i]))
                    or f"[^{note_id}]" in blocks[i] or near & set(pages.get(i, []))]
            story_set = set(story)
            chosen = sorted({j for i in hits for j in (i - 1, i, i + 1) if j in story_set})
        tasks.append({
            "note_id": note_id, "definition_block": d, "definition": definition, "note_page": note_page,
            "candidates": [(i, model_text(blocks[i])) for i in chosen], "whole_story": whole,
        })
    return tasks
