"""
The 63 Source Abbreviations, read from the transcribed Front Matter's Bảng chữ tắt I, and the splitting of the
printed text that cites them: Citation lines into {abbreviation, pages} ("variant" too for a Variant Citation), a
Correction into {wrong, sources, right}, and a See-also into the names of Proverb Entries.

Each split returns its result and its problems, as (Warning kind, reason) pairs.
"""
import re
import unicodedata

UNKNOWN_ABBREVIATION = "unknown_abbreviation"
CITATION_NO_PAGES, CITATION_UNSPLIT = "citation_no_pages", "citation_unsplit"
SEE_ALSO_UNSPLIT = "see_also_unsplit"

# The model may write the subscripts of VNP₁₁ and VNP₂ as plain digits
_SUBSCRIPTS = [(re.compile(r"VNP ?11(?!\d)"), "VNP₁₁"), (re.compile(r"VNP ?2(?!\d)"), "VNP₂")]
# Something shaped like a Source Abbreviation, known or not: capitals, then a volume in Roman numerals if any
_LIKE_ABBREVIATION = re.compile(r"[A-ZĐ][A-ZĐ₀-₉]+(?: [IVX]+)?(?![^\W\d_])")
# An abbreviation-shaped word ending a Correction's wrong wording: a Source the 63 don't list
_ENDING_ABBREVIATION = re.compile(r"(?:^|(?<=\s))[A-ZĐ][A-ZĐ₀-₉]+(?: [IVX]+)?$")
# The page(s) a Source of a Correction may print after it, ending the wrong wording: "TNCL 23", "NASL II 38b"
_ENDING_PAGES = re.compile(r"\s+\d+[a-z]?(?:\s*[,;-]\s*\d+[a-z]?)*$")
# Where the next abbreviation starts, ending the pages before it: two capitals at the start of a word
_NEXT_ABBREVIATION = re.compile(r"(?:^|(?<=[\s,;]))[A-ZĐ][A-ZĐ]")
# The "bk" (bản khác) that makes the Citation after it a Variant Citation, which also ends the pages before it
_VARIANT_MARK = re.compile(r"(?:^|(?<=[\s,;]))bk(?![^\W\d_])")
# A piece of a See-also between spaces and punctuation: a letter (Ă and Â are letters of their own), a number, or
# anything else. "C534" is a letter and a number
_SEE_ALSO_PART = re.compile(r"(?P<letter>[A-ZĂÂĐÊÔƠƯ])(?![^\W\d_])|(?P<number>\d+)|(?P<other>[^\s,;.]+)")
# The printed label the model may copy before a See-also's names
_SEE_ALSO_LABEL = re.compile(r"^xem thêm\s*:?\s*", re.I)
# The fewest letters an abbreviation needs to be taken for a known one a letter away: shorter ones are too alike
_NEAREST_MIN_LETTERS = 4


def _one_letter_apart(a, b):
    """Whether adding, dropping or changing one letter turns one of two different words into the other."""
    short, long = sorted((a, b), key=len)
    if len(long) - len(short) > 1:
        return False
    i = next((k for k, (x, y) in enumerate(zip(short, long)) if x != y), len(short))
    return short[i + (len(short) == len(long)):] == long[i + 1:]


def load_abbreviations(front_matter):
    """The Source Abbreviations of Bảng chữ tắt I, in printed order, from the rows "| n | ABBREVIATION | title |"."""
    with open(front_matter, encoding="utf-8") as f:
        text = f.read()
    start = text.index("## Bảng chữ tắt")
    table = text[text.index("\n### I\n", start):text.index("\n### II\n", start)]
    rows = re.findall(r"^\| *\d+ *\| *([^|]+?) *\|", table, re.M)
    if len(rows) != 63:
        raise ValueError(f"{front_matter}: Bảng chữ tắt I lists {len(rows)} Source Abbreviations, not 63")
    return rows


def clean_citation_text(text):
    """`text` composed (NFC), its spaces collapsed, and "VNP11"/"VNP2" written "VNP₁₁"/"VNP₂", as the Bảng chữ tắt
    prints them."""
    text = " ".join(unicodedata.normalize("NFC", text).split())
    for pattern, abbreviation in _SUBSCRIPTS:
        text = pattern.sub(abbreviation, text)
    return text


