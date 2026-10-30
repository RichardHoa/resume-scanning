"""
Export: website-ready data from the verbatim Proverb Entries of every transcribed PDF Part, run locally with no GPU.

    python3 -m src.khotangtucngu.export

Exports each Part in settings.PARTS whose store has an entries.json, in one go, so a See-also names an entry of any
of them: an Unresolved See-also of Part 1 resolves by itself once Part 2 is transcribed and the export is run again.
Each Part's store/<part>/export/ is emptied and written afresh, and nothing outside it is touched:

  letters/<letter>.json       one record per Proverb Entry of the letter, in book order (see `record`)
  sources.json                the 63 Sources by Source Abbreviation, in printed order: title, author, kind, year where
                              Phàm lệ II.2 dates it, and the text of its Source Note (Markdown)
  intro.md                    the Front Matter without HTML comments, ⚠ markers, quick links or the derived table
  expansions.json             every Expansion of a General Abbreviation made, with its entry and the text around it
  unresolved_see_also.json    every Unresolved See-also, for information

Fixes from the store's review.jsonl that are not stale replace the model's Proverb Entries first. Notes, Variants and
Corrections are lists of spans, {"text"} plus, where it applies: "em" (printed in italics), "strong" (the corrected
words of a Correction), "source" (a Source Abbreviation, the key of its Source in sources.json) or "general" (a General
Abbreviation, whose "text" is its Expansion). The proverb is plain text.
"""
import os
import sys

# Ensure repository root is in sys.path for 'src' package imports
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import argparse
import json
import re
import shutil
import unicodedata

from src.khotangtucngu.citations import clean_citation_text, load_abbreviations
from src.khotangtucngu.settings import FRONT_MATTER, PARTS, STORE_DIR
from src.providers.vlm_requests import read_json, write_json

VARIANT_LABEL = "Bản khác"
# A See-also's preview is this many words of the proverb it names
PREVIEW_WORDS = 6
# An Expansion is listed with this many characters of its note on each side
CONTEXT_CHARS = 40
CORRECTION_SENTENCE = ('Sách {sources} in sai thành "{wrong}". Nhóm biên soạn cho đây là lỗi in, không phải dị bản, '
                       'và sửa lại thành "{right}".')

_COMMENT = re.compile(r"[ \t]*<!--.*?-->", re.S)
_ITALIC = re.compile(r"\*([^*]+)\*")
_VOLUME = re.compile(r" [IVX]+$")
# "BK" or "- " the model may have left before a Variant's wording
_VARIANT_PREFIX = re.compile(r"^(?:(?:BK|bk)\b[\s:]*)?(?:-\s+)?")


# -- the Front Matter

def _section(text, heading, level):
    """The body of the Markdown section `heading` (its full line), up to the next heading of `level` or above."""
    start = text.index(f"\n{heading}\n") + len(heading) + 2
    m = re.compile(rf"^#{{1,{level}}} ", re.M).search(text, start)
    return text[start:m.start() if m else len(text)]


def general_abbreviations(front_matter):
    """{short form: its full words} for the 15 General Abbreviations of Bảng chữ tắt II."""
    section = _section(front_matter, "### II", 3)
    rows = dict(re.findall(r"^\| *([^|#\-][^|]*?) *\| *([^|]+?) *\|$", section, re.M))
    rows.pop("Chữ tắt", None)
    if len(rows) != 15:
        raise ValueError(f"Bảng chữ tắt II lists {len(rows)} General Abbreviations, not 15")
    return rows


def dated_sources(front_matter):
    """{Source Abbreviation: year} for the Sources Phàm lệ II.2 dates (CNGN 1896, ...). KSK, "trước Cách mạng Tháng
    Tám (1945)", has no year of its own and is left out."""
    section = _section(front_matter, "#### 2. Tiêu chí chọn bản chính", 4)
    return {a: int(y) for a, y in re.findall(r"^\s+(\S+) (\d{4})$", section, re.M)}


def year_of(abbreviation, dated):
    """The year of a Source, or of the book it is a volume of (NASL II is NASL, 1925), or None."""
    return dated.get(abbreviation, dated.get(_VOLUME.sub("", abbreviation)))


