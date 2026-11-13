"""
The Topic Index (Hệ thống tra cứu theo chủ đề, PDF 547-674 of Part 4's PDF; vocabulary: the book's GLOSSARY): each
Index Line classified from its Vision reads, the two reads of a line compared, the review log of Confirmed Lines, and the
index assembled and checked from every Index Line with the log laid over.

Every Index Line is read twice, independently: by Apple Vision on the Mac, and by the model from the line's crop. A
number line's request has no Vision read in it (docs/adr/0007-number-lines-read-without-a-hint.md beside the GLOSSARY),
so its numbers are accepted only where the two reads agree. A heading line's request has Vision's reads as a hint, as an
Entry Span's has, and only its number must agree. A line with one read is always a Warning.

The store's answers.json, written by topic_index.py:

  {"section": {"key", "pages": [first, last], "book_page_offset"},
   "pages": {PDF page: {"pdf_sha1", "size", "book_page", "image", "missed", "why", "lines": [Index Line, ...]}}}

each Index Line being {"n" (its Line Number), "band" ([top, bottom] px of the 300 dpi scan), "crop" (its request's crop),
"kind" (`classify_page`), "line_read", "page_read", "vision" (the values parsed from Vision's read), "vlm" (the model's
answer, or None), "vlm_why" (why there is none), "agreement" (`agreement`)}. A page's "why" says why it has no lines.
Values are {"kind", "letter", "numbers", "text"}: a Topic Row line's letter ("" on a continuation) and numbers, a
heading line's text as printed ("I", "17. Tiền bạc, của cải, vay mượn, nợ nần", or a title's line).

The review log, review.jsonl, is appended to by the section's review server only; no run writes or rewrites it. Each line
has its "time":

  {"type": "confirmed_line", "page": 548, "pdf_sha1": "<sha1>", "band": [812, 860], "kind": "row_continuation",
   "letter": "", "numbers": [133, 134], "text": "", "model": {values}, "edited": true}
      a Confirmed Line, whole, keyed by its page and band like a Confirmed Span: its values replace the model's read of
      every Index Line whose centre falls in its band, whatever its Line Number, and clear its disagreement and
      single-read Warnings. The checks still run on its values. "model" is the model's values when it was confirmed.
      It may also carry the line's "crop", "line_read" and "page_read", shown if it falls on no Index Line of a later run
  {"type": "unconfirmed_line", "page": 548, "band": [812, 860]}
      that line undone: the latest of the two for a band wins

Standard library only, importing only assembly.py (and through it citations.py and diacritics.py), relatively:
topic_index.py copies them into the store, for the review server.
"""
import json
import os
import re
import unicodedata

from .assembly import ALPHABET, INK_OUTSIDE, PAGE_MISSING, warning

REVIEW_LOG = "review.jsonl"

# The kinds of Index Line. A Confirmed Line is one of LINE_KINDS: NOT_INDEX is printed matter outside the index, a
# Running Head ("2970 KHO TÀNG TỤC NGỮ NGƯỜI VIỆT", "Hệ thống tra cứu theo chủ đề 2971") or scan noise, and is read by
# no request. Code alone classifies a line UNCLASSIFIED (its read is none of the others), or UNREAD (Vision has no read
# of it, so its request is a number line's and its answer gives its kind)
CHU_DE, TIEU_CHU_DE, TITLE, ROW_START, ROW_CONTINUATION, NOT_INDEX = (
    "chu_de", "tieu_chu_de", "title", "row_start", "row_continuation", "not_index")
LINE_KINDS = [CHU_DE, TIEU_CHU_DE, TITLE, ROW_START, ROW_CONTINUATION, NOT_INDEX]
UNCLASSIFIED, UNREAD = "unclassified", "unread"
# Read as numbers, with no hint; the others but NOT_INDEX are read as headings, with Vision's reads as a hint
NUMBER_KINDS = (ROW_START, ROW_CONTINUATION, UNREAD)
HEADING_KINDS = (CHU_DE, TIEU_CHU_DE, TITLE)
VALUE_KEYS = ("kind", "letter", "numbers", "text")

