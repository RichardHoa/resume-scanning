"""
The diacritics of a page's Blocks checked against its OCR Readings (vocabulary: vsc-project/khoTangTucNguoiNguoiViet/
GLOSSARY.md). Both are cut into syllables, which are lined up by their bare letters, the diacritics and the bar of đ
left out; a syllable whose bare letters match the OCR Reading's but whose marks don't is a Diacritic Disagreement. The
Blocks keep their own reading: the Warning only points the developer at the syllable.

Standard library only, like assembly.py, which imports it relatively: cli.py copies it into the store for serve.py.
"""
import difflib
import re
import unicodedata

_SYLLABLE = re.compile(r"\w+")


def syllables(text):
    """The syllables (and numbers) of `text` in order, lowercase, in NFC; asterisks and punctuation dropped."""
    return _SYLLABLE.findall(unicodedata.normalize("NFC", text).lower())


def bare(syllable):
    """A syllable's letters without their diacritics: "võng" and "vồng" are both "vong", "đôi" is "doi"."""
    letters = "".join(c for c in unicodedata.normalize("NFD", syllable) if not unicodedata.combining(c))
    return letters.replace("đ", "d")


def disagreements(blocks, reading):
    """
    [(index of the Block, its syllable, the OCR Reading's)] for each syllable of `blocks` (a page answer's, their
    `text` then `citations`) lined up with one of `reading` (the page's OCR Readings joined) by its bare letters,
    whose diacritics differ. Syllables that don't line up, such as a word one side dropped, are not compared.
    """
    ours = [(b, s) for b, block in enumerate(blocks)
            for s in syllables(f"{block.get('text') or ''} {block.get('citations') or ''}")]
    theirs = syllables(reading)
    matcher = difflib.SequenceMatcher(None, [bare(s) for _, s in ours], [bare(s) for s in theirs], autojunk=False)
    out = []
    for op, i1, i2, j1, _ in matcher.get_opcodes():
        if op == "equal":
            out += [(ours[i][0], ours[i][1], theirs[j1 + k]) for k, i in enumerate(range(i1, i2))
                    if ours[i][1] != theirs[j1 + k]]
    return out
