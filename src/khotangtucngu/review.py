"""
The review log of a PDF Part's store, review.jsonl, and the Proverb Entries rebuilt with its Confirmed Spans. A Confirmed
Span is an Entry Span the developer has made final, by editing it or confirming it as it stands, where they choose to;
nobody confirms every one (docs/adr/0006-confirmed-spans-override-the-layout.md beside the GLOSSARY). Each of the log's
lines has its "time". serve.py appends them, nothing rewrites them and no run writes any:

  {"type": "confirmed", "page": 38, "pdf_sha1": "<sha1>", "band": [812, 1040], "first": 9, "last": 12, "leading": false,
   "crop": [left, top, right, bottom], "readings": [[9, "line read", "page read"], ...], "crop_reads": [[...], ...],
   "blocks": [...], "model_blocks": [...], "edited": true}
      a Confirmed Span, whole: nothing else is needed to rebuild it. Its "band" is the pixel rows of the 300 dpi scan from
      the top of its first line to the bottom of its last, which with its page names it. "edited" is whether its Blocks
      differ from the model's, "model_blocks", which a span confirmed again carries forward
  {"type": "unconfirmed", "page": 38, "band": [812, 1040]}
      that span undone: the latest "confirmed" or "unconfirmed" line of a span wins
  {"type": "printed_page", "page": 38, "printed_page": "37"}
      the page's printed number as the developer set or confirmed it; null undoes it
  {"type": "page_complete", "page": 38, "printed_page": "37", "body_start": 2}
      appended when a page's last span is confirmed, with the layout's number and first line: a run needs no layout
      request for the page while every line from body_start down falls in a band

Lines of any other type, such as the "fix" lines of earlier reviews, are ignored.

A page's answer in answers.json holds the model's Blocks everywhere, and its spans (see `lay_confirmed`), so a Confirmed
Span shows as soon as it is saved, with no run, and undoing one puts the model's Blocks back.

Standard library only, like assembly.py, citations.py and diacritics.py: cli.py copies the four into the store for
serve.py.
"""
import json
import os

from .assembly import BLOCK_KINDS, CONFIRMED_OVERLAP, LETTER, assemble, warning

REVIEW_LOG = "review.jsonl"


def _whole(value):
    return isinstance(value, int) and not isinstance(value, bool)


def band_problem(band):
    """Why `band` is not a band of pixel rows, or None."""
    if not isinstance(band, list) or len(band) != 2 or not all(_whole(row) for row in band) or band[0] >= band[1]:
        return "no band of pixel rows"
    return None


def blocks_problem(blocks):
    """Why `blocks` is not a list of Blocks, or None. They are held to the span schema's shape only, as the model's are."""
    if not isinstance(blocks, list):
        return "the Blocks are not a list"
    for i, block in enumerate(blocks, 1):
        if not isinstance(block, dict) or block.get("kind") not in BLOCK_KINDS:
            return f"Block {i} has no kind of {BLOCK_KINDS}"
        number = block.get("number")
        if not _whole(number) or number < 0:
            return f"Block {i}'s number is not a whole number"
        if not isinstance(block.get("text"), str) or not isinstance(block.get("citations", ""), str):
            return f"Block {i}'s text and Citations are not text"
    return None


def _confirmed_problem(record):
    """Why `record` is not a whole "confirmed" line, or None."""
    if band_problem(record.get("band")):
        return "no band"
    if not isinstance(record.get("pdf_sha1"), str) or not _whole(record.get("first")) or not _whole(record.get("last")):
        return "no PDF hash or Line Numbers"
    if not all(isinstance(record.get(k), list) for k in ("crop", "readings", "crop_reads")):
        return "no crop or reads"
    if not isinstance(record.get("leading"), bool) or not isinstance(record.get("edited"), bool):
        return "no Leading or edited mark"
    return blocks_problem(record.get("blocks")) or blocks_problem(record.get("model_blocks"))