def _source_notes(front_matter):
    """{anchor id ("qn-6"): the text of its Source Note} from Phàm lệ I.B, each up to the next note or heading."""
    section = _COMMENT.sub("", _section(front_matter, "#### B/ Những sách dùng để biên soạn", 4))
    notes = {}
    for m in re.finditer(r'^<a id="([^"]+)"></a>\n#{6} [^\n]*\n(.*?)(?=^<a id=|^#{1,5} |\Z)', section, re.M | re.S):
        notes[m.group(1)] = m.group(2).strip()
    return notes


def sources(front_matter, abbreviations, dated):
    """The 63 Sources, from the Front Matter's derived table joined to the Source Notes of Phàm lệ I.B."""
    table = _section(front_matter, "## Bảng đối chiếu kí hiệu – ghi chú (derived)", 2)
    notes = _source_notes(front_matter)
    out = {}
    for _, abbreviation, title, author, kind, note in re.findall(
            r"^\| *(\d+) *\| *([^|]+?) *\| *([^|]+?) *\| *([^|]+?) *\| *([^|]+?) *\| *\[[^\]]*\]\(#([^)]+)\) *\|$",
            table, re.M):
        if note not in notes:
            raise ValueError(f"the derived table points {abbreviation} at Source Note #{note}, which Phàm lệ I.B "
                             f"lacks")
        out[abbreviation] = {"abbreviation": abbreviation, "title": title, "author": None if author == "—" else author,
                             "kind": kind, "year": year_of(abbreviation, dated), "note_id": note,
                             "note": notes[note]}
    if list(out) != list(abbreviations):
        raise ValueError(f"the derived table's {len(out)} Sources are not the 63 of Bảng chữ tắt I, in order")
    return out


