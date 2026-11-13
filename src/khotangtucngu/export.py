"""
Export: website-ready data from the verbatim Proverb Entries of one transcribed PDF Part, run locally with no GPU.

    python3 -m src.khotangtucngu.export --part-1

Exports the Part named, whose store must have an answers.json. A See-also still resolves to an entry of any Part whose
store has an answers.json, whose entries are rebuilt for that but not exported: an Unresolved See-also of Part 1
resolves by itself once Part 2 is transcribed and Part 1 is exported again. The Part's store/<part>/export/ is emptied
and written afresh, and nothing outside it is touched:

  letters/<letter>.json       one record per Proverb Entry of the letter, in book order (see `record`)
  sources.json                the 63 Sources by Source Abbreviation, in printed order: title, author, kind, year where
                              Phàm lệ II.2 dates it, and the text of its Source Note (Markdown)
  intro.md                    the Front Matter without HTML comments, ⚠ markers, quick links or the derived table
  expansions.json             every Expansion of a General Abbreviation made, with its entry and the text around it
  unresolved_see_also.json    every Unresolved See-also, for information
  export-warning.txt          for checking by eye: every repeated Entry Image name ("_2" on) with both entries, and
                              each letter's count of numbers from 1 to its highest, with each missing number and the
                              entries either side of it (see `export_warnings`), apart from the numbers lost in the book
                              or its scan (settings.Part.number_jumps)
  entry_images.zip            the Entry Image of every Proverb Entry, flat, "<anchor>.png" ("A-200.png"; a repeated
                              name "A-200_2.png" on), grayscale PNG at settings.ENTRY_IMAGE_DPI, stored, not deflated

An Entry Image is cut from the Part's PDF, which must be in BOOK_DIR: on each page the entry is on, the box around every
span, model span or Confirmed Span, holding a Block of it, whole, so it may show a letter heading or a neighbouring entry
too; its pages stacked top to bottom (see pages.entry_image).

The Proverb Entries are rebuilt from the store's answers.json with the Confirmed Spans of its review.jsonl laid over the
model's Blocks (see review.py); an entry is "fixed" only if a span holding it was edited, not if it was confirmed as it
stood. A Citation after "bk" is a Variant Citation, marked "variant". Notes, Variants and Corrections are lists of
spans, {"text"} plus, where it applies: "em" (printed in italics), "strong" (the corrected words of a Correction), "source" (a Source Abbreviation, the key of its Source in
sources.json) or "general" (a General Abbreviation, whose "text" is its Expansion). The proverb is plain text.
A record's "image" is its Entry Image's file in entry_images.zip.
"""
import os
import sys

# Ensure repository root is in sys.path for 'src' package imports
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import argparse
import re
import shutil
import unicodedata
import zipfile

from src.khotangtucngu.citations import Abbreviations, clean_citation_text, load_abbreviations
from src.khotangtucngu.pages import entry_image, open_pdf, part_pdf
from src.khotangtucngu.review import read_answers, read_log, rebuild
from src.khotangtucngu.settings import BOOK_DIR, FRONT_MATTER, PARTS, STORE_DIR
from src.providers.vlm_requests import write_json

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
# An Entry Image name repeated, "A-200_2.png": its first name's stem and the count
_REPEATED_IMAGE = re.compile(r"^(.+)_(\d+)\.png$")


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


# -- the Proverb Entries with the Confirmed Spans

def with_confirmed(store, abbreviations, book_page_offset, skipped=(), gaps=()):
    """The store's Proverb Entries rebuilt with its Confirmed Spans, the page answers they were laid over (by PDF page),
    and how many Confirmed Spans there are. `skipped`: the PDF pages the Part skips; `gaps`: its scan_gaps."""
    log = read_log(store)
    entries, _, _, laid = rebuild(read_answers(os.path.join(store, "answers.json")), log, abbreviations,
                                  book_page_offset, skipped=skipped, gaps=gaps)
    return entries, laid, sum(len(held) for held in log["confirmed"].values())


# -- the Entry Images