ROMAN = ["I", "II", "III", "IV"]

# How a line's two reads compare (`agreement`), and a line's state for the review server
AGREED, DISAGREED, SINGLE_READ, NO_READ = "agreed", "disagreed", "single_read", "no_read"
WARNED, CONFIRMED = "warned", "confirmed"

DISAGREEMENT, SINGLE = "index_disagreement", "index_single_read"
UNCLASSIFIED_LINE, KIND_MISMATCH, COUNT = "index_unclassified", "index_kind_mismatch", "index_count"
NO_ENTRY, NOT_ASCENDING, LETTER_ORDER = "index_no_entry", "index_not_ascending", "index_letter_order"
HEADING_NUMBER, NO_OWNER, PART_MISSING = "index_heading_number", "index_no_owner", "index_part_missing"
# What a Confirmed Line clears, listed first, and what the export stops on while one is open
READ_KINDS = (DISAGREEMENT, SINGLE)

# A tiểu chủ đề: its number at the left margin, a full stop, then words ("17. Tiền bạc, của cải")
_TIEU = re.compile(r"^(\d{1,2})\s*(?:[.,]\s*|\s+)([^\W\d_].*)$")
# Letters Vision reads for a digit, mended in a word of a number line that holds a digit
_AS_DIGIT = str.maketrans({"l": "1", "I": "1", "|": "1", "ı": "1", "O": "0", "o": "0"})
# ...and for the I of a chủ đề's numeral
_AS_ROMAN = str.maketrans({"l": "I", "1": "I", "|": "I", "ı": "I"})
_RUNNING_HEAD = re.compile(r"kho tàng|tục ngữ|tra cứu|theo chủ")
# A chủ đề's numeral is centred: its middle within this share of the page's width from the middle of the page's lines
CENTRED_SHARE = 0.1


def _whole(value):
    return isinstance(value, int) and not isinstance(value, bool)


def _nfc(text):
    """`text` in NFC, stripped, with Vision's Icelandic eth (Ð) read as the book's Đ."""
    return unicodedata.normalize("NFC", text or "").replace("Ð", "Đ").replace("ð", "đ").strip()


def _letters(text):
    return sum(ch.isalpha() for ch in text)


def parse_number_line(text):
    """
    {"letter", "numbers", "items"} of a read of a number line, or None if it doesn't read as one. Its first word may be
    a letter of the book's alphabet ("C 93, 262", "C93,"); everything after it is numbers separated by commas (or
    semicolons, which Vision reads some commas as), with scan noise between them ("82,·628", "138,-139"). Letters
    Vision reads for digits (l, O) count as digits in a word holding one; a read with letters beyond two such is no
    number line. "items" is how many of its comma-separated pieces hold a digit: the Count check's.
    """
    text = _nfc(text)
    text = text[next((i for i, ch in enumerate(text) if ch.isalnum()), len(text)):]
    letter = ""
    if text and text[0].isalpha():
        follows = text[1:2]
        upper = text[0].upper()
        if upper in ALPHABET and (not follows or follows.isspace()
                                  or (follows.isdigit() and text[0].isupper() and upper not in ("I", "O"))):
            letter, text = upper, text[1:]
    words = [w.translate(_AS_DIGIT) if any(ch.isdigit() for ch in w) else w for w in text.split()]
    rest = " ".join(words)
    numbers = [int(d) for d in re.findall(r"\d+", rest)]
    stray = _letters(rest)
    if not numbers or (stray and (stray > 2 or sum(ch.isdigit() for ch in rest) < 4)):
        return None
    return {"letter": letter, "numbers": numbers,
            "items": sum(any(ch.isdigit() for ch in item) for item in re.split(r"[,;]", rest))}


def heading_number(kind, text):
    """A chủ đề's numeral as 1-4, or a tiểu chủ đề's number, from its `text`; else None."""
    text = _nfc(text)
    if kind == CHU_DE:
        numeral = text.rstrip(".").translate(_AS_ROMAN).upper()
        return ROMAN.index(numeral) + 1 if numeral in ROMAN else None
    if kind == TIEU_CHU_DE:
        m = _TIEU.match(text)
        return int(m.group(1)) if m else None
    return None


