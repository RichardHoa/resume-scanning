"""
AI Proofreading Pass over a scanned book: the vsc OCR pipeline's book.raw.md, with the folder that
`python -m vsc_ocr prepare-ai <book>` writes (page images, OCR lines, notes). Two phases of independent tasks
run in parallel:

  Phase 1  one task per scanned page: the model transcribes the page, with its OCR lines as a draft
  Phase 2  one task per Note the code could not pair with its Note Call: the model places the call

This module holds the parts that need no model:

  read_page            a Phase 1 answer checked against the page's OCR lines: an OCR line the transcription
                       leaves out comes back as a `⚠ ai-missed?` paragraph, transcribed text with no OCR line
                       under it is flagged ⚠, and each block gets the boxes of the lines it covers
  assemble             the pages joined into book.ai.md in the shape of book.raw.md: the Story Titles (titles.yaml)
                       as set, else the raw headings, each with
                       its `<!-- pdf a-b -->` comment, paragraphs split by a page joined, Note Calls paired with
                       their Note Definitions; logged as AI Proposals (a block diff of book.raw.md)
  story_names          each story's names as the OCR prints them most, with the book's Spelling Rules
                       (spellings.yaml), for the Phase 1 prompt and for
  enforce_spellings    the names and Spelling Rules applied to the assembled book; a name still spelled two ways
                       in a story is flagged ⚠
  note_tasks, apply_note_results, flag_leftovers   Phase 2
"""
import re
import unicodedata
from collections import Counter
from difflib import SequenceMatcher
from typing import Dict, List, NamedTuple, Optional

HEADING = re.compile(r"^(#{1,6})\s+(.*)$", re.S)
PDF_RANGE = re.compile(r"^<!--\s*pdf\s+(\d+)(?:-(\d+))?")
_call = re.compile(r"\[\^([^\]\s]+)\]")
_note_ref = re.compile(r"\[\^[^\]\s]+\]:?")
NOTE_DEF = re.compile(r"^\[\^([^\]\s]+)\]:\s?(.*)$", re.S)
# A note mark the transcription keeps as printed, until the code or Phase 2 pairs it: `pụ[^?1]`, `[^?*]`
PLACEHOLDER = re.compile(r"\[\^\?([^\]\s]*)\]")
FLAG = "⚠"
MISSED = "⚠ ai-missed?"
_flag_end = re.compile(r"\s*⚠$")
_trailing_comment = re.compile(r"\s*<!--.*?-->\s*$", re.S)
# Keep a paragraph from turning into a list item, heading or HTML, as the vsc assemble step does
_md_start = re.compile(r"^(?=[-*+#>]|\d{1,4}[.)]\s|[=_]{3})")
_tag = re.compile(r"<(?=[A-Za-z/!])")
_scene_break = re.compile(r"^(?:[*⁂✻❖]\s*){1,5}$")
_mark_chars = re.compile(r"[\s()\[\]{}]")
_lead_mark = re.compile(r"^\s*[(\[]?\s*(?:\d{1,2}|\*)\s*[)\]]\s*")
# A note mark the OCR read as punctuation in a raw heading: "Prăm Lắc (!)", "nàng BìLà (\")", "chăn dệ(!)"
_stray_heading_mark = re.compile(r"\s*\([!\"“”']\)")
_subtitle = re.compile(r"\(([^()]+)\)\s*$")

# An OCR line is in the transcription when this share of its words lines up with transcribed words
COVERED = 0.5
# This many words in a row with no OCR line under them flag their block
ADDED_RUN = 6
# A story's name is a capitalised word printed at least this often; it is enforced when one spelling has this share
NAME_MIN = 2
NAME_MAJORITY = 0.8


class Applied(NamedTuple):
    blocks: List[str]
    proposals: List[dict]
    # Result items not applied: {task, item, why}
    dropped: List[dict]
    # Each block of `blocks` that is on the scans -> its pages
    pages: Dict[int, List[int]]


class Assembled(NamedTuple):
    blocks: List[str]
    # Each block -> its pages (blocks on no scan are left out)
    pages: Dict[int, List[int]]
    # For each block, its boxes on the scans: [{page, bbox, approx}]
    boxes: List[List[dict]]
    # book.raw.md -> `blocks`, as AI Proposals without time, phase and model
    proposals: List[dict]
    # One line per page read: what the transcription missed or added
    coverage: List[dict]


def split_blocks(text: str) -> List[str]:
    text = text.rstrip("\n")
    return text.split("\n\n") if text else []


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
    if block.strip() == "* * *":
        return "break"
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


def _flagged(text: str) -> str:
    return text if text.endswith(FLAG) else text + " " + FLAG


def _title(heading: str) -> str:
    """A heading's title as the review tool names its section: note calls removed, lines joined."""
    m = HEADING.match(heading)
    return re.sub(r"\s*\n#*\s*", " ", _note_ref.sub("", m.group(2))).strip() if m else heading


def _section_titles(blocks: List[str]) -> List[str]:
    """For each block, the title of the heading it falls under, as the review tool names it."""
    titles, title = [], "(trước tiêu đề)"
    for b in blocks:
        if HEADING.match(b):
            title = _title(b)
        titles.append(title)
    return titles


def raw_sections(blocks: List[str]) -> List[dict]:
    """book.raw.md's sections: [{title, heading, level, start, end, pdf: [a, b] | None}], `end` exclusive."""
    out: List[dict] = []
    for i, b in enumerate(blocks):
        m = HEADING.match(b)
        if m:
            out.append(dict(title=_title(b), heading=b, level=len(m.group(1)), start=i))
    for k, s in enumerate(out):
        s["end"] = out[k + 1]["start"] if k + 1 < len(out) else len(blocks)
        s["pdf"] = None
        for b in blocks[s["start"]:s["end"]]:
            m = PDF_RANGE.match(b)
            if m:
                s["pdf"] = [int(m.group(1)), int(m.group(2) or m.group(1))]
                break
    return out