def entry_crops(entry, laid):
    """`entry`'s crops for its Entry Image, [(PDF page, box)] in page order: on each page it is on, the box around every
    span of `laid` holding a Block of it."""
    crops = []
    for page, (first, stop) in sorted(entry["blocks"].items(), key=lambda item: int(item[0])):
        boxes = [span["box"] for span in laid[int(page)]["spans"]
                 if span["blocks"][0] < stop and first < span["blocks"][1]]
        if not boxes:
            raise ValueError(f"{entry['name']}: its Blocks {first}-{stop - 1} of PDF page {page} lie in no span")
        crops.append((int(page), [min(b[0] for b in boxes), min(b[1] for b in boxes), max(b[2] for b in boxes),
                                  max(b[3] for b in boxes)]))
    return crops


def image_names(entries):
    """Each entry's Entry Image file, in order: its anchor in NFC with ".png", a repeated name "_2" on."""
    seen, names = {}, []
    for entry in entries:
        base = unicodedata.normalize("NFC", anchor(entry["name"]))
        seen[base] = seen.get(base, 0) + 1
        names.append(f"{base}.png" if seen[base] == 1 else f"{base}_{seen[base]}.png")
    return names


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
    """Citations keyed to their Sources: the abbreviation is the key in sources.json, or is marked unknown. A Variant
    Citation keeps its "variant"."""
    out = []
    for c in entry_citations:
        citation = {"abbreviation": c["abbreviation"], "pages": c.get("pages", "")}
        if c.get("variant"):
            citation["variant"] = True
        if c["abbreviation"] not in known:
            citation["unknown"] = True
        out.append(citation)
    return out


def record(entry, reader, by_name, dated, unresolved, image):
    """One Proverb Entry for the website: its text for the reader, its filter fields and its Entry Image's file."""
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
        "image": image,
    }


# -- the checks

def _where(r):
    pages = lambda key: ", ".join(map(str, r[key]))
    return f"{r['name']}, PDF page {pages('pdf_pages')} (book page {pages('book_pages')}): {r['proverb']}"


def export_warnings(letters, number_jumps=()):
    """The text of export-warning.txt from {letter: its records, in book order}: each repeated Entry Image name with
    the entry holding the name before it, and each letter's numbers from 1 to its highest, a missing number shown with
    the entries just before and after it, where its proverb most likely went. The numbers a jump of `number_jumps`
    (settings.Part) skips are lost in the book or its scan and listed apart, not counted missing."""
    records = [r for rs in letters.values() for r in rs]
    by_image = {r["image"]: r for r in records}
    repeated = [r for r in records if _REPEATED_IMAGE.match(r["image"])]
    lines = [f"== Repeated Entry Image names: {len(repeated)} =="]
    for r in repeated:
        first = by_image[_REPEATED_IMAGE.sub(r"\1.png", r["image"])]
        lines += [r["image"], f"    {first['image']}: {_where(first)}", f"    {r['image']}: {_where(r)}"]
    lines += ["", "== Numbers per letter =="]
    missing_count = 0
    for letter, rs in letters.items():
        numbers = {}
        for r in rs:
            numbers.setdefault(r["number"], []).append(r)
        top = max(numbers)
        unprinted = {n for jump, before, after in number_jumps if jump == letter for n in range(before + 1, after)}
        missing = [n for n in range(1, top + 1) if n not in numbers and n not in unprinted]
        missing_count += len(missing)
        lines.append(f"{letter}: {len(numbers)} of {letter} 1 to {letter} {top}, {len(missing)} missing"
                     + (f": {', '.join(map(str, missing))}" if missing else ""))
        lines += [f"  {letter} {before + 1}-{after - 1} are not in the PDF: {letter} {before} is followed by "
                  f"{letter} {after}" for jump, before, after in number_jumps if jump == letter]
        for n in missing:
            lines.append(f"  {letter} {n} is missing, between:")
            near = [max((k for k in numbers if k < n), default=None), min(k for k in numbers if k > n)]
            lines += [f"    {_where(r)}" for k in near if k is not None for r in numbers[k]]
    lines += ["", f"== {len(records)} Proverb Entries, {len(repeated)} repeated Entry Image name(s), "
                  f"{missing_count} missing number(s) =="]
    return "\n".join(lines) + "\n"