def tieu_chu_de_title(text):
    """A tiểu chủ đề's title: its text without its number."""
    m = _TIEU.match(_nfc(text))
    return m.group(2).strip() if m else _nfc(text)


def _read(line):
    """The read a line is classified from: its line read, or its page read if the line read holds nothing."""
    line_read = _nfc(line["line_read"])
    return line_read if any(ch.isalnum() for ch in line_read) else _nfc(line["page_read"])


def _kind(line, text, middle, size, heading_open):
    """The kind of a line read as `text` (see `classify_page`). Numbers are tried before a tiểu chủ đề, so a
    continuation read "12, l5, 67" is no tiểu chủ đề 12."""
    _, _, left, right = line["line"]
    if not text:
        return UNREAD
    if line["n"] == 1 and (_RUNNING_HEAD.search(text.casefold()) or (
            re.search(r"^\d{3,4}\s+\D|\D\s+\d{3,4}$", text) and len(re.findall(r"[^\W\d_]{2,}", text)) >= 2)):
        return NOT_INDEX
    if heading_number(CHU_DE, text) and abs((left + right) / 2 - middle) <= CENTRED_SHARE * size[0]:
        return CHU_DE
    parsed = parse_number_line(text)
    if parsed:
        return ROW_START if parsed["letter"] else ROW_CONTINUATION
    if heading_number(TIEU_CHU_DE, text):
        return TIEU_CHU_DE
    return TITLE if heading_open and _letters(text) else UNCLASSIFIED


def classify_page(lines, size, heading_open=False):
    """
    The kind of each of a page's lines, [{"n", "line" ([top, bottom, left, right] px), "line_read", "page_read"}], in
    order, from its Vision reads and position, and whether a heading is still open at the page's end, for the next
    page's `heading_open`:

      NOT_INDEX           the first line, if it is a Running Head: words and a page number at one end, or the title
      CHU_DE              a roman numeral I-IV alone, centred
      ROW_START           a letter of the book's alphabet, then numbers
      ROW_CONTINUATION    numbers only, which continue the Topic Row above, on this page or the page before
      TIEU_CHU_DE         "N. words" at the left
      TITLE               words, while a heading is open: a chủ đề, tiểu chủ đề or title line came last
      UNREAD              no read from Vision
      UNCLASSIFIED        anything else

    Each line is classified from its line read, or its page read if the line read holds nothing or is none of these.
    """
    if not lines:
        return [], heading_open
    middle = (min(l["line"][2] for l in lines) + max(l["line"][3] for l in lines)) / 2
    kinds = []
    for line in lines:
        kind = _kind(line, _read(line), middle, size, heading_open)
        # A line read garbled into words is tried again from the page read
        if kind == UNCLASSIFIED and _nfc(line["page_read"]):
            kind = _kind(line, _nfc(line["page_read"]), middle, size, heading_open)
        if kind != NOT_INDEX:
            heading_open = kind in HEADING_KINDS
        kinds.append(kind)
    return kinds, heading_open


def vision_values(kind, line_read, page_read):
    """The values parsed from a line's Vision reads: a number line's {"letter", "numbers", "items", "read"} from its line
    read, or its page read where the line read doesn't parse ("read" says which), else None; a heading line's {"text"}.
    """
    if kind in NUMBER_KINDS:
        for read, text in (("line", line_read), ("page", page_read)):
            parsed = parse_number_line(text)
            if parsed:
                return {**parsed, "read": read}
        return None
    text = _read({"line_read": line_read, "page_read": page_read})
    return {"text": text} if text else None