def intro(front_matter):
    """The Front Matter for the website's introduction: its headings and text, without HTML comments (and the ⚠
    markers they hold), the quick links and anchors that served the derived table, or the derived table."""
    text = front_matter[:front_matter.index("\n## Bảng đối chiếu kí hiệu – ghi chú (derived)\n")]
    text = _COMMENT.sub("", text).replace("⚠", "")
    text = re.sub(r"^Quick links[^\n]*\n\n(?:- \[[^\n]*\n)+", "", text, flags=re.M)
    text = re.sub(r'^<a id="[^"]+"></a>\n', "", text, flags=re.M)
    text = re.sub(r"\n---\s*$", "\n", text.rstrip() + "\n")
    text = "\n".join(line.rstrip() for line in text.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", text).strip() + "\n"


# -- the review log

def review_fixes(store, page_sha1):
    """
    The Fixes of the store's review.jsonl, by the name of the model's entry they replace, as (applied, stale): a
    Fix applies while every PDF page it was made against still has the answer it saw. Lines of the log, a later one
    on the same name replacing an earlier:

      {"type": "check", "name": "C 484", ...}                            a checked mark, not used here
      {"type": "fix", "name": "C 484", "entry": {...a full Proverb Entry...},
       "answer_sha1": {"420": "<sha1>", "421": "<sha1>"}, ...}          a Fix, with the answer hash of each PDF page
                                                                         the entry was on
      {"type": "fix", "name": "C 484", "entry": null, ...}               the Fix dropped

    `page_sha1` is {PDF page: its current answer hash}.
    """
    path = os.path.join(store, "review.jsonl")
    latest = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    record = json.loads(line)
                    if record.get("type") == "fix":
                        latest[record["name"]] = record
    applied, stale = {}, {}
    for name, record in latest.items():
        if record.get("entry") is None:
            continue
        made_against = record.get("answer_sha1") or {}
        current = made_against and all(page_sha1.get(int(p)) == h for p, h in made_against.items())
        (applied if current else stale)[name] = record["entry"]
    return applied, stale


def with_fixes(store):
    """The store's verbatim Proverb Entries with its non-stale Fixes in place of the model's, and the counts."""
    data = read_json(os.path.join(store, "entries.json"))
    applied, stale = review_fixes(store, {p["pdf"]: p["answer_sha1"] for p in data["pages"]})
    entries = []
    for entry in data["entries"]:
        fix = applied.get(entry["name"])
        entries.append({**fix, "fixed": True} if fix else {**entry, "fixed": False})
    unmatched = sorted(set(applied) - {e["name"] for e in data["entries"]})
    return entries, {"applied": len(applied) - len(unmatched), "stale": sorted(stale), "unmatched": unmatched}


# -- text for the reader

def italic_spans(text):
    """`text` with its italic words between asterisks -> spans, those words {"em": True}."""
    spans, i = [], 0
    for m in _ITALIC.finditer(text):
        if m.start() > i:
            spans.append({"text": text[i:m.start()]})
        spans.append({"text": m.group(1), "em": True})
        i = m.end()
    if i < len(text):
        spans.append({"text": text[i:]})
    return spans


def plain(text):
    """`text` without its asterisks."""
    return _ITALIC.sub(r"\1", text)


class Reader:
    """Turns verbatim text into what the reader sees: Source Abbreviations marked for their hover, General
    Abbreviations expanded, both on whole-word, case-sensitive matches only, the longest form first ("Nbs" before "Nb",
    "TNLG II" before a bare "TNLG"). "VD" is a Source, Vũ Dung, never "ví dụ"."""

    def __init__(self, abbreviations, general):
        self.sources = set(abbreviations)
        self.general = general
        forms = sorted(self.sources | set(self.general), key=len, reverse=True)
        self._word = re.compile(r"(?<!\w)(" + "|".join(re.escape(f) for f in forms) + r")(?!\w)")
        self.expansions = []     # every Expansion made, for the Expansion list

    def note(self, text, entry):
        """A note -> spans, with its Source mentions and Expansions; each Expansion is recorded against `entry`."""
        text = clean_citation_text(text)
        spans, i = [], 0
        for m in self._word.finditer(text):
            form = m.group()
            if m.start() > i:
                spans.append({"text": text[i:m.start()]})
            if form in self.sources:
                spans.append({"text": form, "source": form})
            else:
                spans.append({"text": self.general[form], "general": form})
                self.expansions.append({
                    "entry": entry["name"], "anchor": anchor(entry["name"]), "general": form,
                    "expansion": self.general[form],
                    "context": text[max(0, m.start() - CONTEXT_CHARS):m.end() + CONTEXT_CHARS]})
            i = m.end()
        if i < len(text):
            spans.append({"text": text[i:]})
        return spans

    def correction(self, correction):
        """A Correction's structured fields, its right wording as spans, and its plain-language sentence as spans:
        each Source marked, the corrected (italic) words of the right wording strong."""
        wrong, right = correction.get("wrong", ""), correction.get("right", "")
        sources = correction.get("sources") or []
        before, after = CORRECTION_SENTENCE.split("{sources}")
        middle, end = after.split("{right}")
        sentence = [{"text": before}]
        for k, a in enumerate(sources):
            if k:
                sentence.append({"text": ", "})
            sentence.append({"text": a, "source": a} if a in self.sources else {"text": a})
        sentence.append({"text": middle.format(wrong=plain(wrong))})
        sentence += [{"text": s["text"], "strong": True} if s.get("em") else s for s in italic_spans(right)]
        sentence.append({"text": end})
        return {"wrong": wrong, "sources": sources, "right": italic_spans(right), "sentence": sentence}


def anchor(name):
    """A Proverb Entry's anchor: its name with a hyphen, "C 484" -> "C-484"."""
    return "-".join(name.split())


def first_syllable(proverb):
    """The first word of a proverb, lower case, without punctuation: its tiếng đầu."""
    words = re.findall(r"\w+", unicodedata.normalize("NFC", plain(proverb)))
    return words[0].lower() if words else ""


def preview(proverb):
    """The first PREVIEW_WORDS words of a proverb, with "…" if it goes on."""
    words = plain(proverb).split()
    return " ".join(words[:PREVIEW_WORDS]) + ("…" if len(words) > PREVIEW_WORDS else "")


def citations(entry_citations, known):
    """Citations keyed to their Sources: the abbreviation is the key in sources.json, or is marked unknown."""
    return [{"abbreviation": c["abbreviation"], "pages": c.get("pages", "")}
            if c["abbreviation"] in known else {**c, "unknown": True} for c in entry_citations]


def record(entry, reader, by_name, dated, unresolved):
    """One Proverb Entry for the website: its text for the reader and its filter fields."""
    known = reader.sources
    variants = [{"label": VARIANT_LABEL, "text": italic_spans(_VARIANT_PREFIX.sub("", v.get("text", "")).strip()),
                 "citations": citations(v.get("citations") or [], known)} for v in entry.get("variants") or []]
    see_also = []
    for name in entry.get("see_also") or []:
        target = by_name.get(name)
        if target is None:
            see_also.append({"name": name})
            unresolved.append({"entry": entry["name"], "anchor": anchor(entry["name"]), "name": name})
        else:
            see_also.append({"name": name, "anchor": anchor(name), "preview": preview(target["proverb"])})
    cited = [c["abbreviation"] for c in (entry.get("citations") or []) + [c for v in entry.get("variants") or []
                                                                           for c in v.get("citations") or []]]
    years = [y for y in (year_of(a, dated) for a in cited) if y is not None]
    return {
        "name": entry["name"], "anchor": anchor(entry["name"]), "letter": entry["letter"], "number": entry["number"],
        "proverb": plain(entry["proverb"]),
        "citations": citations(entry.get("citations") or [], known),
        "variants": variants,
        "notes": [reader.note(n, entry) for n in entry.get("notes") or []],
        "corrections": [reader.correction(c) for c in entry.get("corrections") or []],
        "see_also": see_also,
        # the filter fields
        "first_syllable": first_syllable(entry["proverb"]),
        "sources": list(dict.fromkeys(a for a in cited if a in known)),
        "has_notes": bool(entry.get("notes")), "has_variants": bool(variants),
        "has_correction": bool(entry.get("corrections")),
        "earliest_year": min(years) if years else None,
        "book_pages": entry.get("book_pages", []), "pdf_pages": entry.get("pdf_pages", []),
        "fixed": entry["fixed"],
    }


def parse_args():
    parser = argparse.ArgumentParser(description="Export website data from every transcribed Kho tàng tục ngữ PDF "
                                                 "Part, into each Part's store/<part>/export/")
    return parser.parse_args()


def main():
    parse_args()
    with open(FRONT_MATTER, encoding="utf-8") as f:
        front_matter = f.read()
    abbreviations = load_abbreviations(FRONT_MATTER)
    dated = dated_sources(front_matter)
    undated = [a for a in dated if a not in abbreviations and not any(_VOLUME.sub("", k) == a for k in abbreviations)]
    if undated:
        raise ValueError(f"Phàm lệ II.2 dates {undated}, which name no Source of Bảng chữ tắt I")
    source_table = sources(front_matter, abbreviations, dated)
    general = general_abbreviations(front_matter)
    intro_text = intro(front_matter)

    stores = {key: os.path.join(STORE_DIR, key) for key in PARTS
              if os.path.exists(os.path.join(STORE_DIR, key, "entries.json"))}
    if not stores:
        sys.exit(f"[Kho tàng tục ngữ] No store in {STORE_DIR} has an entries.json: run src.khotangtucngu.cli first")
    parts = {}
    for key, store in stores.items():
        entries, fixes = with_fixes(store)
        parts[key] = entries
        print(f"[Kho tàng tục ngữ] {key}: {len(entries)} Proverb Entries, {fixes['applied']} Fix(es) applied, "
              f"{len(fixes['stale'])} stale {fixes['stale'] or ''}")
        if fixes["unmatched"]:
            print(f"[Kho tàng tục ngữ] {key}: Fixes for entries no longer in the store, not applied: "
                  f"{fixes['unmatched']}")
    # Every Part exported now, so a See-also resolves to an entry of any of them
    by_name = {e["name"]: e for entries in parts.values() for e in entries}

    for key, entries in parts.items():
        out = os.path.join(stores[key], "export")
        shutil.rmtree(out, ignore_errors=True)
        os.makedirs(os.path.join(out, "letters"))
        reader = Reader(abbreviations, general)
        unresolved, letters = [], {}
        for entry in entries:
            letters.setdefault(entry["letter"], []).append(record(entry, reader, by_name, dated, unresolved))
        for letter, records in letters.items():
            write_json(os.path.join(out, "letters", f"{letter}.json"), records)
        write_json(os.path.join(out, "sources.json"), source_table)
        with open(os.path.join(out, "intro.md"), "w", encoding="utf-8") as f:
            f.write(intro_text)
        write_json(os.path.join(out, "expansions.json"), reader.expansions)
        write_json(os.path.join(out, "unresolved_see_also.json"), unresolved)
        unknown = sorted({c["abbreviation"] for records in letters.values() for r in records
                          for c in r["citations"] + [c for v in r["variants"] for c in v["citations"]]
                          if c.get("unknown")})
        print(f"[Kho tàng tục ngữ] {key}: letters {' '.join(letters)}, {len(reader.expansions)} Expansion(s), "
              f"{len(unresolved)} Unresolved See-also(s), unknown Source Abbreviations {unknown or 'none'}")
        print(f"[Kho tàng tục ngữ] {key}: export in {out}")


if __name__ == "__main__":
    main()
