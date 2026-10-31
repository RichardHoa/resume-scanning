"""
CLI Entrypoint for transcribing the Proverb Entries of one Kho tàng tục ngữ người Việt PDF Part.

    python3 -m src.khotangtucngu.cli --part-1 [--pages 36-45,420-421] [--dry-run]

The Part is a key of settings.PARTS, which gives its PDF in vsc-project/khoTangTucNguoiNguoiViet/, its proverb pages
and its book page offset. With no --pages, every proverb page of the Part (36-865 for Part 1, past the Front Matter).

Each page is read in two steps (docs/adr/0001-entry-spans-from-numbered-lines.md beside the GLOSSARY). Code finds its
printed lines on the scan, and a layout request sees the page with each line's Line Number written beside it and
answers the printed book page number, the first line under the Running Head and the Line Number each Proverb Entry and
letter heading starts on. Code cuts the page at those lines into Entry Spans, and each is copied as Blocks in its own
request. A page's answer is its Entry Spans' Blocks in order, with the layout's printed page number; a page any of whose
requests failed has none. Writes to the Part's store, vsc-project/khoTangTucNguoiNguoiViet/store/<part>/:

  lines/pNNN.json         each page's printed lines found on the scan, and ink outside them
  layout/pNNN.json        one layout answer per PDF page
  layout/pNNN.png         the page with its Line Numbers as the layout request saw it, smaller, for the review server
  spans/pNNN-LMM.json     one answer per Entry Span, named by its page and the Line Number it starts on
  answers.json            every current page answer, by PDF page, for the review server to rebuild with Fixes
  entries.json            the verbatim Proverb Entries built from every page answer, each page's book page, answer
                          hash, entries and Entry Spans (their crops as shares of the page, for the review server), and
                          the Part's book page offset
  warnings.json           every Warning, with its kind, reason and PDF page: number gaps and duplicates, letter
                          headings out of order, unknown Source Abbreviations, Citations with no pages or that cannot
                          be split, page numbers out of step, failed or missing pages, Leading Blocks with no owner,
                          and ink outside every printed line found
  sources.json            the 63 Sources by Source Abbreviation (as export.py writes them), for the review server
  pages/pNNN.png          each page, for the review server
  serve.py, web/,         the review server, its page, and the code that rebuilds the Proverb Entries with Fixes
  khotangtucngu/          (assembly.py, citations.py, review.py), copied from this package: `python3 serve.py` in the
                          store (on any machine, nothing to install)
  review.jsonl            the review log of Fixes, which serve.py appends to (see review.py). No run writes or
                          deletes it
  token_usage.jsonl       one line per request sent to this store, summarized at the end by step (layout, span)

Saved answers are stamped with the PDF's hash, the image settings and a hash of the prompts (a layout answer also with
the page's lines, an Entry Span answer with its lines and crop), so a run only redoes requests whose answer is missing,
failed or stamped differently, and runs over different pages add up in the store. The outputs are always rebuilt from
every saved answer, not only this run's. --dry-run sends nothing: it counts each layout request's prompt tokens with
the model's own processor (images included) to check they fit the context window; Entry Span requests need layout
answers, so they are not counted.
"""
import os
import sys

# Ensure repository root is in sys.path for 'src' package imports
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import argparse
import json
import shutil
import unicodedata

import fitz

from src.core.config import DEFAULT_LLM_MODEL, DEFAULT_VLLM_URL
from src.khotangtucngu.assembly import INK_OUTSIDE, LETTER, PAGE_MISSING, assemble, warning
from src.khotangtucngu.citations import Abbreviations, load_abbreviations
from src.khotangtucngu.export import dated_sources, sources
from src.khotangtucngu.pages import (
    entry_spans, find_lines, layout_image, layout_problem, page_key, review_image, review_layout_image, span_image,
    span_key
)
from src.khotangtucngu.prompts import (
    LAYOUT_SYSTEM_PROMPT, SPAN_SYSTEM_PROMPT, layout_prompt_sha1, layout_schema, layout_user_text, span_prompt_sha1,
    span_schema, span_user_text
)
from src.khotangtucngu.settings import (
    BOOK_DIR, FRONT_MATTER, LABEL_STRIP_PX, LAYOUT_IMAGE, LAYOUT_MAX_TOKENS, PAGE_DPI, PAGE_IMAGE, PARTS,
    REQUEST_TIMEOUT, RETRY_TEMPERATURE, SPAN_MAX_TOKENS, STORE_DIR
)
from src.providers import vlm_requests
from src.providers.vlm_requests import (
    Model, Phase, Request, current_answer, data_url, file_sha1, image_messages, page_set, print_token_stats,
    read_json, sha1, write_json
)