def agreement(kind, vision, vlm):
    """
    How a line's two reads compare: AGREED where a number line's letter and numbers, or a heading's number, are the same
    in both (a title line's two reads are only a hint and its answer, so they agree), DISAGREED where they differ,
    SINGLE_READ where only one read it, NO_READ where neither did.
    """
    if kind == NOT_INDEX:
        return AGREED
    reads = (vision is not None) + (vlm is not None)
    if reads < 2:
        return SINGLE_READ if reads else NO_READ
    if kind in NUMBER_KINDS:
        same = (vision["letter"], vision["numbers"]) == (vlm["letter"], vlm["numbers"])
    elif kind in (CHU_DE, TIEU_CHU_DE):
        same = heading_number(kind, vision["text"]) == heading_number(kind, vlm["text"])
    else:
        same = True
    return AGREED if same else DISAGREED


def model_values(line):
    """An Index Line's values as read: the model's answer, or Vision's where the model has none. An UNREAD line the
    model read is a ROW_START if it read a letter, else a ROW_CONTINUATION."""
    kind, read = line["kind"], line["vlm"] or line["vision"] or {}
    if kind == UNREAD and line["vlm"]:
        kind = ROW_START if line["vlm"]["letter"] else ROW_CONTINUATION
    if kind in NUMBER_KINDS:
        return {"kind": kind, "letter": read.get("letter", ""), "numbers": list(read.get("numbers", [])), "text": ""}
    return {"kind": kind, "letter": "", "numbers": [], "text": read.get("text", "")}


def values_problem(values):
    """Why `values` are not a Confirmed Line's values, or None."""
    if not isinstance(values, dict) or values.get("kind") not in LINE_KINDS:
        return f"no kind of {LINE_KINDS}"
    kind, letter, numbers, text = (values.get(k) for k in VALUE_KEYS)
    if not isinstance(letter, str) or not isinstance(text, str):
        return "the letter and text are not text"
    if not isinstance(numbers, list) or not all(_whole(x) and x >= 0 for x in numbers):
        return "the numbers are not a list of whole numbers"
    if kind in (ROW_START, ROW_CONTINUATION) and not numbers:
        return "a Topic Row's line has no numbers"
    if kind == ROW_START and _nfc(letter).upper() not in ALPHABET:
        return f'"{letter}" is not a letter of the book\'s alphabet'
    if kind == ROW_CONTINUATION and letter:
        return "a Topic Row's continuation has no letter"
    if kind in (CHU_DE, TIEU_CHU_DE) and heading_number(kind, text) is None:
        return "a chủ đề is a numeral I-IV" if kind == CHU_DE else 'a tiểu chủ đề begins with its number ("17. ...")'
    if kind == TITLE and not text.strip():
        return "a title line has no text"
    return None


def normal_values(values):
    """`values` as compared and stored: the letter upper case in NFC, the text in NFC."""
    return {"kind": values["kind"], "letter": _nfc(values["letter"]).upper(), "numbers": list(values["numbers"]),
            "text": _nfc(values["text"])}


def band_problem(band):
    """Why `band` is not a band of pixel rows, or None."""
    if not isinstance(band, list) or len(band) != 2 or not all(_whole(row) for row in band) or band[0] >= band[1]:
        return "no band of pixel rows"
    return None


def read_log(store):
    """The store's review log as it stands now: {PDF page: its Confirmed Lines' latest records, top to bottom}."""
    path = os.path.join(store, REVIEW_LOG)
    held = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(record, dict) or not _whole(record.get("page")) or band_problem(record.get("band")):
                    continue
                key = (record["page"], tuple(record["band"]))
                if record.get("type") == "confirmed_line" and isinstance(record.get("pdf_sha1"), str) \
                        and values_problem(record) is None:
                    held[key] = record
                elif record.get("type") == "unconfirmed_line":
                    held.pop(key, None)
    log = {}
    for (page, _), record in sorted(held.items()):
        log.setdefault(page, []).append(record)
    return log


