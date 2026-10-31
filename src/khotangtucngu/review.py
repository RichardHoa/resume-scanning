"""
The review log of a PDF Part's store, review.jsonl, and the Proverb Entries rebuilt with its Fixes. A Fix is the
developer's corrected Blocks of one PDF page, made where they see the model got something wrong; nobody checks every
entry. Lines of the log, which serve.py appends and nothing rewrites, a later one for the same page replacing an
earlier:

  {"type": "fix", "page": 38, "answer_sha1": "<sha1>", "printed_page": "37", "blocks": [...]}
      a Fix: the page's printed number and its Blocks, in the shape of a page answer's, made against the model's
      answer of that hash
  {"type": "fix", "page": 38, "blocks": null}
      the page's Fix dropped

Each line also has its "time". Lines of any other type, such as the "check" marks of earlier reviews, are ignored.
A Fix is stale once the model's answer of its page no longer has the hash it was made against: a rerun changed it, so
the Fix is not applied until it is saved again or dropped.

Standard library only, like assembly.py and citations.py: cli.py copies the three into the store for serve.py.
"""
import json
import os

from .assembly import BLOCK_KINDS, answer_sha1, assemble

REVIEW_LOG = "review.jsonl"


def fix_problem(record):
    """Why `record` is not a Fix line of the shape above, or None. Its Blocks are held to the page schema's shape only,
    as the model's are: a Fix of one entry carries the page's other Blocks as the model wrote them."""
    if not isinstance(record, dict) or record.get("type") != "fix":
        return "not a Fix"
    if not isinstance(record.get("page"), int) or isinstance(record["page"], bool):
        return "no PDF page"
    blocks = record.get("blocks")
    if blocks is None:
        return None
    if not isinstance(record.get("answer_sha1"), str) or not record["answer_sha1"]:
        return "no answer hash"
    if not isinstance(record.get("printed_page"), str):
        return "no printed page number"
    if not isinstance(blocks, list):
        return "the Blocks are not a list"
    for i, block in enumerate(blocks, 1):
        if not isinstance(block, dict) or block.get("kind") not in BLOCK_KINDS:
            return f"Block {i} has no kind of {BLOCK_KINDS}"
        number = block.get("number")
        if not isinstance(number, int) or isinstance(number, bool) or number < 0:
            return f"Block {i}'s number is not a whole number"
        if not isinstance(block.get("text"), str) or not isinstance(block.get("citations"), str):
            return f"Block {i}'s text and Citations are not text"
    return None


def read_fixes(store):
    """{PDF page: its latest Fix line} from the store's review log, without the pages whose Fix was dropped."""
    path = os.path.join(store, REVIEW_LOG)
    latest = {}
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            for line in f:
                try:
                    record = json.loads(line)
                except ValueError:
                    continue
                if isinstance(record, dict) and record.get("type") == "fix" and fix_problem(record) is None:
                    latest[record["page"]] = record
    return {page: record for page, record in latest.items() if record["blocks"] is not None}


def with_fixes(answers, fixes):
    """`answers` ({PDF page: the model's answer}) with each Fix that is not stale in place of its page's answer, and
    the pages whose Fix is applied and whose Fix is stale (a Fix of a page with no answer is stale too)."""
    fixed, applied, stale = dict(answers), [], []
    for page, fix in sorted(fixes.items()):
        if page in answers and answer_sha1(answers[page]) == fix["answer_sha1"]:
            fixed[page] = {**answers[page], "printed_page": fix["printed_page"], "blocks": fix["blocks"]}
            applied.append(page)
        else:
            stale.append(page)
    return fixed, applied, stale


def rebuild(answers, fixes, abbreviations, book_page_offset):
    """The Proverb Entries, Warnings and pages of assembly.assemble, built from `answers` with the Fixes that apply,
    and the pages whose Fix is applied and stale. An entry is "fixed" when a page it is printed on has an applied
    Fix."""
    fixed, applied, stale = with_fixes(answers, fixes)
    entries, warnings, pages = assemble(fixed, abbreviations, book_page_offset)
    for entry in entries:
        entry["fixed"] = any(p in applied for p in entry["pdf_pages"])
    return entries, warnings, pages, applied, stale


def read_answers(path):
    """The model's page answers a store's answers.json holds, by PDF page."""
    with open(path, encoding="utf-8") as f:
        return {int(page): answer for page, answer in json.load(f).items()}
