"""
A page's two Vision reads compared, and its Blocks checked against them (vocabulary:
vsc-project/khoTangTucNguoiNguoiViet/GLOSSARY.md; docs/adr/0005-two-reads-and-model-edits.md beside it). The two reads
of a line are lined up exactly: what they share, in letters of the Vietnamese alphabet only, is Agreed, and the rest
Disputed. The Blocks and the OCR Readings are then lined up by their bare letters, the diacritics and the bar of đ left
out. A syllable whose bare letters match the OCR Reading's but whose marks don't is a Diacritic Disagreement, unless the
syllable is Agreed: any change to an Agreed Syllable is a Model Edit. The Blocks keep their own reading: the Warning
only points the developer at the syllable.

Standard library only, like assembly.py, which imports it relatively: cli.py copies it into the store for serve.py.
"""
import difflib
import functools
import re
import unicodedata

_SYLLABLE = re.compile(r"\w+")
# The letters of the Vietnamese alphabet, in NFC, with each vowel's five tone marks
_LETTERS = frozenset("bcdđghklmnpqrstvx") | {unicodedata.normalize("NFC", vowel + tone) for vowel in "aăâeêioôơuưy"
                                             for tone in ("", "̀", "́", "̃", "̉", "̣")}
# The labels printed in the book and read by Vision, which the Blocks never hold
_LABELS = (("bk",), ("xem", "thêm"), ("sửa", "lại"))
# The Blocks whose text a Model Edit is raised on: the reads garble Citations and See-alsos
_EDITED_KINDS = ("proverb", "variant", "note", "correction")
# A syllable only a page read has is behind an added syllable this many syllables away, as the lining up can shift
_BEHIND_REACH = 2
# What a Model Edit did to a syllable
CHANGED, DROPPED, ADDED = "changed", "dropped", "added"


def _spans(text):
    """The syllables of `text` (in NFC) as (lowercase syllable, start, end)."""
    return [(m.group().lower(), m.start(), m.end()) for m in _SYLLABLE.finditer(text)]


def syllables(text):
    """The syllables (and numbers) of `text` in order, lowercase, in NFC; asterisks and punctuation dropped."""
    return [s for s, _, _ in _spans(unicodedata.normalize("NFC", text))]


def bare(syllable):
    """A syllable's letters without their diacritics: "võng" and "vồng" are both "vong", "đôi" is "doi"."""
    letters = "".join(c for c in unicodedata.normalize("NFD", syllable) if not unicodedata.combining(c))
    return letters.replace("đ", "d")


@functools.lru_cache(maxsize=4096)
def _opcodes(ours, theirs):
    return difflib.SequenceMatcher(None, ours, theirs, autojunk=False).get_opcodes()


def _lined_up(ours, theirs):
    """The stretches of two lists of syllables, each worked out once: the review server rebuilds every page per preview,
    and a page's Blocks are lined up the same way for both kinds of Warning."""
    return _opcodes(tuple(ours), tuple(theirs))


def _agreeable(syllable):
    """Whether a syllable both reads share counts as Agreed: only letters of the Vietnamese alphabet, so no digits and
    nothing like "хó" with a Cyrillic letter."""
    return all(c in _LETTERS for c in syllable)


def _label_places(line):
    """The indexes in `line` (a line's syllables) of the labels the Blocks never hold."""
    places = set()
    for label in _LABELS:
        for i in range(len(line) - len(label) + 1):
            if tuple(line[i:i + len(label)]) == label:
                places.update(range(i, i + len(label)))
    return places


def read_of_line(line_read, page_read):
    """The read a line's OCR Reading is: its line read, or its page read if the line read holds no syllable."""
    return line_read if syllables(line_read) else page_read


def flagged_reads(reads):
    """
    The two reads of a page's lines, `reads` as [(line read, page read)], flagged for checking Blocks against: {
    "syllables": [[syllable, Agreed?, counts if dropped?]] for each syllable of the lines' OCR Readings joined, in
    order, "page_only": [[index in "syllables" it would go before, syllable]] for the syllables only a page read has}.
    A line with one read has no Agreed Syllable. A label the Blocks never hold doesn't count if dropped, nor does a
    syllable of two or more letters printed all in capitals, as those are Source Abbreviations, so that a Citation can't
    raise a Model Edit.
    """
    marked, page_only = [], []
    for line_read, page_read in reads:
        line = unicodedata.normalize("NFC", line_read)
        spans, page = _spans(line), syllables(page_read)
        if not spans or not page:
            marked += [[s, False, False] for s in syllables(read_of_line(line_read, page_read))]
            continue
        ours, at = [s for s, _, _ in spans], len(marked)
        agreed, labels = [False] * len(ours), _label_places(ours)
        for op, i1, i2, j1, j2 in _lined_up(ours, page):
            if op == "equal":
                agreed[i1:i2] = [_agreeable(s) for s in ours[i1:i2]]
            else:
                page_only += [[at + i1, s] for s in page[j1:j2]]
        marked += [[s, agreed[i], agreed[i] and i not in labels and not (len(s) > 1 and line[start:end].isupper())]
                   for i, (s, start, end) in enumerate(spans)]
    return {"syllables": marked, "page_only": page_only}