class Abbreviations:
    def __init__(self, known):
        self.known = set(known)
        self._longest_first = sorted(known, key=len, reverse=True)

    def at(self, text, i):
        """The longest known abbreviation that starts at `text[i]` and ends a word ("TNLG II" in "TNLG II 7", not
        "VC I" in "VC II 166"), or None."""
        for a in self._longest_first:
            end = i + len(a)
            if text.startswith(a, i) and not (end < len(text) and text[end].isalpha()):
                return a
        return None

    def nearest(self, abbreviation):
        """The one known abbreviation with the same volume whose letters are one letter from those of `abbreviation`
        ("VCVN I" for "VCSVN I"), or None if there is none or several, or it only lost its volume ("TNPD", not TNCD)."""
        letters, _, volume = abbreviation.partition(" ")
        if len(letters) < _NEAREST_MIN_LETTERS or any(a.startswith(abbreviation + " ") for a in self.known):
            return None
        near = [a for a in self.known if a.partition(" ")[2] == volume
                and a.partition(" ")[0] != letters and _one_letter_apart(a.partition(" ")[0], letters)]
        return near[0] if len(near) == 1 else None

    def unknown(self, abbreviation, text):
        """The problem of an abbreviation not among the 63, naming the volumes it may have lost ("VNP₂" for VNP₂ I or
        VNP₂ II), or the known one it was taken for."""
        volumes = sorted(a for a in self.known if a.startswith(abbreviation + " "))
        nearest = self.nearest(abbreviation)
        hint = f" (no volume: {' or '.join(volumes)}?)" if volumes else f" (taken as {nearest})" if nearest else ""
        return UNKNOWN_ABBREVIATION, f'unknown Source Abbreviation "{abbreviation}"{hint} in "{text}"'

    def split(self, raw):
        """Printed Citations "HT 63 NL 7 TNLG II 7, 25" -> [{"abbreviation": "HT", "pages": "63"}, ...], the pages
        as printed: what follows an abbreviation up to the next one (or a "bk"). A Citation after "bk" is a Variant
        Citation, {"abbreviation": "VD", "pages": "", "variant": True}, and may have no pages: "VC I 11 bk VD". An
        unknown abbreviation one letter from a known one is kept as the known one, still with its problem (`nearest`)."""
        text = clean_citation_text(raw)
        citations, problems, i, variant = [], [], 0, False
        while True:
            while i < len(text) and text[i] in " ,;.":
                i += 1
            if i == len(text):
                break
            if _VARIANT_MARK.match(text, i):
                i, variant = i + 2, True
                continue
            abbreviation = printed = self.at(text, i)
            if abbreviation is None:
                m = _LIKE_ABBREVIATION.match(text, i)
                if m is None:
                    stop = self._next(text, i + 1)
                    problems.append((CITATION_UNSPLIT, f'cannot split "{text[i:stop].strip()}" of the Citations '
                                                       f'"{text}"'))
                    i = stop
                    continue
                printed = m.group()
                abbreviation = self.nearest(printed) or printed
                problems.append(self.unknown(printed, text))
            end = i + len(printed)
            stop = self._next(text, end)
            pages = text[end:stop].strip(" ,;.")
            citation = {"abbreviation": abbreviation, "pages": pages}
            if variant:
                citation["variant"], variant = True, False
            elif not pages:
                problems.append((CITATION_NO_PAGES, f'"{abbreviation}" has no pages in "{text}"'))
            citations.append(citation)
            i = stop
        if variant:
            problems.append((CITATION_UNSPLIT, f'"bk" names no Source in "{text}"'))
        return citations, problems

    @staticmethod
    def _next(text, i):
        """Where the next Citation of `text` starts at or after `i`: its abbreviation or its "bk"; or the end."""
        found = [m.start() for m in (_NEXT_ABBREVIATION.search(text, i), _VARIANT_MARK.search(text, i)) if m]
        return min(found, default=len(text))

    def split_correction(self, raw, cited=()):
        """A Correction "Nằm giữa mất... CCM = Nằm giữa *không* mất..." -> {"wrong": "Nằm giữa mất...", "sources":
        ["CCM"], "right": "Nằm giữa *không* mất..."}: the Source Abbreviations are the abbreviation-shaped words that
        end the wording before "=", each known or raising an unknown-abbreviation problem. One printed without its
        volume ("VCVN") is the volume its Proverb Entry cites, if `cited`, the entry's abbreviations, holds just one."""
        text = clean_citation_text(raw)
        left, eq, right = text.partition("=")
        sources, problems, wrong = [], [], left.rstrip(" ,;")
        while True:
            # A Source may print its page after it, "TNCL 23": the page goes with it, and stays if no Source is before it
            cut = _ENDING_PAGES.sub("", wrong)
            found = source = next((a for a in self._longest_first
                                   if cut.endswith(a) and (len(cut) == len(a) or not cut[-len(a) - 1].isalpha())),
                                  None)
            if found is None:
                m = _ENDING_ABBREVIATION.search(cut)
                if m is None:
                    break
                found = m.group()
                volumes = {a for a in cited if a.startswith(found + " ") and a in self.known}
                if len(volumes) == 1:
                    source = volumes.pop()
                else:
                    source = self.nearest(found) or found
                    problems.append(self.unknown(found, text))
            sources.insert(0, source)
            wrong = cut[:-len(found)].rstrip(" ,;")
        correction = {"wrong": wrong, "sources": sources, "right": right.strip()}
        if not eq or not sources or not wrong or not correction["right"]:
            problems.append((CITATION_UNSPLIT, f'cannot split the Correction "{text}" into wrong wording, Source '
                                               f'Abbreviations, "=" and right wording'))
        return correction, problems


def see_also_names(raw):
    """The names a See-also prints, "M 526 T 65" -> ["M 526", "T 65"]; a number printed without its letter is the
    letter's before it, "Ă 86, 109" -> ["Ă 86", "Ă 109"]. Anything else, or a letter with no number, is a problem.
    The text whole if it holds no name."""
    text = _SEE_ALSO_LABEL.sub("", clean_citation_text(raw))
    names, unread, letter, numbered = [], [], None, True
    for m in _SEE_ALSO_PART.finditer(text):
        if m["letter"]:
            if not numbered:
                unread.append(letter)
            letter, numbered = m["letter"], False
        elif m["number"] and letter:
            names.append(f"{letter} {int(m['number'])}")
            numbered = True
        else:
            unread.append(m.group())
    if not numbered:
        unread.append(letter)
    problems = [(SEE_ALSO_UNSPLIT, f'cannot read "{piece}" of the See-also "{text}" as a Proverb Entry\'s name')
                for piece in unread]
    return names or [text], problems