def story_titles(data: Optional[dict]) -> Dict[int, str]:
    """The book's Story Titles (titles.yaml: {titles: [{pdf, title}]}) by the first pdf page of their section."""
    return {int(t["pdf"]): unicodedata.normalize("NFC", str(t["title"]).strip())
            for t in (data or {}).get("titles") or []}


def story_title(section: dict, titles: Optional[Dict[int, str]]) -> str:
    """A section's (from `raw_sections`) Story Title, else its raw title."""
    return (titles or {}).get(section["pdf"][0] if section["pdf"] else None) or section["title"]


# -- words, for matching a transcription with the OCR lines
def fold_words(s: str) -> List[str]:
    """The words of `s` in lower case without diacritics, note calls or punctuation: "Pụ[^?1] :" -> ["pu"]."""
    s = unicodedata.normalize("NFD", _call.sub(" ", s).lower().replace("đ", "d"))
    return re.findall(r"[a-z0-9]+", "".join(c for c in s if not unicodedata.combining(c)))


def _spans(text: str) -> List[tuple]:
    """
    The words of `text` (taken in NFC) as (word, start, end, folded), the same words `fold_words` gives, so a word
    can be replaced where it is. Words inside a note call don't count.
    """
    text = unicodedata.normalize("NFC", text)
    chars = []
    for c in text:
        f = unicodedata.normalize("NFD", c.lower().replace("đ", "d"))[:1]
        chars.append(f if "a" <= f <= "z" or "0" <= f <= "9" else " ")
    for m in _call.finditer(text):
        chars[m.start():m.end()] = " " * (m.end() - m.start())
    return [(text[m.start():m.end()], m.start(), m.end(), m.group(0))
            for m in re.finditer(r"[a-z0-9]+", "".join(chars))]


def _cased(spelling: str, like: str) -> str:
    """`spelling` in the case of `like`, letter by letter: ("Tềwa", "TêWa") -> "TềWa"; ("Tềwa", "TÊWA") -> "TỀWA"."""
    if len(spelling) == len(like):
        return "".join(s.upper() if c.isupper() else s.lower() for s, c in zip(spelling, like))
    if like.isupper():
        return spelling.upper()
    return spelling[:1].upper() + spelling[1:].lower() if like[:1].isupper() else spelling.lower()


def _pairs(ws: List[str]) -> set:
    return set(zip(ws, ws[1:]))


def _union(boxes: List[List[float]]) -> List[float]:
    return [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes), max(b[3] for b in boxes)]


def _merged(boxes: List[dict]) -> List[dict]:
    """Boxes on the same page (and equally sure) as one box."""
    out: Dict[tuple, dict] = {}
    for b in boxes:
        k = (b["page"], b["approx"])
        out[k] = dict(b, bbox=_union([out[k]["bbox"], b["bbox"]])) if k in out else b
    return list(out.values())


def _mark(m: str) -> str:
    """A printed note mark as one key: "(1)", "1)", "1" -> "1"; "(*)" -> "*"."""
    return _mark_chars.sub("", m or "")


def _block(text: str) -> tuple:
    """A transcribed block as (kind, markdown): one-line headings, escaped dialogue dashes, verse lines kept."""
    lines = [" ".join(line.split()) for line in unicodedata.normalize("NFC", text).strip().split("\n")]
    lines = [line for line in lines if line]
    flat = " ".join(lines)
    if flat.startswith("#"):
        return "heading", "## " + flat.lstrip("#").strip()
    if _scene_break.match(flat):
        return "break", "* * *"
    lines = [_md_start.sub("\\\\", _tag.sub("&lt;", line.lstrip("\\"))) for line in lines]
    return "text", "  \n".join(lines)