def marked_reading(line_read, page_read):
    """
    The line read of a line with both reads, each Disputed Syllable written as [line read|page read]: "Ai chết trước
    thì được [mồ|mô] mả." A stretch where the reads have different numbers of syllables is marked whole:
    "[VC I 10|VC110]".
    """
    line, page = unicodedata.normalize("NFC", line_read), unicodedata.normalize("NFC", page_read)
    ours, theirs = _spans(line), _spans(page)
    out, at = [], 0
    for op, i1, i2, j1, j2 in _lined_up([s for s, _, _ in ours], [s for s, _, _ in theirs]):
        stretches = [(i1, i2, j1, j2)]
        if i2 - i1 == j2 - j1:
            stretches = [(i1 + k, i1 + k + 1, j1 + k, j1 + k + 1) for k in range(i2 - i1)]
        for x1, x2, y1, y2 in stretches:
            # A stretch only the page read has goes before the line read's next syllable
            start = ours[x1][1] if x1 < len(ours) else len(line)
            stop = ours[x2 - 1][2] if x2 > x1 else start
            out.append(line[at:start])
            if op == "equal" and _agreeable(ours[x1][0]):
                out.append(line[start:stop])
            else:
                out.append(f"[{line[start:stop]}|{page[theirs[y1][1]:theirs[y2 - 1][2]] if y2 > y1 else ''}]")
            at = stop
    return "".join(out) + line[at:]


def _block_syllables(blocks):
    """[(index of the Block, its syllable, whether it is of the Block's text)] for each syllable of `blocks`, their
    `text` then `citations`."""
    return [(b, s, field == "text") for b, block in enumerate(blocks) for field in ("text", "citations")
            for s in syllables(block.get(field) or "")]


def disagreements(blocks, reading, flagged=None):
    """
    [(index of the Block, its syllable, the OCR Reading's)] for each syllable of `blocks` (a page answer's, their
    `text` then `citations`) lined up with one of `reading` (the page's OCR Readings joined) by its bare letters,
    whose diacritics differ, unless `flagged` (`flagged_reads`) has that syllable Agreed. Syllables that don't line up,
    such as a word one side dropped, are not compared.
    """
    ours = _block_syllables(blocks)
    theirs = syllables(reading)
    out = []
    for op, i1, i2, j1, _ in _lined_up([bare(s) for _, s, _ in ours], [bare(s) for s in theirs]):
        if op == "equal":
            out += [(ours[i][0], ours[i][1], theirs[j1 + k]) for k, i in enumerate(range(i1, i2))
                    if ours[i][1] != theirs[j1 + k] and not (flagged and flagged["syllables"][j1 + k][1])]
    return out


def model_edits(blocks, flagged):
    """
    [(index of the Block, what the model did, its syllable or None, the reads' syllable or None)] for each Model Edit
    in the text of `blocks` (a page answer's), lined up by bare letters with `flagged` (`flagged_reads`):
    - CHANGED: a syllable lined up, or paired one-to-one in a stretch of equal length, with an Agreed Syllable it
      differs from;
    - DROPPED: an Agreed Syllable the Blocks left out, in a stretch of or next to their text;
    - ADDED: a syllable no read has behind it, in a stretch of the Blocks with only Agreed Syllables or none across
      from it, and not one only a page read has at that place.
    """
    ours = _block_syllables(blocks)
    theirs = flagged["syllables"]

    def edited(i):
        return (0 <= i < len(ours) and ours[i][2]
                and blocks[ours[i][0]].get("kind") in _EDITED_KINDS)

    out = []
    for op, i1, i2, j1, j2 in _lined_up([bare(s) for _, s, _ in ours], [bare(s) for s, _, _ in theirs]):
        if i2 - i1 == j2 - j1:
            for k in range(i2 - i1):
                b, s, _ = ours[i1 + k]
                t, agreed, _ = theirs[j1 + k]
                if agreed and s != t and edited(i1 + k):
                    out.append((b, CHANGED, s, t))
            continue
        near = [i for i in (range(i1, i2) if i2 > i1 else (i1 - 1, i1)) if edited(i)]
        if not near:
            continue
        across = theirs[j1:j2]
        out += [(ours[near[0]][0], DROPPED, None, t) for t, agreed, counts in across if agreed and counts]
        if all(agreed for _, agreed, _ in across):
            behind = {bare(s) for at, s in flagged["page_only"] if j1 - _BEHIND_REACH <= at <= j2 + _BEHIND_REACH}
            out += [(ours[i][0], ADDED, ours[i][1], None) for i in range(i1, i2)
                    if edited(i) and bare(ours[i][1]) not in behind]
    return out