def lay_confirmed(answer, records):
    """
    A page's Index Lines with `records`, its Confirmed Lines, laid over them, top to bottom: each line with its values
    (the model's, or a record's), "model" (the model's values), "confirmed" and "edited". A record's values go to the
    first line whose centre falls in its band; any other line there is part of it, NOT_INDEX. A record on no line of
    the page is a line of its own.
    """
    out, used = [], set()
    for line in answer["lines"]:
        model = model_values(line)
        laid = {**line, **model, "model": model, "confirmed": False, "edited": False}
        centre = (line["band"][0] + line["band"][1]) / 2
        holding = [k for k, r in enumerate(records) if r["band"][0] <= centre < r["band"][1]]
        held = max(holding, key=lambda k: records[k].get("time", ""), default=None)
        if held is not None:
            values = normal_values(records[held]) if held not in used else {**model, "kind": NOT_INDEX,
                                                                            "letter": "", "numbers": [], "text": ""}
            laid.update(values, band=records[held]["band"], confirmed=True, edited=values != normal_values(model))
            used.add(held)
        out.append(laid)
    for k, r in enumerate(records):
        if k not in used:
            out.append({"n": None, "band": r["band"], "crop": r.get("crop"), "line_read": r.get("line_read", ""),
                        "page_read": r.get("page_read", ""), "vision": None, "vlm": None, "vlm_why": None,
                        "agreement": AGREED, **normal_values(r), "model": r.get("model"), "confirmed": True,
                        "edited": bool(r.get("edited"))})
    return sorted(out, key=lambda l: l["band"][0])


def _place(page, line):
    """A line's place in a Warning's id: its page and the top of its band, which stay when Line Numbers change."""
    return f"p{page}-y{line['band'][0]}"


def _line_name(page, line):
    return f"PDF page {page}, line {line['n']}" if line["n"] else f"PDF page {page}, the line at {line['band'][0]} px"


def _read_warnings(page, line):
    """The Warnings of a line's reads, which confirming it clears: disagreement or a single read, its kind contradicted
    by the model's read, the Count, or no kind."""
    if line["confirmed"]:
        return []
    where, kind, vision, vlm = _line_name(page, line), line["kind"], line["vision"], line["vlm"]
    reads = (f'line read "{line["line_read"]}", page read "{line["page_read"]}", '
             f"model {json.dumps(vlm, ensure_ascii=False)}")
    out = []
    if line["agreement"] == DISAGREED:
        out.append((DISAGREEMENT, f"{where}: the reads disagree: {reads}"))
    elif line["agreement"] in (SINGLE_READ, NO_READ):
        why = f" (the model's: {line['vlm_why']})" if vlm is None and line.get("vlm_why") else ""
        out.append((SINGLE, f"{where}: {'one read' if line['agreement'] == SINGLE_READ else 'no read'}{why}: {reads}"))
    if kind == UNCLASSIFIED:
        out.append((UNCLASSIFIED_LINE, f"{where} is none of the index's kinds of line: {reads}"))
    if vlm is not None and "text" in vlm and (
            (kind in (CHU_DE, TIEU_CHU_DE) and heading_number(kind, vlm["text"]) is None)
            or (kind == TITLE and parse_number_line(vlm["text"]))):
        out.append((KIND_MISMATCH, f'{where} was classified {kind}, and the model read "{vlm["text"]}"'))
    if kind in NUMBER_KINDS and vision and vlm and vision["items"] != len(vlm["numbers"]):
        out.append((COUNT, f'{where}: Vision\'s {vision["read"]} read has {vision["items"]} comma-separated item(s), '
                           f"the model read {len(vlm['numbers'])} number(s): {reads}"))
    return out


def _unresolved(entry_names):
    return [tuple(r) for r in entry_names.get("unresolved", [])]