HERE = os.path.dirname(os.path.abspath(__file__))
# The modules serve.py rebuilds the Proverb Entries with, copied into <store>/khotangtucngu/
REVIEW_CODE = ("assembly.py", "citations.py", "review.py")
LAYOUT = Phase("layout", step="khotangtucngu_layout", max_tokens=LAYOUT_MAX_TOKENS, thinking=False,
               retry_temperature=RETRY_TEMPERATURE, timeout=REQUEST_TIMEOUT)
SPAN = Phase("span", step="khotangtucngu_span", max_tokens=SPAN_MAX_TOKENS, thinking=False,
             retry_temperature=RETRY_TEMPERATURE, timeout=REQUEST_TIMEOUT)


def parse_args():
    parser = argparse.ArgumentParser(description="Transcribe the Proverb Entries of one Kho tàng tục ngữ PDF Part")
    which = parser.add_mutually_exclusive_group(required=True)
    for key, part in PARTS.items():
        which.add_argument(f"--{key}", dest="part", action="store_const", const=key,
                           help=f"{part.pdf}, proverb pages {part.proverb_pages[0]}-{part.proverb_pages[1]}")
    parser.add_argument("--pages", help="Only these PDF pages, e.g. 36-45,420-421 (default: the Part's proverb pages)")
    parser.add_argument("--model-name", default=DEFAULT_LLM_MODEL)
    parser.add_argument("--vllm-url", default=DEFAULT_VLLM_URL)
    parser.add_argument("--dry-run", action="store_true",
                        help="Send nothing; count every request's prompt tokens and check they fit the context window")
    return parser.parse_args()


def part_pdf(name):
    """The path of a Part's PDF in BOOK_DIR, whichever way the file system spells its accents (composed on Linux,
    as copied; decomposed if copied from macOS), or None."""
    for form in ("NFC", "NFD"):
        path = os.path.join(BOOK_DIR, unicodedata.normalize(form, name))
        if os.path.exists(path):
            return path
    return None


def layout_stamp(page, found):
    """What a page's layout answer depends on beyond the phase's stamp: its user text and the lines it numbers."""
    return {"user_sha1": sha1(layout_user_text(page)), "lines_sha1": sha1(json.dumps(found["lines"]))}


def span_stamp(page, span):
    """What an Entry Span's answer depends on beyond the phase's stamp: its user text, its lines and its crop."""
    return {"user_sha1": sha1(span_user_text(page, span["leading"])), "lines": [span["first"], span["last"]],
            "box": span["box"]}


def layout_requests(doc, pages, found):
    schema = layout_schema()
    for page in pages:
        lines = found[page]["lines"]
        if not lines:
            continue
        yield Request(page_key(page), (
            lambda page=page, lines=lines: image_messages(
                LAYOUT_SYSTEM_PROMPT,
                [(f"Scan of PDF page {page}, with its Line Numbers:",
                  data_url(layout_image(doc, page, lines), "image/png"))],
                layout_user_text(page))
        ), schema, layout_stamp(page, found[page]), check=lambda answer, n=len(lines): layout_problem(answer, n))


def span_requests(doc, page_spans):
    schema = span_schema()
    for page, spans in page_spans.items():
        for span in spans:
            yield Request(span_key(page, span["first"]), (
                lambda page=page, span=span: image_messages(
                    SPAN_SYSTEM_PROMPT,
                    [(f"Entry Span of PDF page {page}:", data_url(span_image(doc, page, span["box"]), "image/png"))],
                    span_user_text(page, span["leading"]))
            ), schema, span_stamp(page, span))


def page_answer(page, found, layout_dir, layout_base, spans_dir, span_base):
    """
    (answer, Entry Spans, None) for a page whose layout answer and every Entry Span answer are current: its answer
    is the Entry Spans' Blocks in order with the layout's printed page number, and each Entry Span gets "blocks",
    [first, last + 1], the indexes of its Blocks in the answer. Else (None, None, why it has none).
    """
    if found is None:
        return None, None, "never ran"
    if not found["lines"]:
        return None, None, "no printed line was found on it"
    layout, why = current_answer(layout_dir, page_key(page), {**layout_base, **layout_stamp(page, found)})
    if layout is None:
        return None, None, why if why == "never ran" else f"layout request {why}"
    spans, blocks = entry_spans(found, layout), []
    for span in spans:
        key = span_key(page, span["first"])
        answer, why = current_answer(spans_dir, key, {**span_base, **span_stamp(page, span)})
        if answer is None:
            return None, None, f"Entry Span {key} (Line Numbers {span['first']}-{span['last']}) {why}"
        span["blocks"] = [len(blocks), len(blocks) + len(answer["blocks"])]
        blocks += answer["blocks"]
    return {"printed_page": layout["printed_page"], "blocks": blocks}, spans, None


