"""
Assembly: the verbatim Proverb Entries of a PDF Part, built by code from every saved page answer, and the Warnings
about anything that looks wrong in them. Nothing is expanded: the text is as the model copied it from the print, with
the italic words of Variants and Corrections between asterisks.

Pages are walked in PDF order. A run of consecutive PDF pages with answers is read as one stretch of the book: a
Leading Block joins the last Proverb Entry of the page before, and entry numbers run on. Across a page with no answer
nothing carries over: the next stretch starts afresh.

Standard library only, importing only citations.py and diacritics.py, relatively: cli.py copies them, this file and
review.py into the store, where serve.py rebuilds the entries with the developer's Fixes.
"""
import hashlib
import json
import unicodedata

from .citations import see_also_names
from .diacritics import disagreements

# The kinds of Block a page answer holds (prompts.py tells the model what each is)
LETTER, PROVERB, CITATIONS, VARIANT, NOTE, CORRECTION, SEE_ALSO = (
    "letter", "proverb", "citations", "variant", "note", "correction", "see_also")
BLOCK_KINDS = [LETTER, PROVERB, CITATIONS, VARIANT, NOTE, CORRECTION, SEE_ALSO]

# Phàm lệ II.1
ALPHABET = "A Ă Â B C D Đ E Ê G H I K L M N O Ô Ơ P Q R S T U Ư V X Y".split()
# The tone marks, which the letter of a proverb's first word drops (Ả is under A); the breve, the circumflex and the
# horn make letters of their own (Ă, Â, Ơ)
_TONES = {"̀", "́", "̃", "̉", "̣"}

NUMBER_GAP, NUMBER_DUPLICATE, LETTER_ORDER = "number_gap", "number_duplicate", "letter_order"
PAGE_NUMBER, PAGE_MISSING, NO_OWNER = "page_number", "page_missing", "no_owner"
DIACRITIC = "diacritic_disagreement"
# Raised by cli.py, not here: ink on a page outside every printed line found, which no Entry Span holds
INK_OUTSIDE = "ink_outside"


def warning(kind, place, reason, page):
    """A Warning: something in the transcription for the developer to look at, with its reason and its PDF page. Its
    id, from its kind and `place`, stays the same when the outputs are rebuilt."""
    return {"id": f"{kind}:{place}", "kind": kind, "reason": reason, "page": page}


