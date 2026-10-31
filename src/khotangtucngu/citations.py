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

# The model may write the subscripts of VNP₁₁ and VNP₂ as plain digits
_SUBSCRIPTS = [(re.compile(r"VNP ?11(?!\d)"), "VNP₁₁"), (re.compile(r"VNP ?2(?!\d)"), "VNP₂")]
# Something shaped like a Source Abbreviation, known or not: capitals, then a volume in Roman numerals if any
_LIKE_ABBREVIATION = re.compile(r"[A-ZĐ][A-ZĐ₀-₉]+(?: [IVX]+)?(?![^\W\d_])")
# An abbreviation-shaped word ending a Correction's wrong wording: a Source the 63 don't list
_ENDING_ABBREVIATION = re.compile(r"(?:^|(?<=\s))[A-ZĐ][A-ZĐ₀-₉]+(?: [IVX]+)?$")
# Where the next abbreviation starts, ending the pages before it: two capitals at the start of a word
_NEXT_ABBREVIATION = re.compile(r"(?:^|(?<=[\s,;]))[A-ZĐ][A-ZĐ]")
# The "bk" (bản khác) that makes the Citation after it a Variant Citation, which also ends the pages before it
_VARIANT_MARK = re.compile(r"(?:^|(?<=[\s,;]))bk(?![^\W\d_])")
# A See-also name: a letter (Ă and Â are letters of their own) and a number, written "C 534"
_NAME = re.compile(r"([A-ZĂÂĐÊÔƠƯ])\s*(\d+)")


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

    def unknown(self, abbreviation, text):
        """The problem of an abbreviation not among the 63, naming the volumes it may have lost ("VNP₂" for VNP₂ I or
        VNP₂ II)."""
        volumes = sorted(a for a in self.known if a.startswith(abbreviation + " "))
        hint = f" (no volume: {' or '.join(volumes)}?)" if volumes else ""
        return UNKNOWN_ABBREVIATION, f'unknown Source Abbreviation "{abbreviation}"{hint} in "{text}"'

    def split(self, raw):
        """Printed Citations "HT 63 NL 7 TNLG II 7, 25" -> [{"abbreviation": "HT", "pages": "63"}, ...], the pages
        as printed: what follows an abbreviation up to the next one (or a "bk"). A Citation after "bk" is a Variant
        Citation, {"abbreviation": "VD", "pages": "", "variant": True}, and may have no pages: "VC I 11 bk VD"."""
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
            abbreviation = self.at(text, i)
            if abbreviation is None:
                m = _LIKE_ABBREVIATION.match(text, i)
                if m is None:
                    stop = self._next(text, i + 1)
                    problems.append((CITATION_UNSPLIT, f'cannot split "{text[i:stop].strip()}" of the Citations '
                                                       f'"{text}"'))
                    i = stop
                    continue
                abbreviation = m.group()
                problems.append(self.unknown(abbreviation, text))
            end = i + len(abbreviation)
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

    def split_correction(self, raw):
        """A Correction "Nằm giữa mất... CCM = Nằm giữa *không* mất..." -> {"wrong": "Nằm giữa mất...", "sources":
        ["CCM"], "right": "Nằm giữa *không* mất..."}: the Source Abbreviations are the abbreviation-shaped words that
        end the wording before "=", each known or raising an unknown-abbreviation problem."""
        text = clean_citation_text(raw)
        left, eq, right = text.partition("=")
        sources, problems, wrong = [], [], left.rstrip(" ,;")
        while True:
            found = next((a for a in self._longest_first
                          if wrong.endswith(a) and (len(wrong) == len(a) or not wrong[-len(a) - 1].isalpha())), None)
            if found is None:
                m = _ENDING_ABBREVIATION.search(wrong)
                if m is None:
                    break
                found = m.group()
                problems.append(self.unknown(found, text))
            sources.insert(0, found)
            wrong = wrong[:-len(found)].rstrip(" ,;")
        correction = {"wrong": wrong, "sources": sources, "right": right.strip()}
        if not eq or not sources or not wrong or not correction["right"]:
            problems.append((CITATION_UNSPLIT, f'cannot split the Correction "{text}" into wrong wording, Source '
                                               f'Abbreviations, "=" and right wording'))
        return correction, problems


def see_also_names(raw):
    """The names a See-also prints, "M 526 T 65" -> ["M 526", "T 65"]; the text whole if it holds none."""
    names = [f"{letter} {number}" for letter, number in _NAME.findall(raw)]
    return names or [raw.strip()]
