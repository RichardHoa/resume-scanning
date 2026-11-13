"""
Export of the Topic Index, run locally with no GPU by export.py for a key of settings.SECTIONS:

    python3 -m src.khotangtucngu.export --part-4-final-section

The index is rebuilt from the section's store, its answers.json with the Confirmed Lines of its review.jsonl laid over
and checked against its entry_names.json (topics.py), as the run left them. The export stops, writing nothing, and lists
why while any page of the section has no Index Lines, a Part had no answers.json when the index was run, or a line has
an open disagreement or single-read Warning. Otherwise the store's export/ is emptied and written afresh:

  topics.json        {"topics": [{"id": "I", "title", "subtopics": [{"id": "I.1", "number", "title", "entries": ["A-8",
                     ...], "unresolved": ["C-1858", ...]}]}]}: entries as the anchors letters/*.json uses, in printed
                     order; the names lost in the book or its scan, or naming no Proverb Entry, apart in "unresolved".
                     The Parts' letters/*.json are not touched: the website inverts this file
  topic-intro.md     the Lời dẫn of the hand-transcribed Back Matter
  compilers.md       its Vài nét về các soạn giả

Both Markdown files are without HTML comments or ⚠ markers, as intro.md is from the Front Matter.
"""
import os
import re
import shutil
import sys

from src.khotangtucngu.settings import BACK_MATTER, STORE_DIR
from src.khotangtucngu.topics import READ_KINDS, read_log, rebuild
from src.providers.vlm_requests import read_json, write_json

INTRO_HEADING = "## Lời dẫn"
COMPILERS_HEADING = '## Vài nét về các soạn giả sách "*Kho tàng tục ngữ người Việt*"'


def back_matter_section(text, heading):
    """The Markdown section `heading` (its full line) of the Back Matter, with its heading, up to the next "## "
    heading, without HTML comments or ⚠ markers."""
    start = text.index(f"\n{heading}\n") + 1
    m = re.compile(r"^## ", re.M).search(text, start + len(heading))
    section = re.sub(r"[ \t]*<!--.*?-->", "", text[start:m.start() if m else len(text)], flags=re.S).replace("⚠", "")
    section = "\n".join(line.rstrip() for line in section.split("\n"))
    return re.sub(r"\n{3,}", "\n\n", section).strip() + "\n"


def blockers(answers, entry_names, result):
    """Why the index can't be exported yet: each page of the section with no Index Lines, each Part with no
    answers.json at run time, and each line with an open disagreement or single-read Warning."""
    first, last = answers["section"]["pages"]
    pages = answers["pages"]
    out = [f"PDF page {page} has no Index Lines: "
           + (pages[str(page)]["why"] if str(page) in pages else "it was never run")
           for page in range(first, last + 1) if not (pages.get(str(page)) or {}).get("lines")]
    out += [f"{part} had no answers.json when the index was run: run the index again once it has one"
            for part in entry_names["missing_parts"]]
    out += [w["reason"] for w in result["warnings"] if w["kind"] in READ_KINDS]
    return out


def main(key):
    store = os.path.join(STORE_DIR, key)
    for name in ("answers.json", "entry_names.json"):
        if not os.path.exists(os.path.join(store, name)):
            sys.exit(f"[Kho tàng tục ngữ] {store} has no {name}: run src.khotangtucngu.cli --{key} first")
    with open(BACK_MATTER, encoding="utf-8") as f:
        back_matter = f.read()
    intro, compilers = (back_matter_section(back_matter, h) for h in (INTRO_HEADING, COMPILERS_HEADING))
    answers = read_json(os.path.join(store, "answers.json"))
    entry_names = read_json(os.path.join(store, "entry_names.json"))
    log = read_log(store)
    result = rebuild(answers, log, entry_names)
    blocking = blockers(answers, entry_names, result)
    if blocking:
        sys.exit(f"[Kho tàng tục ngữ] {key}: not exported, {len(blocking)} thing(s) to settle first (review the open "
                 f"lines in the review server):\n" + "\n".join(f"  {why}" for why in blocking))

    out = os.path.join(store, "export")
    shutil.rmtree(out, ignore_errors=True)
    os.makedirs(out)
    write_json(os.path.join(out, "topics.json"), {"topics": result["topics"]})
    for name, text in (("topic-intro.md", intro), ("compilers.md", compilers)):
        with open(os.path.join(out, name), "w", encoding="utf-8") as f:
            f.write(text)
    subtopics = [s for t in result["topics"] for s in t["subtopics"]]
    print(f"[Kho tàng tục ngữ] {key}: {len(result['topics'])} chủ đề, {len(subtopics)} tiểu chủ đề, "
          f"{sum(len(s['entries']) for s in subtopics)} entry name(s), {sum(len(s['unresolved']) for s in subtopics)} "
          f"unresolved, {sum(len(held) for held in log.values())} Confirmed Line(s), {len(result['warnings'])} "
          f"Warning(s) left in warnings.json")
    print(f"[Kho tàng tục ngữ] {key}: export in {out}")