def read_log(store):
    """
    The store's review log as it stands now: {"confirmed": {PDF page: its Confirmed Spans' latest lines, top to bottom},
    "printed": {PDF page: the number the developer gave it}, "complete": {PDF page: its latest "page_complete" line}}.
    """
    path = os.path.join(store, REVIEW_LOG)
    spans, printed, complete = {}, {}, {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if not isinstance(record, dict) or not _whole(record.get("page")):
                    continue
                kind, page = record.get("type"), record["page"]
                if kind == "confirmed" and _confirmed_problem(record) is None:
                    spans[(page, tuple(record["band"]))] = record
                elif kind == "unconfirmed" and band_problem(record.get("band")) is None:
                    spans.pop((page, tuple(record["band"])), None)
                elif kind == "printed_page" and (record.get("printed_page") is None
                                                 or isinstance(record["printed_page"], str)):
                    printed[page] = record["printed_page"]
                elif kind == "page_complete" and isinstance(record.get("printed_page"), str) \
                        and _whole(record.get("body_start")):
                    complete[page] = record
    confirmed = {}
    for (page, _), record in sorted(spans.items()):
        confirmed.setdefault(page, []).append(record)
    return {"confirmed": confirmed, "complete": complete,
            "printed": {page: number for page, number in printed.items() if number is not None}}


def _block_key(block):
    return (block.get("kind"), block.get("number") or 0, (block.get("text") or "").strip(),
            (block.get("citations") or "").strip())


def blocks_differ(blocks, model_blocks):
    """Whether Blocks say anything other than the model's did."""
    return [_block_key(b) for b in blocks] != [_block_key(b) for b in model_blocks]


def lay_confirmed(answer, records):
    """
    A page's answer with `records`, its Confirmed Spans' lines, laid over its spans, each span of the answer being
    {"first", "last" (its Line Numbers), "leading", "box" (its crop), "band", "blocks" ([first, last + 1] of the answer's
    Blocks), "readings", "crop_reads"}. A model span inside a band is replaced. One only partly overlapping a band was cut
    by a run without the latest log and can't be divided, so it stays, with "overlap". Each span of the result also has
    "confirmed" (a record marked "preview" isn't, so that its Blocks raise their Warnings), "edited" and "model_blocks",
    and the spans run top to bottom, with "blocks" the indexes of their Blocks in the result's.
    """
    pieces = []
    for span in answer["spans"]:
        top, bottom = span["band"]
        if any(r["band"][0] <= top and bottom <= r["band"][1] for r in records):
            continue
        first, stop = span["blocks"]
        held = answer["blocks"][first:stop]
        pieces.append(({**span, "confirmed": False, "edited": False, "model_blocks": held,
                        "overlap": any(top < r["band"][1] and r["band"][0] < bottom for r in records)}, held))
    for r in records:
        pieces.append(({"first": r["first"], "last": r["last"], "leading": r["leading"], "box": r["crop"],
                        "band": r["band"], "readings": r["readings"], "crop_reads": r["crop_reads"],
                        "confirmed": not r.get("preview"), "edited": r["edited"], "model_blocks": r["model_blocks"],
                        "overlap": False}, r["blocks"]))
    pieces.sort(key=lambda piece: piece[0]["band"][0])
    blocks, spans = [], []
    for span, held in pieces:
        spans.append({**span, "blocks": [len(blocks), len(blocks) + len(held)]})
        blocks += held
    return {**answer, "blocks": blocks, "spans": spans}


def _printed_number(page, laid, log):
    """A page's printed number: the developer's, then its "page_complete" line's while every span of it is confirmed,
    then the layout answer's."""
    if page in log["printed"]:
        return log["printed"][page]
    if page in log["complete"] and all(span["confirmed"] for span in laid["spans"]):
        return log["complete"][page]["printed_page"]
    return laid["printed_page"]


def _review_spans(laid, starts):
    """
    A page's spans for the review server: each one's crop as shares of the page, its band and Line Numbers, the indexes
    of its Blocks, whether it is confirmed, edited or cut across a band, the model's Blocks of an edited one, its kind
    ("leading", "letter" or "entry") and its label: "Leading" for a Leading span, then the letter headings and the names
    of the Proverb Entries whose Blocks on this page start in it (`starts`, [(index of the Block, name)]).
    """
    w, h = laid["size"]
    out = []
    for span in laid["spans"]:
        first, stop = span["blocks"]
        letters = [b["text"] for b in laid["blocks"][first:stop] if b.get("kind") == LETTER]
        names = [name for at, name in starts if first <= at < stop]
        kind = "leading" if span["leading"] else "entry" if names or not letters else "letter"
        label = " · ".join((["Leading"] if span["leading"] else []) + letters + names)
        left, top, right, bottom = span["box"]
        view = {"box": [round(left / w, 4), round(top / h, 4), round(right / w, 4), round(bottom / h, 4)],
                "band": span["band"], "first": span["first"], "last": span["last"], "blocks": span["blocks"],
                "confirmed": span["confirmed"], "edited": span["edited"], "overlap": span["overlap"],
                "kind": kind, "label": label or "(no Blocks)"}
        if span["edited"]:
            view["model_blocks"] = span["model_blocks"]
        out.append(view)
    return out


def rebuild(answers, log, abbreviations, book_page_offset, readings=None, flagged=None, skipped=(), gaps=()):
    """
    The Proverb Entries, Warnings and pages of assembly.assemble, built from `answers` ({PDF page: its answer}) with `log`
    (`read_log`) laid over them, and the laid answers. A Confirmed Span's Blocks and a number the developer gave raise no
    Warning; `readings` (the pages' OCR Readings) and `flagged` (their reads flagged) still hold its lines, so the other
    spans' Blocks line up against them. An entry is "fixed" when a span holding it was edited. Each page also has its
    "spans" (`_review_spans`) and "printed_confirmed", whether the developer gave its number. `skipped`: the PDF pages
    the Part skips and `gaps` its scan_gaps (assembly.assemble).
    """
    laid = {}
    for page, answer in answers.items():
        laid[page] = lay_confirmed(answer, log["confirmed"].get(page, []))
        laid[page]["printed_page"] = _printed_number(page, laid[page], log)
    confirmed = {page: {b for span in view["spans"] if span["confirmed"] for b in range(*span["blocks"])}
                 for page, view in laid.items()}
    entries, warnings, pages = assemble(laid, abbreviations, book_page_offset, readings, flagged, confirmed,
                                        set(log["printed"]), skipped, gaps)
    starts = {}
    for entry in entries:
        for page, (first, stop) in entry["blocks"].items():
            starts.setdefault(int(page), []).append((first, entry["name"]))
            entry["fixed"] = entry.get("fixed", False) or any(
                span["edited"] and first < span["blocks"][1] and span["blocks"][0] < stop
                for span in laid[int(page)]["spans"])
    for p in pages:
        page = p["pdf"]
        p["spans"] = _review_spans(laid[page], starts.get(page, []))
        p["printed_confirmed"] = page in log["printed"]
        for span in laid[page]["spans"]:
            if span["overlap"]:
                warnings.append(warning(CONFIRMED_OVERLAP, f"p{page}-L{span['first']}",
                                        f"PDF page {page}: the Entry Span of Line Numbers {span['first']}-{span['last']} "
                                        f"only partly overlaps a Confirmed Span, so their text may be doubled, until a "
                                        f"run with the latest review log cuts the page again", page))
    return entries, warnings, pages, laid


def read_answers(path):
    """The page answers a store's answers.json holds, by PDF page."""
    with open(path, encoding="utf-8") as f:
        return {int(page): answer for page, answer in json.load(f).items()}
