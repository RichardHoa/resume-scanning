"""
Compares two AI Proofreading Pass runs (one with the OCR hint, one with --no-ocr-hint) against the reviewer's own
Corrections (human_corrections.jsonl in the book folder), on the paragraphs the reviewer corrected:

  corrections reproduced  of the words the reviewer changed (and the paragraphs they deleted or joined), how many the run
                    has as the reviewer has them
  new errors        places where the run's text differs from the reviewer's where the reviewer changed nothing

Only Corrections on pages both runs read count. Words are compared with their diacritics, case and punctuation;
markup (⚠, note calls, dialogue dashes, comments) is left out.

Usage:
  python3 scripts/compare_ocr_hint.py <run-dir-with-hint> <run-dir-without> [--book-dir vsc-project] [--details]
"""
import argparse
import json
import os
import re
import sys
from difflib import SequenceMatcher

_markup = re.compile(r"<!--.*?-->|\[\^[^\]\s]+\]:?|⚠ ai-missed\?|⚠ dropcap\?|⚠|^\\(?=-)", re.S | re.M)
_token = re.compile(r"\w+|[^\w\s]")


def words(text):
    return _token.findall(_markup.sub(" ", text))


def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def human_paragraphs(corrections):
    """The reviewer's Corrections with each chain of edits to one paragraph made one: [{pages, before, after, action}]."""
    out = []
    for c in corrections:
        prev = next((p for p in reversed(out) if p["after"] == c["before"]), None)
        if prev:
            prev["after"] = c["after"]
            prev["pages"] = sorted(set(prev["pages"]) | set(c["pdf_pages"]))
            prev["action"] = "merge" if "merge" in (prev["action"], c["action"]) else prev["action"]
        else:
            out.append(dict(action=c["action"], pages=list(c["pdf_pages"]), before=c["before"], after=c["after"]))
    return out


class Run:
    def __init__(self, run_dir):
        with open(os.path.join(run_dir, "book.ai.md"), encoding="utf-8") as f:
            self.blocks = f.read().rstrip("\n").split("\n\n")
        self.boxes = {e["i"]: e["boxes"] for e in read_jsonl(os.path.join(run_dir, "boxes.jsonl"))}
        self.read = {c["page"] for c in read_jsonl(os.path.join(run_dir, "coverage.jsonl"))}

    def on(self, pages):
        """The run's blocks on any of `pages`, in order."""
        return [b for i, b in enumerate(self.blocks) if {x["page"] for x in self.boxes.get(i, [])} & set(pages)]


def window(target, text):
    """The stretch of `text` (words) that lines up with `target` (words)."""
    blocks = [m for m in SequenceMatcher(None, target, text, autojunk=False).get_matching_blocks() if m.size >= 2]
    if not blocks:
        return []
    return text[blocks[0].b:blocks[-1].b + blocks[-1].size]


def score(par, run):
    """(corrections, reproduced, new_errors) for one corrected paragraph: corrections are word changes."""
    blocks = run.on(par["pages"])
    raw, human = words(" ".join(par["before"])), words(" ".join(par["after"]))
    if not par["after"]:    # a deleted paragraph is reproduced when the run has no stretch like it
        best = max((SequenceMatcher(None, raw, words(b), autojunk=False).find_longest_match(0, len(raw), 0, len(words(b))).size
                    for b in blocks), default=0)
        return 1, int(best < max(2, len(raw) // 2)), 0
    run_words = window(human, [w for b in blocks for w in words(b)])

    fixes = [(j1, j2) for op, _, _, j1, j2 in SequenceMatcher(None, raw, human, autojunk=False).get_opcodes()
             if op != "equal"]
    same = [False] * len(human)      # human word -> the run has it, in line
    run_at = [None] * len(human)
    diffs = []
    for op, i1, i2, j1, j2 in SequenceMatcher(None, human, run_words, autojunk=False).get_opcodes():
        if op == "equal":
            for k in range(i2 - i1):
                same[i1 + k], run_at[i1 + k] = True, j1 + k
        else:
            diffs.append((i1, i2))

    def reproduced(j1, j2):
        if j1 < j2:
            return all(same[j1:j2])
        # a deletion: the words either side of it are next to each other in the run
        left, right = run_at[j1 - 1] if j1 else -1, run_at[j1] if j1 < len(human) else len(run_words)
        return left is not None and right is not None and right == left + 1

    hit = sum(reproduced(j1, j2) for j1, j2 in fixes)
    new = sum(1 for i1, i2 in diffs if not any(i1 <= f2 and f1 <= i2 for f1, f2 in fixes))
    joins = 1 if par["action"] == "merge" else 0
    joined = joins and any(len(window(human, words(b))) >= 0.9 * len(human) for b in blocks)
    return len(fixes) + joins, hit + int(bool(joined)), new


def main():
    parser = argparse.ArgumentParser(description="Compare a run with the OCR hint and one without, against the "
                                                 "reviewer's Corrections")
    parser.add_argument("with_hint")
    parser.add_argument("without_hint")
    parser.add_argument("--book-dir", default="vsc-project")
    parser.add_argument("--details", action="store_true", help="Print the numbers for each corrected paragraph")
    args = parser.parse_args()

    path = os.path.join(args.book_dir, "human_corrections.jsonl")
    if not os.path.exists(path):
        sys.exit(f"No {path}: run prepare-ai in the vsc repo and copy the folder")
    runs = {"with OCR hint": Run(args.with_hint), "without": Run(args.without_hint)}
    both = set.intersection(*(r.read for r in runs.values()))
    pars = [p for p in human_paragraphs(read_jsonl(path)) if set(p["pages"]) <= both]
    if not pars:
        sys.exit(f"None of the reviewer's Corrections is on a page both runs read ({len(both)} pages in common)")

    print(f"{len(pars)} corrected paragraphs on pages both runs read")
    for name, run in runs.items():
        totals = [0, 0, 0]
        for p in pars:
            fixes, hit, new = score(p, run)
            totals = [a + b for a, b in zip(totals, (fixes, hit, new))]
            if args.details:
                print(f"  {name:14} pdf {p['pages']}: {hit}/{fixes} corrections, {new} new errors  "
                      f"| {' '.join(p['after'])[:70] or '(deleted)'}")
        print(f"{name:14} corrections reproduced {totals[1]}/{totals[0]}, new errors {totals[2]}")


if __name__ == "__main__":
    main()