def review_spans(page, spans, size, answer, entries):
    """
    A page's Entry Spans for the review server: each one's crop as shares of the page, the Line Number it starts on,
    its kind ("leading", "letter" or "entry") and its label: "Leading" for the Leading span, then the letter headings
    and the names of the Proverb Entries whose Blocks on this page start in it (from the model's `entries`).
    """
    w, h = size
    starts = [(e["blocks"][str(page)][0], e["name"]) for e in entries if str(page) in e["blocks"]]
    out = []
    for span in spans:
        first, stop = span["blocks"]
        letters = [b["text"] for b in answer["blocks"][first:stop] if b.get("kind") == LETTER]
        names = [name for at, name in starts if first <= at < stop]
        kind = "leading" if span["leading"] else "entry" if names or not letters else "letter"
        label = " · ".join((["Leading"] if span["leading"] else []) + letters + names)
        left, top, right, bottom = span["box"]
        out.append({"box": [round(left / w, 4), round(top / h, 4), round(right / w, 4), round(bottom / h, 4)],
                    "start": span["first"], "kind": kind, "label": label or "(no Blocks)"})
    return out


def main():
    args = parse_args()
    part = PARTS[args.part]
    pdf = part_pdf(part.pdf)
    if pdf is None:
        sys.exit(f"[Kho tàng tục ngữ] No PDF '{part.pdf}' in {BOOK_DIR} for --{args.part}")
    doc = fitz.open(pdf)
    n_pages = len(doc)
    first, last = part.proverb_pages
    only = page_set(args.pages, n_pages) if args.pages else list(range(first, min(last, n_pages) + 1))

    store = os.path.join(STORE_DIR, args.part)
    lines_dir, layout_dir, spans_dir = (os.path.join(store, d) for d in ("lines", "layout", "spans"))
    usage_file = os.path.join(store, "token_usage.jsonl")
    os.makedirs(lines_dir, exist_ok=True)
    print(f"[Kho tàng tục ngữ] {args.part} ({part.pdf}): {n_pages} PDF pages, running {len(only)} "
          f"({'--pages ' + args.pages if args.pages else f'proverb pages {first}-{last}'}); store {store}")
    abbreviation_list = load_abbreviations(FRONT_MATTER)
    abbreviations = Abbreviations(abbreviation_list)
    # Read before any request is sent, so a Front Matter that doesn't parse stops the run before it costs anything
    with open(FRONT_MATTER, encoding="utf-8") as f:
        front_matter = f.read()
    source_table = sources(front_matter, abbreviation_list, dated_sources(front_matter))

    pdf_sha1 = file_sha1(pdf)
    layout_base = {"pdf_sha1": pdf_sha1, "page_dpi": PAGE_DPI, "layout_image": LAYOUT_IMAGE,
                   "prompt_sha1": layout_prompt_sha1()}
    span_base = {"pdf_sha1": pdf_sha1, "page_dpi": PAGE_DPI, "page_image": PAGE_IMAGE,
                 "prompt_sha1": span_prompt_sha1()}

    # -- the printed lines: found again for this run's pages, read back for the others
    print(f"[Kho tàng tục ngữ] Finding the printed lines of {len(only)} page(s)")
    found = {}
    for page in only:
        found[page] = find_lines(doc, page)
        write_json(os.path.join(lines_dir, f"{page_key(page)}.json"), {"pdf_sha1": pdf_sha1, **found[page]})
    for page in range(1, n_pages + 1):
        path = os.path.join(lines_dir, f"{page_key(page)}.json")
        if page not in found and os.path.exists(path):
            saved = read_json(path)
            if saved.get("pdf_sha1") == pdf_sha1:
                found[page] = {k: saved[k] for k in ("size", "lines", "missed")}

    if args.dry_run:
        with open(os.path.join(store, "dry_run_tokens.jsonl"), "w", encoding="utf-8") as out:
            vlm_requests.count_tokens(list(layout_requests(doc, only, found)), LAYOUT, args.model_name, out,
                                      label="Layout requests")
        print(f"[Dry Run] Per-request counts in {store}/dry_run_tokens.jsonl")
        return

    model = Model(args.model_name, args.vllm_url)
    vlm_requests.run_phase(layout_requests(doc, only, found), layout_dir, layout_base,
                           label="[Kho tàng tục ngữ] Layout requests", phase=LAYOUT, model=model, usage_file=usage_file)
    page_spans = {}
    for page in only:
        if found[page]["lines"]:
            layout, _ = current_answer(layout_dir, page_key(page), {**layout_base, **layout_stamp(page, found[page])})
            if layout is not None:
                page_spans[page] = entry_spans(found[page], layout)
    vlm_requests.run_phase(span_requests(doc, page_spans), spans_dir, span_base,
                           label="[Kho tàng tục ngữ] Entry Span requests", phase=SPAN, model=model,
                           usage_file=usage_file)

    # -- outputs, rebuilt from every saved answer
    answers, spans, missing = {}, {}, []
    for page in range(1, n_pages + 1):
        answer, page_spans_now, why = page_answer(page, found.get(page), layout_dir, layout_base, spans_dir, span_base)
        if answer is not None:
            answers[page], spans[page] = answer, page_spans_now
        # A page outside this run counts only if its requests ran and one failed, or were made from other input
        elif page in only or why != "never ran":
            missing.append(warning(PAGE_MISSING, page_key(page), f"PDF page {page} has no answer: {why}", page))
        if page in found and found[page]["missed"]:
            patches = found[page]["missed"]
            top, bottom = min(m[1] for m in patches), max(m[3] for m in patches)
            missing.append(warning(INK_OUTSIDE, page_key(page), f"PDF page {page} has {len(patches)} patch(es) of "
                                   f"ink outside every printed line found ({top}-{bottom} px down the 300 dpi scan), "
                                   f"in no Entry Span", page))
    entries, warnings, pages = assemble(answers, abbreviations, part.book_page_offset)
    # assemble's Warning ids are unique, and a missing page's and a page's missed ink are their own
    warnings = sorted(missing + warnings, key=lambda w: w["page"])

    os.makedirs(os.path.join(store, "pages"), exist_ok=True)
    for page in sorted(set(only) | set(answers)):
        image = os.path.join(store, "pages", f"{page_key(page)}.png")
        # This run's pages are drawn again; others only if missing
        if page in only or not os.path.exists(image):
            with open(image, "wb") as f:
                f.write(review_image(doc, page))
    for page in sorted(set(only) | set(answers)):
        image = os.path.join(layout_dir, f"{page_key(page)}.png")
        if page in found and found[page]["lines"] and (page in only or not os.path.exists(image)):
            with open(image, "wb") as f:
                f.write(review_layout_image(layout_image(doc, page, found[page]["lines"])))
    for p in pages:
        page, (w, _) = p["pdf"], found[p["pdf"]]["size"]
        p["image"] = f"pages/{page_key(page)}.png"
        p["layout_image"] = f"layout/{page_key(page)}.png"
        p["layout_page_share"] = round(w / (w + LABEL_STRIP_PX), 4)
        p["spans"] = review_spans(page, spans[page], found[page]["size"], answers[page], entries)
    write_json(os.path.join(store, "answers.json"), {str(p): answers[p] for p in sorted(answers)})
    write_json(os.path.join(store, "entries.json"), {"part": args.part, "book_page_offset": part.book_page_offset,
                                                     "pages": pages, "entries": entries})
    write_json(os.path.join(store, "warnings.json"), warnings)
    write_json(os.path.join(store, "sources.json"), source_table)
    # The review server's single master copy is this package's; review.jsonl beside it is never touched
    shutil.copyfile(os.path.join(HERE, "serve.py"), os.path.join(store, "serve.py"))
    shutil.copytree(os.path.join(HERE, "web"), os.path.join(store, "web"), dirs_exist_ok=True)
    code = os.path.join(store, "khotangtucngu")
    os.makedirs(code, exist_ok=True)
    for name in REVIEW_CODE:
        shutil.copyfile(os.path.join(HERE, name), os.path.join(code, name))
    with open(os.path.join(code, "__init__.py"), "w", encoding="utf-8") as f:
        f.write('"""Copied from src/khotangtucngu by cli.py: what serve.py rebuilds the Proverb Entries with."""\n')

    kinds = {}
    for w in warnings:
        kinds[w["kind"]] = kinds.get(w["kind"], 0) + 1
    print(f"[Kho tàng tục ngữ] {len(answers)} page(s) with an answer in the store, {len(entries)} Proverb Entries")
    print(f"[Kho tàng tục ngữ] {len(warnings)} Warning(s): {kinds}")
    print(f"[Kho tàng tục ngữ] Entries in {store}/entries.json, Warnings in {store}/warnings.json")
    print(f"[Kho tàng tục ngữ] To review the Part: cd {store} && python3 serve.py")
    print_token_stats(usage_file)


if __name__ == "__main__":
    main()