def rebuild(answers, log, entry_names, extra=None):
    """
    The Topic Index assembled from `answers` (answers.json) with `log` (`read_log`) laid over it, checked against
    `entry_names` (entry_names.json: {"missing_parts", "names": {letter: [numbers]}, "unresolved": [[letter, first,
    last]]}). `extra`, (page, record), lays one more record over its page, in place of any at its band (`preview`).
    Returns {"topics", "warnings", "pages"}:

      topics      [{"id": "I", "title", "subtopics": [{"id": "I.1", "number", "title", "entries": ["A-8", ...],
                   "unresolved": ["C-1858", ...]}]}]: entries as anchors in printed order. A name lost in the book or its
                   scan (a Part's number_jumps or scan_gaps), or naming no Proverb Entry, is unresolved
      warnings    every Warning, the disagreements and single reads first; a line's carries its "band"
      pages       [{"pdf", "book_page", "image", "size", "lines"}], each line laid (`lay_confirmed`) with its "state"
                   (agreed, warned or confirmed) and the ids of its "warnings"

    Pages are walked in PDF order. Across a page with no answer nothing carries over: a Topic Row, tiểu chủ đề or
    chủ đề continued after it has no owner, and the heading numbers after it go unchecked.
    """
    section, pages_in = answers["section"], {int(p): a for p, a in answers["pages"].items()}
    names = {letter: set(numbers) for letter, numbers in entry_names.get("names", {}).items()}
    unresolved, missing_parts = _unresolved(entry_names), entry_names.get("missing_parts", [])
    first_page = section["pages"][0]
    warnings = [warning(PART_MISSING, part, f"{part} had no answers.json when the index was run: the entry names of "
                        f"its letters are unchecked", first_page) for part in missing_parts]

    def line_warning(kind, page, line, reason):
        warnings.append({**warning(kind, _place(page, line), reason, page), "band": line["band"]})

    topics, laid_pages = [], []
    topic = sub = row = heading = None
    last_numeral, last_sub, previous = 0, 0, None
    for page in sorted(pages_in):
        answer = pages_in[page]
        records = list(log.get(page, []))
        if extra and extra[0] == page:
            records = sorted([r for r in records if r["band"] != extra[1]["band"]] + [extra[1]],
                             key=lambda r: r["band"][0])
        lines = lay_confirmed(answer, records)
        if previous is not None and page != previous + 1 or previous is None and page != first_page:
            topic = sub = row = heading = None
            last_numeral = last_sub = None
        previous = page
        before = f"PDF page {page - 1} has no answer" if page - 1 not in pages_in else "nothing above it holds one"
        if not answer["lines"]:
            warnings.append(warning(PAGE_MISSING, f"p{page}", f"PDF page {page} has no Index Lines: {answer['why']}",
                                    page))
        if answer.get("missed"):
            patches = answer["missed"]
            warnings.append(warning(INK_OUTSIDE, f"p{page}", f"PDF page {page} has {len(patches)} patch(es) of ink "
                                    f"outside every printed line found ({min(m[1] for m in patches)}-"
                                    f"{max(m[3] for m in patches)} px down the 300 dpi scan), in no Index Line", page))
        for line in lines:
            for kind, reason in _read_warnings(page, line):
                line_warning(kind, page, line, reason)
            kind, where = line["kind"], _line_name(page, line)
            if kind in (NOT_INDEX, UNCLASSIFIED, UNREAD):
                continue
            if kind == CHU_DE:
                # None where the model read no numeral (a Warning of its kind already)
                number = heading_number(CHU_DE, line["text"])
                if last_numeral is not None and number != last_numeral + 1:
                    expected = ROMAN[last_numeral] if last_numeral < len(ROMAN) else "no chủ đề"
                    line_warning(HEADING_NUMBER, page, line, f'{where}: chủ đề "{line["text"]}" where {expected} '
                                                             f"comes next")
                topic = {"id": ROMAN[number - 1] if number else "?", "title": "", "subtopics": []}
                topics.append(topic)
                heading, sub, row, last_numeral = topic, None, None, number
                continue
            if kind == TIEU_CHU_DE:
                number = heading_number(TIEU_CHU_DE, line["text"])
                opens = topic is not None and not topic["subtopics"]
                if number is None:
                    line_warning(HEADING_NUMBER, page, line, f'{where}: tiểu chủ đề "{line["text"]}" has no number')
                elif last_sub is not None and number != last_sub + 1 and not (opens and number == 1):
                    line_warning(HEADING_NUMBER, page, line, f"{where}: tiểu chủ đề {number} follows {last_sub}")
                if topic is None:
                    line_warning(NO_OWNER, page, line, f"{where}: tiểu chủ đề {number} has no chủ đề: {before}")
                    topic = {"id": "?", "title": "", "subtopics": []}
                    topics.append(topic)
                sub = {"id": f"{topic['id']}.{number if number is not None else '?'}", "number": number,
                       "title": tieu_chu_de_title(line["text"]), "entries": [], "unresolved": [], "letters": []}
                topic["subtopics"].append(sub)
                heading, row, last_sub = sub, None, number
                continue
            if kind == TITLE:
                if heading is None:
                    line_warning(NO_OWNER, page, line, f'{where}: title line "{line["text"]}" has no heading above it')
                else:
                    heading["title"] = f"{heading['title']} {line['text']}".strip()
                continue
            heading = None
            if kind == ROW_START:
                letter = line["letter"]
                if sub is None:
                    line_warning(NO_OWNER, page, line, f"{where}: Topic Row {letter} has no tiểu chủ đề: {before}")
                    row = None
                    continue
                if letter not in ALPHABET:
                    line_warning(LETTER_ORDER, page, line, f'{where}: "{letter}" is not a letter of the book\'s '
                                                           f"alphabet")
                elif sub["letters"] and sub["letters"][-1] in ALPHABET \
                        and ALPHABET.index(letter) <= ALPHABET.index(sub["letters"][-1]):
                    line_warning(LETTER_ORDER, page, line, f"{where}: Topic Row {letter} comes after "
                                                           f"{sub['letters'][-1]} in tiểu chủ đề {sub['id']}")
                sub["letters"].append(letter)
                row = {"letter": letter, "last": None}
            elif row is None:
                line_warning(NO_OWNER, page, line, f"{where}: numbers with no Topic Row to continue: {before}")
                continue
            falling, lost, nowhere = [], [], []
            for number in line["numbers"]:
                if row["last"] is not None and number <= row["last"]:
                    falling.append(f"{number} after {row['last']}")
                row["last"] = number
                letter, anchor = row["letter"], f"{row['letter']}-{number}"
                if any(l == letter and first <= number <= last for l, first, last in unresolved):
                    lost.append(anchor)
                elif letter in names or not missing_parts:
                    if number in names.get(letter, ()):
                        sub["entries"].append(anchor)
                    else:
                        nowhere.append(anchor)
                else:
                    sub["entries"].append(anchor)
            sub["unresolved"] += lost + nowhere
            if falling:
                line_warning(NOT_ASCENDING, page, line, f"{where}: Topic Row {row['letter']} does not go up: "
                                                        f"{', '.join(falling)}")
            if nowhere:
                line_warning(NO_ENTRY, page, line, f"{where}: no Proverb Entry is named {', '.join(nowhere)}")
        laid_pages.append({"pdf": page, "book_page": answer["book_page"], "image": answer["image"],
                           "size": answer["size"], "lines": lines})

    for p in laid_pages:
        for line in p["lines"]:
            ids = [w["id"] for w in warnings if w["page"] == p["pdf"] and w.get("band") == line["band"]]
            line["warnings"] = ids
            line["state"] = CONFIRMED if line["confirmed"] else WARNED if ids else AGREED
    for topic in topics:
        for sub in topic["subtopics"]:
            del sub["letters"]
    warnings.sort(key=lambda w: (w["kind"] not in READ_KINDS, w["page"]))
    return {"topics": topics, "warnings": warnings, "pages": laid_pages}


def preview(answers, log, entry_names, page, band, values):
    """The Warnings of PDF page `page` and the pages either side of it, whose Topic Rows its lines may continue or be
    continued by, were its line at `band` confirmed with `values`, whether or not it already is."""
    record = {"type": "confirmed_line", "page": page, "band": band, **normal_values(values)}
    result = rebuild(answers, log, entry_names, extra=(page, record))
    return [w for w in result["warnings"] if page - 1 <= w["page"] <= page + 1]