# -- Phase 1: one page
def read_page(entry: dict, answer: dict, ocr_marks: bool = False, depends: frozenset = frozenset()) -> dict:
    """
    A page's transcription (a Phase 1 answer) checked against its OCR lines (a pages.jsonl line):

      units    the page's blocks in reading order, each {kind, text, page, boxes, missed}: text is markdown, with
               ⚠ at the end when it has text no OCR line is under, and `⚠ ai-missed?` blocks put back where an
               OCR line the model left out was; scene breaks (`* * *`) are left out, the book keeps only the story
      notes    the page's notes, {part: footnote | story, mark, text, page, boxes}, the same way
      joins    whether the page's first paragraph carries on the previous page's last one
      report   the page's coverage line: OCR lines missed, text added, OCR lines left out (`left_out`: noise, or a
               garbled line beside a ⚠ block that reads it anew), whether the printed page number the model read is
               the one the clean step expects, and the words `ocr_marks` changed

    With `ocr_marks`, a transcribed word that lines up with an OCR word of the same letters but other marks takes the
    OCR's marks when both OCR engines read the line alike (not `check`), unless its folded form is in `depends` (a
    word whose marks are decided per place).
    """
    page = entry["page"]
    lines = [ln for ln in entry.get("lines", []) if ln["role"] != "removed" and fold_words(ln["text"])]
    units: List[dict] = []
    for b in answer.get("blocks", []):
        kind, text = _block(b.get("text", ""))
        if text and kind != "break":
            units.append(dict(kind=kind, text=text, part="body", box=b.get("box")))
    for part, key in (("story", "story_notes"), ("footnote", "footnotes")):
        for n in answer.get(key, []):
            text = _lead_mark.sub("", " ".join(n.get("text", "").split()), count=1)
            if text:
                units.append(dict(kind="note", text=unicodedata.normalize("NFC", _tag.sub("&lt;", text)), part=part,
                                  mark=_mark(n.get("mark")),
                                  box=None))
    for u in units:
        u.update(page=page, lines=[], missed=False, added=False)

    # The page's OCR words and the transcription's words, lined up in reading order. An OCR word is covered when
    # it lines up with a transcribed word, the same or (where the model fixed the OCR) a different one; an OCR
    # line is in the block holding most of its covered words. Transcribed words with no OCR word against them,
    # ADDED_RUN or more in a row, are text no OCR line is under.
    ocr_spans = [(sp, k) for k, ln in enumerate(lines) for sp in _spans(ln["text"])]
    ocr = [(sp[3], k) for sp, k in ocr_spans]
    unit_spans = [_spans(u["text"]) for u in units]
    words = [[sp[3] for sp in sps] for sps in unit_spans]
    tr_spans = [(sp, k) for k, sps in enumerate(unit_spans) for sp in sps]
    tr = [(sp[3], k) for sp, k in tr_spans]
    marks: List[tuple] = []     # (unit, start, end, word, OCR word, OCR line) for `ocr_marks`
    held: List[Optional[int]] = [None] * len(ocr)      # OCR word -> the unit it lines up with
    added_in: set = set()
    matcher = SequenceMatcher(None, [w for w, _ in ocr], [w for w, _ in tr], autojunk=False)
    for op, i1, i2, j1, j2 in matcher.get_opcodes():
        n, m = i2 - i1, j2 - j1
        for k in range(min(n, m) if op == "replace" else n if op == "equal" else 0):
            held[i1 + k] = tr[j1 + (k * m // n if op == "replace" else k)][1]
            if op == "equal" and ocr_marks:
                (o_word, *_), line_k = ocr_spans[i1 + k]
                (t_word, start, end, folded), unit_k = tr_spans[j1 + k]
                if o_word.lower() != t_word.lower() and not lines[line_k]["check"] and folded not in depends:
                    marks.append((unit_k, start, end, t_word, o_word, lines[line_k]["n"]))
        extra = m - n if op == "replace" else m if op == "insert" else 0
        if extra >= ADDED_RUN:
            added_in |= {tr[j][1] for j in range(j2 - extra, j2)}
    owner: Dict[int, dict] = {}
    for k, ln in enumerate(lines):
        mine = [held[i] for i, (_, line_k) in enumerate(ocr) if line_k == k and held[i] is not None]
        if mine and len(mine) >= COVERED * sum(1 for _, line_k in ocr if line_k == k):
            u = units[max(set(mine), key=mine.count)]
            owner[ln["n"]] = u
            u["lines"].append(ln)

    printed, est = str(answer.get("printed_page") or "").strip(), entry.get("printed_page_est")
    report = dict(page=page, printed_page=printed, printed_page_est=est,
                  printed_page_ok=printed == str(est) if printed and est else None, missed=[], added=[], left_out=[],
                  ocr_marks=[dict(n=n, ai=t_word, ocr=o_word) for _, _, _, t_word, o_word, n in marks])
    for unit_k, start, end, t_word, o_word, _ in sorted(marks, key=lambda x: (x[0], -x[1])):
        u = units[unit_k]
        u["text"] = u["text"][:start] + _cased(o_word, t_word) + u["text"][end:]
    for k, (u, ws) in enumerate(zip(units, words)):
        if u["kind"] != "break" and ws and (k in added_in or not u["lines"]):
            u["added"] = True
            u["text"] = _flagged(u["text"])
            report["added"].append(u["text"][:120])

    # OCR lines no block holds come back, each run of them as one flagged block after the block before them. A run
    # that is mostly junk is noise; a run right before or after a ⚠ block is the garbled line the model read anew
    # there (a drop cap's first line); both are left out
    runs: List[list] = []       # [the body unit before the run or None, the run's lines, the unit after it or None]
    after, last_missed = None, False
    for ln in lines:
        u = owner.get(ln["n"])
        if u is not None:
            if last_missed:
                runs[-1][2] = u
            after = u if u["part"] == "body" else after
            last_missed = False
        elif last_missed and runs[-1][1][-1]["role"] == ln["role"]:
            runs[-1][1].append(ln)
        else:
            runs.append([after, [ln], None])
            last_missed = True
    missed_after: Dict[int, List[dict]] = {}    # id of the body unit (0: the page top) -> blocks to put after it
    for after, run, before in runs:
        why = ("noise" if _noise(" ".join(ln["text"] for ln in run))
               else "read anew in a ⚠ block" if any(v is not None and v["added"] for v in (after, before))
               else None)
        if why:
            report["left_out"] += [dict(n=ln["n"], text=ln["text"], why=why) for ln in run]
            continue
        text = run[0]["text"]
        for ln in run[1:]:
            text = joined(text, ln["text"])
        report["missed"] += [dict(n=ln["n"], text=ln["text"]) for ln in run]
        u = dict(page=page, lines=[], boxes=[dict(page=page, bbox=_union([ln["bbox"] for ln in run]), approx=False)],
                 missed=True, added=False, box=None)
        if run[0]["role"] == "footnote":
            units.append(dict(u, kind="note", part="footnote", mark="?", text=f"{MISSED} {text}"))
        else:
            missed_after.setdefault(id(after) if after else 0, []).append(
                dict(u, kind="text", part="body", text=f"{MISSED} {_block(text)[1]}"))

    for u in units:
        if "boxes" in u:
            continue
        if u["lines"]:
            u["boxes"] = [dict(page=page, bbox=_union([ln["bbox"] for ln in u["lines"]]), approx=False)]
        elif _box_ok(u["box"]):
            u["boxes"] = [dict(page=page, bbox=[v / 1000 for v in u["box"]], approx=True)]
        else:
            u["boxes"] = []

    body = list(missed_after.get(0, []))
    for u in units:
        if u["part"] == "body":
            body.append(u)
            body += missed_after.get(id(u), [])

    # The first paragraph carries on the previous page's last one when the page's first OCR line isn't indented
    # (the clean step's `continues`); the model's own reading decides when the OCR has no such line: the page
    # starts with a heading, or the transcription starts with words the OCR's first line doesn't have
    joins = False
    first = body[0] if body else None
    if first and first["kind"] == "text" and not first["missed"] and not first["text"].startswith("\\"):
        segs = [s for s in entry.get("segments", []) if s["kind"] != "footnote"]
        body_lines = [ln for ln in lines if ln["role"] == "body"]
        top = set(fold_words(body_lines[0]["text"])) if body_lines else set()
        if (segs and segs[0]["kind"] == "paragraph" and owner.get(body_lines[0]["n"]) is first
                and top & set(fold_words(first["text"])[:2])):
            joins = bool(segs[0].get("continues"))
        else:
            joins = bool(answer.get("starts_mid_paragraph"))
    notes = [u for u in units if u["part"] != "body"]
    for u in body + notes:
        for k in ("lines", "box", "added"):
            u.pop(k, None)
    return dict(page=page, units=body, notes=notes, joins=joins, report=report)


def _heading(raw: str, transcribed: Optional[str]) -> str:
    """
    A section's heading line: the raw one, which has the book's numbering and casing, without the note marks the
    OCR read as punctuation, and with a subtitle in brackets the page prints under the title that the raw heading
    lacks. The transcription's letters are not taken: the model misreads the diacritics of names.
    """
    out = _stray_heading_mark.sub("", _note_ref.sub("", raw)).rstrip()
    m = _subtitle.search(_note_ref.sub("", transcribed or "").strip())
    if m and fold_words(m.group(1)) and not set(fold_words(m.group(1))) <= set(fold_words(out)):
        out += f" ({m.group(1).strip()})"
    return out


def _noise(text: str) -> bool:
    """
    OCR lines that are specks, pictures or drop-cap junk ("Š/о1/2оє1", "N nnn nh Tàn n", "tt Ũ", "se b3"), not text
    the model missed: no more words (Latin letters, a vowel, no digits) than tokens that aren't words. A short line
    of the story ("vợ nói :", "bắc.") is all words.
    """
    words = junk = 0
    for tok in text.split():
        if not any(c.isalnum() for c in tok):
            continue
        latin = all(unicodedata.normalize("NFD", c)[0].isascii() or c in "đĐ" for c in tok if c.isalpha())
        ws = fold_words(tok)
        if latin and ws and all(w.isalpha() and re.search(r"[aeiouy]", w) for w in ws):
            words += 1
        else:
            junk += 1
    return words <= junk


def _box_ok(box) -> bool:
    return (isinstance(box, list) and len(box) == 4 and all(isinstance(v, (int, float)) for v in box)
            and 0 <= box[0] < box[2] <= 1000 and 0 <= box[1] < box[3] <= 1000)


# -- notes
def _slug(s: str) -> str:
    s = unicodedata.normalize("NFD", s.lower().replace("đ", "d"))
    s = "".join(c for c in s if not unicodedata.combining(c))
    return re.sub(r"[^a-z0-9]+", "-", s).strip("-")


def pair_notes(units: List[dict], notes: List[dict], scope: str, known: Dict[tuple, str], used: set) -> List[dict]:
    """
    Pairs a story's note marks (`[^?1]` in `units`, in reading order) with its notes: first a note printed at the
    foot of the mark's own page, then the story's end-of-story notes by mark, in order. Each paired mark becomes
    `[^id]` in its unit's text; a note keeps the id notes.json gives (page, marker), else gets `<scope>-p<page>-<n>`.
    Returns the notes, each with its `id` and whether a mark was `paired`; marks left unpaired stay `[^?1]`.
    """
    for n in notes:
        n["paired"] = False
        key = "star" if n["mark"] == "*" else n["mark"]
        nid = known.get((n["page"], n["mark"])) or f"{scope}-p{n['page']}-{key or 'x'}"
        base, k = nid, 1
        while nid in used:
            k += 1
            nid = f"{base}-{k}"
        used.add(nid)
        n["id"] = nid

    def take(page: Optional[int], mark: str, part: str) -> Optional[dict]:
        return next((n for n in notes if not n["paired"] and n["part"] == part and n["mark"] == mark
                     and (page is None or n["page"] == page)), None)

    marks = [(u, m) for u in units for m in PLACEHOLDER.finditer(u["text"])]
    pairs: Dict[int, dict] = {}
    for k, (u, m) in enumerate(marks):
        n = take(u["page"], _mark(m.group(1)), "footnote")
        if n:
            n["paired"], pairs[k] = True, n
    for k, (u, m) in enumerate(marks):
        if k not in pairs:
            n = take(None, _mark(m.group(1)), "story")
            if n:
                n["paired"], pairs[k] = True, n
    for u in units:
        mine = [(k, m) for k, (v, m) in enumerate(marks) if v is u and k in pairs]
        for k, m in reversed(mine):
            u["text"] = u["text"][:m.start()] + f"[^{pairs[k]['id']}]" + u["text"][m.end():]
    return notes


# -- the book
def assemble(raw_text: str, pages: Dict[int, dict], known_notes: List[dict],
             titles: Optional[Dict[int, str]] = None) -> Assembled:
    """
    book.ai.md from the pages read (`read_page` results by page). Each section of book.raw.md with a page read is
    rebuilt from its pages: its heading line is its Story Title (`titles`, by the section's first pdf page) as set,
    else the raw one cleaned up (see `_heading`), a call the page's heading carries going at its end; with a `<!-- pdf a-b · heading: <as transcribed> -->` comment, then its blocks, then
    its notes. A section none of whose pages were read, and the book's title (`# `, the title page), stay as they
    are in book.raw.md. Blocks the page above the section's heading prints belong to the section before.
    """
    raw = split_blocks(raw_text)
    secs = raw_sections(raw)
    known = {(n["page"], _mark(n.get("marker", ""))): n["id"] for n in known_notes}
    scopes = {n["page"]: n["scope"] for n in known_notes if n.get("scope")}
    used: set = set()

    # Each section's units (and notes) from its pages. Units above its heading on its first page end the section
    # before; when that one is not read, its book.raw.md text, which stays, already has them
    units: List[List[dict]] = [[] for _ in secs]
    notes: List[List[dict]] = [[] for _ in secs]
    read: List[List[int]] = [[] for _ in secs]
    for k, s in enumerate(secs):
        if not s["pdf"] or s["level"] == 1:
            continue
        for p in range(s["pdf"][0], s["pdf"][1] + 1):
            if p not in pages:
                continue
            read[k].append(p)
            us = pages[p]["units"]
            if p == s["pdf"][0] and k > 0:
                h = next((i for i, u in enumerate(us) if u["kind"] == "heading"), 0)
                if read[k - 1]:
                    units[k - 1] += us[:h]
                us = us[h:]
            units[k] += us
            notes[k] += pages[p]["notes"]

    out: List[str] = raw[:secs[0]["start"]] if secs else list(raw)
    out_pages: List[List[int]] = [[] for _ in out]
    out_boxes: List[List[dict]] = [[] for _ in out]
    proposals: List[dict] = []
    joins = {p: r["joins"] for p, r in pages.items()}
    for k, s in enumerate(secs):
        if not read[k]:
            block_range = raw[s["start"]:s["end"]]
            out += block_range
            out_pages += [[] for _ in block_range]
            out_boxes += [[] for _ in block_range]
            continue
        # The heading on the section's first page is its heading, however many lines it is printed over; any other
        # heading inside a story is a centred line
        us = [dict(u) for u in units[k]]
        head = None
        if us and us[0]["kind"] == "heading" and us[0]["page"] == read[k][0] == s["pdf"][0]:
            head = us.pop(0)
            while us and us[0]["kind"] == "heading" and us[0]["page"] == head["page"]:
                nxt = us.pop(0)
                head["text"] += " " + HEADING.match(nxt["text"]).group(2)
                head["boxes"] = _merged(head["boxes"] + nxt["boxes"])
        us = [dict(u, kind="text", text=_block(HEADING.match(u["text"]).group(2))[1]) if u["kind"] == "heading" else u
              for u in us]
        scope = next((scopes[p] for p in read[k] if p in scopes), None) or _slug(re.sub(r"^\d+\.\s*", "", s["title"]))
        sec_notes = pair_notes(([head] if head else []) + us, [dict(n) for n in notes[k]], scope, known, used)

        # The section's blocks, each {text, kind, pages, boxes}: paragraphs a page splits joined
        blocks: List[dict] = []
        heading_calls = "".join(f"[^{c}]" for c in _call.findall(head["text"])) if head else ""
        transcribed = HEADING.match(head["text"]).group(2) if head else None
        title, fixed = story_title(s, titles), s["pdf"][0] in (titles or {})
        line = "#" * s["level"] + " " + title if fixed else _heading(s["heading"], transcribed)
        blocks.append(dict(text=line + heading_calls, kind="heading",
                           pages=[head["page"]] if head else [], boxes=head["boxes"] if head else []))
        prev_page = head["page"] if head else None
        for u in us:
            last = blocks[-1]
            first_on_page, prev_page = u["page"] != prev_page, u["page"]
            if (first_on_page and joins.get(u["page"]) and last["kind"] == "text" and not last.get("missed")
                    and last["pages"] and last["pages"][-1] == u["page"] - 1):
                last["text"] = joined(last["text"], u["text"])
                last["pages"].append(u["page"])
                last["boxes"] = last["boxes"] + u["boxes"]
                continue
            blocks.append(dict(text=u["text"], kind=u["kind"], pages=[u["page"]], boxes=u["boxes"],
                               missed=u["missed"]))
        for n in sec_notes:
            tail = f" <!-- note pdf {n['page']}" + ("" if n["paired"] else " · call not found") + " -->"
            blocks.append(dict(text=f"[^{n['id']}]: {n['text']}{tail}", kind="note", pages=[n["page"]],
                               boxes=n["boxes"]))

        # A `<!-- pdf a-b -->` comment under the heading, from the pages read, so `review` finds the scans
        a, z = read[k][0], read[k][-1]
        comment = (f"pdf {a}" if a == z else f"pdf {a}-{z}") + (
            " · heading: " + _note_ref.sub("", transcribed).strip() if transcribed else "")
        sec_out = blocks[:1] + [dict(text=f"<!-- {comment} -->", kind="comment", pages=[], boxes=[])] + blocks[1:]

        full = s["pdf"] and read[k] == list(range(s["pdf"][0], s["pdf"][1] + 1))
        for p in block_diff(raw[s["start"]:s["end"]], [b["text"] for b in sec_out],
                            [b["pages"] for b in sec_out], trim=not full):
            proposals.append(dict(action=p["action"], section=title, pdf_pages=p["pdf_pages"],
                                  before=p["before"], after=p["after"],
                                  reason="transcribed from the scan"))
        out += [b["text"] for b in sec_out]
        out_pages += [sorted(set(b["pages"])) for b in sec_out]
        out_boxes += [b["boxes"] for b in sec_out]

    coverage = [pages[p]["report"] for p in sorted(pages)]
    return Assembled(out, {i: p for i, p in enumerate(out_pages) if p}, out_boxes, proposals, coverage)


# -- names and Spelling Rules
def spelling_rules(data: Optional[dict]) -> dict:
    """
    The book's Spelling Rules (spellings.yaml, from the review tool's diacritic page) ready to apply: {words: {folded:
    rule}, phrases: [rule], depends: {folded}}, each rule {spelling, except: the folded titles of the stories it
    skips}, a phrase also with its folded words and the punctuation between them. `depends` pairs are never applied.
    """
    data = data or {}

    def rule(r: dict) -> dict:
        return dict(spelling=r["spelling"], except_={_folded(t) for t in r.get("except") or []})

    words = {}
    for r in data.get("words") or []:
        words["".join(fold_words(r["spelling"]))] = rule(r)
    phrases = []
    for r in data.get("phrases") or []:
        sps = _spans(r["spelling"])
        phrases.append(dict(rule(r), words=[sp[0] for sp in sps], folds=[sp[3] for sp in sps],
                            gaps=[_gap(r["spelling"], a, b) for a, b in zip(sps, sps[1:])]))
    depends = {f for pair in data.get("depends") or [] for w in pair for f in fold_words(w)}
    return dict(words=words, phrases=phrases, depends=depends)


def _gap(text: str, a: tuple, b: tuple) -> str:
    """The punctuation between two words of `text` (from `_spans`), spaces left out."""
    return "".join(unicodedata.normalize("NFC", text)[a[2]:b[1]].split())


def _word_rule(rules: dict, folded: str, title: str) -> Optional[dict]:
    r = rules["words"].get(folded)
    return r if r and title not in r["except_"] else None


def story_names(raw_text: str, entries: Dict[int, dict], rules: dict,
                titles: Optional[Dict[int, str]] = None) -> List[List[dict]]:
    """
    For each section of book.raw.md (as `raw_sections` lists them), its names: the capitalised words of its pages'
    OCR lines that both OCR engines read alike (not `check`), printed NAME_MIN times or more, and never printed in
    lower case anywhere in the book (a common word starting a sentence). Spellings equal once folded are one name:
    [{fold, spelling, counts, rule}], most printed first. `spelling` is the book's Spelling Rule for it (`rule`
    true; a rule's story exceptions name Story Titles, `titles`), else the OCR's spelling when it has
    NAME_MAJORITY of the name's prints, else None. The title page's section has none.
    """
    lower = {sp[3] for e in entries.values() for ln in e.get("lines", []) for sp in _spans(ln["text"])
             if sp[0][:1].islower()}
    out: List[List[dict]] = []
    for s in raw_sections(split_blocks(raw_text)):
        if not s["pdf"] or s["level"] == 1:
            out.append([])
            continue
        title = _folded(story_title(s, titles))
        forms: Dict[str, Counter] = {}      # folded -> the word as printed -> times
        for p in range(s["pdf"][0], s["pdf"][1] + 1):
            for ln in entries.get(p, {}).get("lines", []):
                if ln["role"] == "removed":
                    continue
                for word, _, _, folded in _spans(ln["text"]):
                    if _word_rule(rules, folded, title):
                        forms.setdefault(folded, Counter())    # a ruled name the OCR garbles still goes in the prompt
                    if (not ln["check"] and word[:1].isupper() and len(folded) >= 2 and folded.isalpha()
                            and folded not in lower):
                        forms.setdefault(folded, Counter())[word] += 1
        names = []
        for folded, printed in forms.items():
            total = sum(printed.values())
            rule = _word_rule(rules, folded, title)
            if total < NAME_MIN and not rule:
                continue
            counts: Counter = Counter()
            for word, n in printed.items():
                counts[word.lower()] += n
            if rule:
                spelling = rule["spelling"]
                names.append(dict(fold=folded, spelling=spelling, counts=dict(counts), rule=True))
                continue
            top, n = counts.most_common(1)[0]
            if n >= NAME_MAJORITY * total:
                shown = [w for w, _ in printed.most_common() if w.lower() == top and not w.isupper()]
                spelling = shown[0] if shown else top[:1].upper() + top[1:]
            else:
                spelling = None
            names.append(dict(fold=folded, spelling=spelling, counts=dict(counts), rule=False))
        names.sort(key=lambda nm: -sum(nm["counts"].values()))
        out.append(names)
    return out


def page_names(raw_text: str, entries: Dict[int, dict], rules: dict, most: int = 40,
               titles: Optional[Dict[int, str]] = None) -> Dict[int, List[str]]:
    """For each page, the names of its story (or stories) that have a spelling, as the Phase 1 prompt lists them."""
    out: Dict[int, List[str]] = {}
    for s, names in zip(raw_sections(split_blocks(raw_text)), story_names(raw_text, entries, rules, titles)):
        if not names:
            continue
        spelled = [n["spelling"] for n in names if n["spelling"]]
        for p in range(s["pdf"][0], s["pdf"][1] + 1):
            have = out.setdefault(p, [])
            have += [w for w in spelled if w not in have][:max(0, most - len(have))]
    return out


def _respell(text: str, story: Dict[str, str], rules: dict, title: str) -> tuple:
    """
    `text` with the Spelling Rules (phrases first, then words) and the story's name spellings (`story`: folded ->
    spelling) applied, each word in its own case: (text, [(before, after, rule spelling or None)]).
    """
    text = unicodedata.normalize("NFC", text)
    sps = _spans(text)
    edits: List[tuple] = []     # (start, end, after, before, rule spelling or None)
    used: set = set()
    for r in rules["phrases"]:
        if title in r["except_"]:
            continue
        n = len(r["folds"])
        for i in range(len(sps) - n + 1):
            win = sps[i:i + n]
            if (any(k in used for k in range(i, i + n)) or [sp[3] for sp in win] != r["folds"]
                    or [_gap(text, a, b) for a, b in zip(win, win[1:])] != r["gaps"]):
                continue
            new = "".join(_cased(w, sp[0]) + text[sp[2]:nxt[1]] for w, sp, nxt in zip(r["words"], win, win[1:] + [None])
                          if nxt) + _cased(r["words"][-1], win[-1][0])
            before = text[win[0][1]:win[-1][2]]
            if new.lower() != before.lower():
                used |= set(range(i, i + n))
                edits.append((win[0][1], win[-1][2], new, before, r["spelling"]))
    for k, (word, start, end, folded) in enumerate(sps):
        if k in used:
            continue
        rule = _word_rule(rules, folded, title)
        spelling = rule["spelling"] if rule else story.get(folded)
        if spelling and spelling.lower() != word.lower():
            edits.append((start, end, _cased(spelling, word), word, rule["spelling"] if rule else None))
    edits.sort()
    for start, end, new, _, _ in reversed(edits):
        text = text[:start] + new + text[end:]
    return text, [(before, new, rule) for _, _, new, before, rule in edits]


def enforce_spellings(blocks: List[str], pages: Dict[int, List[int]], raw_text: str, entries: Dict[int, dict],
                      rules: dict, titles: Optional[Dict[int, str]] = None) -> Applied:
    """
    The Spelling Rules and each story's names (`story_names`) applied to the sections the pass wrote (`blocks`,
    whose sections are book.raw.md's, in order; a rule's story exceptions name Story Titles, `titles`, else raw
    titles), headings included but a Story Title (the model's own reading in the heading comment stays): a word equal to a name once folded
    takes the name's spelling, in the word's own case. A Spelling Rule beats the OCR's spelling. Then a name still
    spelled two ways in a story gets ⚠ on the blocks with its less common spelling. Each block changed is one AI
    Proposal; one a rule changed lists the rules in `rule`.
    """
    secs = raw_sections(split_blocks(raw_text))
    names = story_names(raw_text, entries, rules, titles)
    section_of, k = [], -1
    for b in blocks:
        k += bool(HEADING.match(b))
        section_of.append(k)
    read = {section_of[i] for i in pages if section_of[i] >= 0}
    out = list(blocks)
    why: Dict[int, dict] = {}
    for k in sorted(read):
        if k >= len(names):
            continue
        fixed = bool(secs[k]["pdf"]) and secs[k]["pdf"][0] in (titles or {})
        idx = [i for i, sec in enumerate(section_of) if sec == k and _kind(blocks[i]) != "comment"
               and not (fixed and HEADING.match(blocks[i]))]
        title = _folded(story_title(secs[k], titles))
        story = {n["fold"]: n["spelling"] for n in names[k] if n["spelling"]}
        for i in idx:
            text, changes = _respell(model_text(blocks[i]), story, rules, title)
            if changes:
                out[i] = _with_comment(blocks[i], text)
                why[i] = dict(changes=changes)

        # A name still spelled two ways: ⚠ on the blocks (not the heading) holding a less common spelling
        body = [i for i in idx if not HEADING.match(out[i])]
        for n in names[k]:
            seen: Counter = Counter()
            shown: Dict[str, str] = {}
            where: Dict[int, set] = {}
            for i in body:
                for word, _, _, folded in _spans(model_text(out[i])):
                    if folded == n["fold"]:
                        seen[word.lower()] += 1
                        shown.setdefault(word.lower(), word)
                        where.setdefault(i, set()).add(word.lower())
            if len(seen) < 2:
                continue
            top = seen.most_common(1)[0][0]
            reason = "a name spelled differently in this story: " + ", ".join(
                f"{shown[w]} {c}" for w, c in seen.most_common())
            for i, spelled in where.items():
                if spelled - {top}:
                    out[i] = _with_comment(out[i], _flagged(model_text(out[i])))
                    why.setdefault(i, dict(changes=[]))["flag"] = reason

    def listed(changes: List[tuple]) -> str:
        times = Counter((a, b) for a, b, _ in changes)
        return ", ".join(f"{a} → {b}" + (f" ({n}×)" if n > 1 else "") for (a, b), n in times.items())

    titles = _section_titles(out)
    proposals = []
    for i in sorted(why):
        changes = why[i]["changes"]
        ruled = [c for c in changes if c[2]]
        named = [c for c in changes if not c[2]]
        parts = []
        if ruled:
            parts.append("Spelling Rule: " + listed(ruled))
        if named:
            parts.append("names as the OCR prints them in this story: " + listed(named))
        if "flag" in why[i]:
            parts.append(why[i]["flag"])
        # A heading the model did not read as one has no pages of its own: it goes with its section's first page
        on = pages.get(i) or next((pages[j][:1] for j in range(i, len(out)) if pages.get(j)
                                   and section_of[j] == section_of[i]), [])
        p = {"action": "edit", "section": titles[i], "pdf_pages": on, "before": [blocks[i]],
             "after": [out[i]], "reason": "; ".join(parts)}
        if ruled:
            p["rule"] = list(dict.fromkeys(r for _, _, r in ruled))
        proposals.append(p)
    return Applied(out, proposals, [], dict(pages))


# -- book.raw.md -> book.ai.md as AI Proposals
_MATCH = 0.3     # least similarity for two blocks to be the same paragraph
_WITHIN = 0.6    # a block is part of another when this share of its word pairs is in it


def _shape(block: str) -> tuple:
    ws = fold_words(model_text(block))
    return ws, (_pairs(ws) if len(ws) > 1 else {(w, "") for w in ws})


def _within(a: set, b: set) -> float:
    return len(a & b) / len(a) if a else 0.0


def block_diff(before: List[str], after: List[str], after_pages: List[List[int]], trim: bool = False) -> List[dict]:
    """
    The changes from one list of blocks to another, paragraph by paragraph: [{action, pdf_pages, before, after}],
    action edit, merge (several blocks became one), delete or insert. Blocks are lined up by their words, so a
    changed paragraph is an edit of its old one, not a delete and an insert. Comments are left out. With `trim`,
    old blocks before the first and after the last new one are left out (the new side covers only some pages).
    """
    a_idx = [i for i, b in enumerate(before) if _kind(b) != "comment"]
    b_idx = [j for j, b in enumerate(after) if _kind(b) != "comment"]
    A = [_shape(before[i])[1] for i in a_idx]
    B = [_shape(after[j])[1] for j in b_idx]
    n, m = len(A), len(B)

    def sim(i: int, j: int) -> float:
        if before[a_idx[i]] == after[b_idx[j]]:
            return 1.0
        if not A[i] or not B[j]:
            return 0.0
        return len(A[i] & B[j]) / min(len(A[i]), len(B[j]))

    # Best lining-up (most similarity) by dynamic programming
    score = [[0.0] * (m + 1) for _ in range(n + 1)]
    for i in range(1, n + 1):
        row, up = score[i], score[i - 1]
        for j in range(1, m + 1):
            best = max(up[j], row[j - 1])
            if up[j - 1] + 1 > best:     # a pair adds at most 1
                s = sim(i - 1, j - 1)
                if s >= _MATCH and up[j - 1] + s > best:
                    best = up[j - 1] + s
            row[j] = best
    ops = []
    i, j = n, m
    while i or j:
        if i and j:
            s = sim(i - 1, j - 1)
            if s >= _MATCH and abs(score[i][j] - (score[i - 1][j - 1] + s)) < 1e-9:
                ops.append(([i - 1], [j - 1]))
                i, j = i - 1, j - 1
                continue
        if i and (not j or score[i][j] == score[i - 1][j]):
            ops.append(([i - 1], []))
            i -= 1
        else:
            ops.append(([], [j - 1]))
            j -= 1
    ops.reverse()

    # A block left alone that is part of a neighbouring pair's block joins that pair: a merge or a split
    groups: List[tuple] = []
    for olds, news in ops:
        if groups and groups[-1][0] and groups[-1][1]:
            g_old, g_new = groups[-1]
            if olds and not news and _within(A[olds[0]], set().union(*(B[x] for x in g_new))) >= _WITHIN:
                g_old += olds
                continue
            if news and not olds and _within(B[news[0]], set().union(*(A[x] for x in g_old))) >= _WITHIN:
                g_new += news
                continue
        groups.append((list(olds), list(news)))
    for k in range(len(groups) - 2, -1, -1):
        (o1, n1), (o2, n2) = groups[k], groups[k + 1]
        if o2 and n2 and o1 and not n1 and _within(A[o1[-1]], set().union(*(B[x] for x in n2))) >= _WITHIN:
            groups[k + 1] = (o1 + o2, n2)
            del groups[k]
        elif o2 and n2 and n1 and not o1 and _within(B[n1[-1]], set().union(*(A[x] for x in o2))) >= _WITHIN:
            groups[k + 1] = (o2, n1 + n2)
            del groups[k]

    if trim:
        # Old blocks outside the span of new paragraphs are on pages not read (the heading and the notes, at the
        # ends of a section, are always written)
        content = [k for k, (_, nw) in enumerate(groups)
                   if any(_kind(after[b_idx[x]]) not in ("heading", "note") for x in nw)]
        groups = [g for k, g in enumerate(groups) if g[1] or (content and content[0] <= k <= content[-1])]

    out, last_pages = [], []
    for olds, news in groups:
        old = [before[a_idx[x]] for x in olds]
        new = [after[b_idx[x]] for x in news]
        pages = sorted({p for x in news for p in after_pages[b_idx[x]]}) or last_pages
        last_pages = pages
        if old == new:
            continue
        if not new:
            action = "delete"
        elif not old:
            action = "insert"
        elif len(old) > 1 and len(new) == 1:
            action = "merge"
        else:
            action = "edit"
        out.append(dict(action=action, pdf_pages=pages, before=old, after=new))
    return out


# -- Phase 2: notes the code could not pair
NOTE_PAGE = re.compile(r"<!--\s*note pdf (\d+)")
# A story up to this long is shown whole to a note task; a longer one only around the term the note explains
WHOLE_STORY_MAX_CHARS = 30000


def _folded(s: str) -> str:
    """Lower-case letters without diacritics, so "Pụ" finds "pu" and "P Tao-lu-pu" finds "ptaolupu"."""
    s = unicodedata.normalize("NFD", s.lower().replace("đ", "d"))
    return "".join(c for c in s if c.isalnum() and not unicodedata.combining(c))


def note_tasks(blocks: List[str], pages: Dict[int, List[int]]) -> List[dict]:
    """
    One Phase 2 task per Note Definition the pass wrote (one with pages) whose call was not found: the definition,
    the page it is
    printed on, and the story paragraphs the call may be in (the whole story when it is short, else the paragraphs
    mentioning the term the note explains, those on the note's page and the page before, and any holding an
    unpaired mark, each with its neighbours).
    """
    titles = _section_titles(blocks)
    tasks = []
    for d, block in enumerate(blocks):
        m = NOTE_DEF.match(block)
        if not m or "call not found" not in block or d not in pages:
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
                    or PLACEHOLDER.search(blocks[i]) or near & set(pages.get(i, []))]
            story_set = set(story)
            chosen = sorted({j for i in hits for j in (i - 1, i, i + 1) if j in story_set})
        tasks.append({
            "note_id": note_id, "definition_block": d, "definition": definition, "note_page": note_page,
            "candidates": [(i, model_text(blocks[i])) for i in chosen], "whole_story": whole,
        })
    return tasks


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


def flag_leftovers(blocks: List[str], pages: Dict[int, List[int]]) -> Applied:
    """
    ⚠ on every block the pass wrote (one with pages) that still holds an unpaired note mark, and every note of it
    whose call is still not found.
    """
    titles = _section_titles(blocks)
    out = list(blocks)
    proposals = []
    for i, b in enumerate(blocks):
        if i not in pages:
            continue
        if NOTE_DEF.match(b) and "call not found" in b and FLAG not in model_text(b):
            after, why = _with_comment(b, _flagged(model_text(b))), "the note's call is still not found"
        elif PLACEHOLDER.search(b) and not b.endswith(FLAG) and _kind(b) != "note":
            after, why = _flagged(b), "a note mark is still not paired with a note"
        else:
            continue
        proposals.append({"action": "edit", "section": titles[i], "pdf_pages": pages.get(i, []),
                          "before": [b], "after": [after], "reason": why})
        out[i] = after
    return Applied(out, proposals, [], dict(pages))