def answer_sha1(answer):
    """The hash of a page answer, which a Fix made against it records."""
    return hashlib.sha1(json.dumps(answer, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()


def first_letter(text):
    """The letter of the alphabet a proverb is ordered under: its first letter without its tone mark."""
    for ch in text:
        if ch.isalpha():
            bare = "".join(c for c in unicodedata.normalize("NFD", ch) if c not in _TONES)
            return unicodedata.normalize("NFC", bare).upper()
    return ""


def _page_number_warnings(answers, book_page_offset):
    """A Warning for each page whose printed number isn't the book page its PDF page makes it (PDF page +
    `book_page_offset`), or that prints none though it opens no letter: only a letter's first page prints none."""
    warnings = []
    for p in sorted(answers):
        printed = unicodedata.normalize("NFC", str(answers[p].get("printed_page", ""))).strip()
        expected = p + book_page_offset
        if not printed:
            if not any(b.get("kind") == LETTER for b in answers[p].get("blocks") or []):
                warnings.append(warning(PAGE_NUMBER, f"p{p}", f"PDF page {p} prints no page number, though it opens "
                                        f"no letter: book page {expected} expected", p))
        elif printed != str(expected):
            warnings.append(warning(PAGE_NUMBER, f"p{p}", f'PDF page {p} prints page number "{printed}": book page '
                                    f"{expected} expected", p))
    return warnings


def _new_entry(letter, number, text, page, book_page):
    return {"name": f"{letter} {number}", "letter": letter, "number": number, "proverb": text.strip(),
            "citations": [], "variants": [], "notes": [], "corrections": [], "see_also": [],
            "book_pages": [book_page], "pdf_pages": [page], "blocks": {}}


def _on_page(entry, page, book_page, b):
    """`entry` holds Block `b` of PDF page `page`: its Blocks there run from the first such `b` to this one."""
    if page not in entry["pdf_pages"]:
        entry["pdf_pages"].append(page)
    if book_page not in entry["book_pages"]:
        entry["book_pages"].append(book_page)
    entry["blocks"].setdefault(str(page), [b, b])[1] = b + 1


def _unique_ids(warnings):
    """`warnings` with a repeated id made unique by its count, "#2" on, in order: vlm_requests.unique_ids, which this
    file can't import, as it must stay standard library only."""
    seen = {}
    for w in warnings:
        seen[w["id"]] = seen.get(w["id"], 0) + 1
        if seen[w["id"]] > 1:
            w["id"] += f"#{seen[w['id']]}"
    return warnings


def _diacritic_warnings(page, blocks, reading, owners):
    """A Diacritic Disagreement Warning for each syllable of a page's `blocks` that its OCR Readings (`reading`,
    joined) mark otherwise, one per Proverb Entry (`owners`, by Block) and pair of readings, with how often it came."""
    counts = {}
    for b, ours, theirs in disagreements(blocks, reading):
        key = (owners[b], ours, theirs)
        counts[key] = counts.get(key, 0) + 1
    warnings = []
    for (owner, ours, theirs), n in counts.items():
        where = f"{owner}: " if owner else f"PDF page {page}: "
        times = f" ({n} times)" if n > 1 else ""
        warnings.append(warning(DIACRITIC, f"p{page}-{owner}" if owner else f"p{page}", f'{where}"{ours}" where the '
                                f'OCR Reading has "{theirs}"{times}', page))
    return warnings


def assemble(answers, abbreviations, book_page_offset, readings=None):
    """
    `answers`: {PDF page: its current page answer}; `abbreviations`: citations.Abbreviations; `book_page_offset`: the
    Part's book page minus PDF page; `readings`: {PDF page: its OCR Readings joined}, which a page's Blocks are checked
    against for Diacritic Disagreements (none for a page without). Returns the verbatim
    Proverb Entries in book order, the Warnings they raise (all but failed or missing pages), and each page's
    {"pdf", "book_page", "printed_page", "answer_sha1", "entries"}, the names of the entries it holds. An entry's
    "blocks" is {PDF page (a string): [first, last + 1]}, the indexes of its Blocks in that page's answer.
    """
    entries, warnings, pages = [], _page_number_warnings(answers, book_page_offset), []
    seen = {}               # entry name -> its entry, for duplicates
    letter = None           # the letter of the stretch's last heading or entry
    current = None          # the entry the next Block belongs to
    previous = None         # the stretch's last entry, for number continuity
    headed = False          # a letter heading came since the stretch's last entry
    last_heading = None     # the last letter heading read, across stretches, for the book's order
    last_page = None
    unowned = ""            # why a Block with no entry to join has none

    def report(problems, page, owner):
        """A Warning for each (kind, reason) problem of a split of `owner`'s Citations or Correction."""
        for kind, reason in problems:
            warnings.append(warning(kind, f"p{page}-{owner}", f"{owner}: {reason}", page))

    def cite(raw, page, owner):
        citations, problems = abbreviations.split(raw)
        report(problems, page, owner)
        return citations

    for page in sorted(answers):
        if last_page is None or page != last_page + 1:
            letter, current, previous, headed = None, None, None, False
            unowned = f"PDF page {page - 1} has no answer"
        last_page = page
        book_page = str(page + book_page_offset)
        names, unowned_kinds = [], []
        blocks = answers[page].get("blocks") or []
        owners = [None] * len(blocks)    # the name of the Proverb Entry each Block joins
        for b, block in enumerate(blocks):
            kind, text = block.get("kind"), unicodedata.normalize("NFC", block.get("text") or "").strip()
            if kind == LETTER:
                heading = text.upper()
                order = ALPHABET.index(heading) if heading in ALPHABET else -1
                latest = max((x for x in (last_heading, letter) if x in ALPHABET), key=ALPHABET.index, default=None)
                if order < 0:
                    warnings.append(warning(LETTER_ORDER, f"p{page}-{heading}", f'letter heading "{text}" is not a '
                                            f"letter of the book's alphabet", page))
                elif latest is not None and order <= ALPHABET.index(latest):
                    warnings.append(warning(LETTER_ORDER, f"p{page}-{heading}", f'letter heading "{text}" comes '
                                            f"after {latest}", page))
                if order >= 0:
                    last_heading = heading
                # A heading misread as no letter of the alphabet names nothing: the next proverb's letter is used
                letter = heading if order >= 0 else None
                current, headed, unowned = None, True, "they follow a letter heading"
                continue
            if kind == PROVERB:
                if letter is None:
                    letter = first_letter(text)
                number = int(block.get("number") or 0)
                entry = _new_entry(letter, number, text, page, book_page)
                _on_page(entry, page, book_page, b)
                name = entry["name"]
                # The model often puts the Citation lines on the proverb's own Block, not a Citations Block after it
                entry["citations"] += cite(block.get("citations") or "", page, name)
                if name in seen:
                    warnings.append(warning(NUMBER_DUPLICATE, f"p{page}-{name}", f"{name} appears again, first on "
                                            f"PDF page {seen[name]['pdf_pages'][0]}", page))
                elif headed and number != 1:
                    warnings.append(warning(NUMBER_GAP, f"p{page}-{name}", f"letter {letter} opens with {name}, "
                                            f"not {letter} 1", page))
                elif previous is not None and not headed and previous["letter"] == letter \
                        and number != previous["number"] + 1:
                    warnings.append(warning(NUMBER_GAP, f"p{page}-{name}", f"{name} follows {previous['name']}", page))
                seen.setdefault(name, entry)
                entries.append(entry)
                names.append(name)
                owners[b] = name
                current, previous, headed = entry, entry, False
                continue
            if current is None:
                unowned_kinds.append(kind)
                continue
            _on_page(current, page, book_page, b)
            owners[b] = current["name"]
            if current["name"] not in names:
                names.append(current["name"])
            if kind == CITATIONS:
                current["citations"] += cite(text, page, current["name"])
            elif kind == VARIANT:
                current["variants"].append({"text": text,
                                            "citations": cite(block.get("citations") or "", page, current["name"])})
            elif kind == NOTE:
                current["notes"].append(text)
            elif kind == CORRECTION:
                correction, problems = abbreviations.split_correction(text)
                current["corrections"].append(correction)
                report(problems, page, current["name"])
            elif kind == SEE_ALSO:
                current["see_also"] += see_also_names(text)
        if readings and page in readings:
            warnings += _diacritic_warnings(page, blocks, readings[page], owners)
        if unowned_kinds:
            warnings.append(warning(NO_OWNER, f"p{page}", f"PDF page {page} has {len(unowned_kinds)} Block(s) "
                                    f"({', '.join(unowned_kinds)}) with no Proverb Entry to join: {unowned}", page))
        pages.append({"pdf": page, "book_page": book_page, "printed_page": answers[page].get("printed_page", ""),
                      "answer_sha1": answer_sha1(answers[page]), "entries": names})
    return entries, _unique_ids(warnings), pages

