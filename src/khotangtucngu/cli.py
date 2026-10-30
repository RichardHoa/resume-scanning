"""
CLI Entrypoint for transcribing the Proverb Entries of one Kho tàng tục ngữ người Việt PDF Part.

    python3 -m src.khotangtucngu.cli --part-1 [--pages 36-45,420-421] [--dry-run]

The Part is a key of settings.PARTS, which gives its PDF in vsc-project/khoTangTucNguoiNguoiViet/, its proverb pages
and its book page offset. With no --pages, every proverb page of the Part (36-865 for Part 1, past the Front Matter).
Writes to the Part's store, vsc-project/khoTangTucNguoiNguoiViet/store/<part>/:

  requests/pNNN.json      one answer per PDF page: its printed book page number and its Blocks in reading order
  entries.json            the verbatim Proverb Entries built from every saved page answer, and each page's book page,
                          answer hash and entries
  warnings.json           every Warning, with its kind, reason and PDF page: number gaps and duplicates, letter
                          headings out of order, unknown Source Abbreviations, Citations with no pages or that cannot
                          be split, page numbers out of step, failed or missing pages, and Leading Blocks with no owner
  pages/pNNN.png          each page, for the review server
  serve.py, web/          the review server and its page, copied from this package: `python3 serve.py` in the store
                          (on any machine, nothing to install)
  review.jsonl            the review log of checks and Fixes, which serve.py appends to. No run writes or deletes it
  token_usage.jsonl       one line per request sent to this store, summarized at the end

Saved answers are stamped with the PDF's hash, the image settings and a hash of the prompts, so a run only redoes pages
whose answer is missing, failed or stamped differently, and runs over different pages add up in the store. The outputs
are always rebuilt from every saved answer, not only this run's. --dry-run sends nothing: it counts each request's
prompt tokens with the model's own processor (images included) to check they fit the context window.
"""
import os
import sys

# Ensure repository root is in sys.path for 'src' package imports
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import argparse
import shutil
import unicodedata

import fitz

from src.core.config import DEFAULT_LLM_MODEL, DEFAULT_VLLM_URL
from src.khotangtucngu.assembly import PAGE_MISSING, assemble, warning
from src.khotangtucngu.citations import Abbreviations, load_abbreviations
from src.khotangtucngu.pages import page_key, request_image, review_image
from src.khotangtucngu.prompts import SYSTEM_PROMPT, page_schema, prompt_sha1, user_text
from src.khotangtucngu.settings import (
    BOOK_DIR, FRONT_MATTER, PAGE_DPI, PAGE_IMAGE, PAGE_MAX_TOKENS, PARTS, REQUEST_TIMEOUT, RETRY_TEMPERATURE, STORE_DIR
)
from src.providers import vlm_requests
from src.providers.vlm_requests import (
    Model, Phase, Request, current_answer, data_url, file_sha1, image_messages, page_set, print_token_stats, sha1,
    unique_ids, write_json
)

HERE = os.path.dirname(os.path.abspath(__file__))
PHASE = Phase("page", step="khotangtucngu_page", max_tokens=PAGE_MAX_TOKENS, thinking=False,
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


def page_stamp(page):
    """What a page's answer depends on beyond the phase's stamp."""
    return {"user_sha1": sha1(user_text(page))}


def page_requests(doc, pages):
    schema = page_schema()
    for page in pages:
        yield Request(page_key(page), (
            lambda page=page: image_messages(
                SYSTEM_PROMPT, [(f"Scan of PDF page {page}:", data_url(request_image(doc, page), "image/png"))],
                user_text(page))
        ), schema, page_stamp(page))


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
    answers_dir = os.path.join(store, "requests")
    usage_file = os.path.join(store, "token_usage.jsonl")
    os.makedirs(store, exist_ok=True)
    print(f"[Kho tàng tục ngữ] {args.part} ({part.pdf}): {n_pages} PDF pages, running {len(only)} "
          f"({'--pages ' + args.pages if args.pages else f'proverb pages {first}-{last}'}); store {store}")
    abbreviations = Abbreviations(load_abbreviations(FRONT_MATTER))

    stamp = {"pdf_sha1": file_sha1(pdf), "page_dpi": PAGE_DPI, "page_image": PAGE_IMAGE, "prompt_sha1": prompt_sha1()}
    if args.dry_run:
        with open(os.path.join(store, "dry_run_tokens.jsonl"), "w", encoding="utf-8") as out:
            vlm_requests.count_tokens(list(page_requests(doc, only)), PHASE, args.model_name, out,
                                      label="Page requests")
        print(f"[Dry Run] Per-request counts in {store}/dry_run_tokens.jsonl")
        return

    vlm_requests.run_phase(page_requests(doc, only), answers_dir, stamp, label="[Kho tàng tục ngữ] Page requests",
                           phase=PHASE, model=Model(args.model_name, args.vllm_url), usage_file=usage_file)

    # -- outputs, rebuilt from every saved answer
    answers, missing = {}, []
    for page in range(1, n_pages + 1):
        answer, why = current_answer(answers_dir, page_key(page), {**stamp, **page_stamp(page)})
        if answer is not None:
            answers[page] = answer
        # A page outside this run counts only if its request ran and failed, or was made from other input
        elif page in only or why != "never ran":
            missing.append(warning(PAGE_MISSING, page_key(page), f"PDF page {page} has no answer: {why}", page))
    entries, warnings, pages = assemble(answers, abbreviations, part.book_page_offset)
    warnings = unique_ids(sorted(missing + warnings, key=lambda w: w["page"]))

    os.makedirs(os.path.join(store, "pages"), exist_ok=True)
    for page in sorted(set(only) | set(answers)):
        image = os.path.join(store, "pages", f"{page_key(page)}.png")
        # This run's pages are drawn again; others only if missing
        if page in only or not os.path.exists(image):
            with open(image, "wb") as f:
                f.write(review_image(doc, page))
    for p in pages:
        p["image"] = f"pages/{page_key(p['pdf'])}.png"
    write_json(os.path.join(store, "entries.json"), {"part": args.part, "pages": pages, "entries": entries})
    write_json(os.path.join(store, "warnings.json"), warnings)
    # The review server's single master copy is this package's; review.jsonl beside it is never touched
    shutil.copyfile(os.path.join(HERE, "serve.py"), os.path.join(store, "serve.py"))
    shutil.copytree(os.path.join(HERE, "web"), os.path.join(store, "web"), dirs_exist_ok=True)

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