def parse_args():
    parser = argparse.ArgumentParser(description="Export website data from one transcribed Kho tàng tục ngữ PDF "
                                                 "Part, into its store/<part>/export/")
    which = parser.add_mutually_exclusive_group(required=True)
    for key, part in PARTS.items():
        which.add_argument(f"--{key}", dest="part", action="store_const", const=key, help=part.pdf)
    return parser.parse_args()


def main():
    part = parse_args().part
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
              if os.path.exists(os.path.join(STORE_DIR, key, "answers.json"))}
    if part not in stores:
        sys.exit(f"[Kho tàng tục ngữ] {os.path.join(STORE_DIR, part)} has no answers.json: "
                 f"run src.khotangtucngu.cli --{part} first")
    pdf = part_pdf(PARTS[part].pdf)
    if pdf is None:
        sys.exit(f"[Kho tàng tục ngữ] No PDF in {BOOK_DIR} for {part} ({PARTS[part].pdf!r}): "
                 f"the Entry Images are cut from it")
    parts = {}
    for key, store in stores.items():
        entries, laid, confirmed = with_confirmed(store, Abbreviations(abbreviations), PARTS[key].book_page_offset,
                                                    PARTS[key].skipped_pages, PARTS[key].scan_gaps)
        if key == part:
            # Every Entry Image's crops before export/ is emptied, so an entry in no span stops the run with nothing
            # half written
            try:
                crops = [entry_crops(entry, laid) for entry in entries]
            except ValueError as e:
                sys.exit(f"[Kho tàng tục ngữ] {key}: {e}")
            print(f"[Kho tàng tục ngữ] {key}: {len(entries)} Proverb Entries, {confirmed} Confirmed Span(s)")
        parts[key] = entries
    # Every transcribed Part's entries, so a See-also resolves to an entry of any of them
    by_name = {e["name"]: e for entries in parts.values() for e in entries}

    out = os.path.join(stores[part], "export")
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(os.path.join(out, "letters"))
    reader = Reader(abbreviations, general)
    unresolved, letters = [], {}
    names = image_names(parts[part])
    for entry, name in zip(parts[part], names):
        letters.setdefault(entry["letter"], []).append(record(entry, reader, by_name, dated, unresolved, name))
    for letter, records in letters.items():
        write_json(os.path.join(out, "letters", f"{letter}.json"), records)
    write_json(os.path.join(out, "sources.json"), source_table)
    with open(os.path.join(out, "intro.md"), "w", encoding="utf-8") as f:
        f.write(intro_text)
    write_json(os.path.join(out, "expansions.json"), reader.expansions)
    write_json(os.path.join(out, "unresolved_see_also.json"), unresolved)
    with open(os.path.join(out, "export-warning.txt"), "w", encoding="utf-8") as f:
        f.write(export_warnings(letters, PARTS[part].number_jumps))
    with open_pdf(pdf, PARTS[part]) as doc, \
            zipfile.ZipFile(os.path.join(out, "entry_images.zip"), "w", zipfile.ZIP_STORED) as images:
        for its_crops, name in zip(crops, names):
            images.writestr(name, entry_image(doc, its_crops))
    unknown = sorted({c["abbreviation"] for records in letters.values() for r in records
                      for c in r["citations"] + [c for v in r["variants"] for c in v["citations"]]
                      if c.get("unknown")})
    print(f"[Kho tàng tục ngữ] {part}: letters {' '.join(letters)}, {len(reader.expansions)} Expansion(s), "
          f"{len(unresolved)} Unresolved See-also(s), unknown Source Abbreviations {unknown or 'none'}, "
          f"{len(names)} Entry Image(s)")
    print(f"[Kho tàng tục ngữ] {part}: export in {out}")


if __name__ == "__main__":
    main()
