"""
CLI Entrypoint for transcribing the Proverb Entries of one Kho tàng tục ngữ người Việt PDF Part.

    python3 -m src.khotangtucngu.cli --part-1 [--pages 36-45,420-421] [--dry-run]

A key of settings.SECTIONS (--part-4-final-section, the Topic Index) is handed to topic_index.py, which reads the
section's printed lines one by one; everything below is a Part's.

The Part is a key of settings.PARTS, which gives its PDF in vsc-project/khoTangTucNguoiNguoiViet/, its proverb pages
and its book page offset. With no --pages, every proverb page of the Part (36-865 for Part 1, past the Front Matter).
A page the Part skips, misprinted in the book (PDF page 671 of Part 1), is never read, answered or warned about.

A Mac reads the pages first (vision_ocr.py): it finds each page's printed lines, and Apple Vision reads each line on its
own and with the whole page, and those two folders of the store are copied here. This job finds no lines itself: before
any request, it exits naming any page of this run whose lines or Vision read are missing, failed or made from another
PDF. --pages needs reads for those pages only. --check-reads does only this check, which the job runs before it starts
its server, so a page that can't finish costs no GPU time.

Each page is then read in two steps (docs/adr/0001-entry-spans-from-numbered-lines.md beside the GLOSSARY). A layout
request sees the page with each line's Line Number written beside it and answers the printed book page number, the first
line under the Running Head and the Line Number each Proverb Entry and letter heading starts on. Code cuts the page at
those lines into Entry Spans, and each is copied as Blocks in its own request, with the two reads of its lines
(docs/adr/0002-ocr-readings-of-each-line.md, 0005-two-reads-and-model-edits.md).
A page's answer is its Entry Spans' Blocks in order, with the layout's printed page number; a page any of whose
requests failed has none. Each request is tried up to 3 times (vlm_requests.ATTEMPTS), and the run ends by listing
every page with no answer, why, and each attempt of the request that failed, from its saved result's attempt_log.

The store's review.jsonl (review.py) is read before any request and never written. A Confirmed Span gets no request: it
owns every line whose centre falls in its band, the page is cut around it, and the lines left below it are read as a
Leading span (docs/adr/0006-confirmed-spans-override-the-layout.md). A page whose "page_complete" line still applies gets
no request at all. A run stops before any request if a Confirmed Span was made from another PDF, naming the pages.
Writes to the Part's store, vsc-project/khoTangTucNguoiNguoiViet/store/<part>/:

  layout/pNNN.json        one layout answer per PDF page
  layout/pNNN.png         the page with its Line Numbers as the layout request saw it, smaller, for the review server
  spans/pNNN-LMM.json     one answer per Entry Span, named by its page and the Line Number it starts on
  layout/spirals/, spans/spirals/
                          <key>-a<attempt>/ for each attempt that ran to max_tokens: its prompt as sent and the start
                          and end of its reply (vlm_requests.py)
  answers.json            every current page answer, by PDF page, for the review server to lay Confirmed Spans over: the
                          model's Blocks (a Confirmed Span's as its record keeps them), and its printed number, first
                          line, PDF hash, size and spans, each with its Block range, band, crop, Line Numbers, whether
                          it is Leading and its reads, so the review server needs no PDF and no line data
  readings.json           the OCR Readings of each page with an answer joined, by PDF page, which the page's Blocks are
                          checked against for Diacritic Disagreements
  agreed.json             the same readings of each page, with their Agreed Syllables flagged
                          (diacritics.flagged_reads), which the page's Blocks are checked against for Model Edits
  entries.json            the verbatim Proverb Entries built from every page answer with the Confirmed Spans laid over,
                          each page's book page, entries and Entry Spans (their crops as shares of the page, for the
                          review server), and the Part's book page offset, skipped pages and scan gaps
  warnings.json           every Warning, with its kind, reason and PDF page, the Stable Model Edits first: number gaps
                          and duplicates, letter headings out of order, unknown Source Abbreviations, Citations with no
                          pages or that cannot be split, Diacritic Disagreements, Model Edits, page numbers out of step,
                          failed or missing pages, Leading Blocks with no owner, proverb Blocks with no number (read as
                          notes), and ink outside every printed line found
  sources.json            the 63 Sources by Source Abbreviation (as export.py writes them), for the review server
  pages/pNNN.png          each page, for the review server
  serve.py, web/,         the review server, its page, and the code that rebuilds the Proverb Entries with Confirmed
  khotangtucngu/          Spans (assembly.py, citations.py, diacritics.py, review.py), copied from this package:
                          `python3 serve.py` in the store (on any machine, nothing to install)
  review.jsonl            the review log of Confirmed Spans, which serve.py appends to (see review.py). No run writes or
                          deletes it
  token_usage.jsonl       one line per request sent to this store, summarized at the end by step (layout, span)

Saved answers are stamped with the PDF's hash, the image settings, the repetition penalty and a hash of the prompts (a
layout answer also with the page's lines, an Entry Span answer with its lines, crop and the two reads of its lines), so a run only redoes
requests whose answer is missing, failed or stamped differently, and runs over different pages add up in the store.
The outputs are always rebuilt from every saved answer, not only this run's. --dry-run sends nothing: it needs the Mac's
lines and reads like any run, and counts each layout request's prompt tokens with the model's own processor (images
included) to check they fit the context window; Entry Span requests need layout answers, so they are not counted.
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

from src.core.config import DEFAULT_LLM_MODEL, DEFAULT_VLLM_URL
from src.khotangtucngu.assembly import INK_OUTSIDE, PAGE_MISSING, priority_first, warning
from src.khotangtucngu.citations import Abbreviations, load_abbreviations
from src.khotangtucngu.diacritics import flagged_reads, read_of_line
from src.khotangtucngu.export import dated_sources, sources
from src.khotangtucngu.pages import (
    entry_spans, in_band, layout_image, layout_problem, open_pdf, page_key, part_pdf, review_image, review_layout_image,
    span_image, span_key
)
from src.khotangtucngu.prompts import (
    LAYOUT_SYSTEM_PROMPT, SPAN_SYSTEM_PROMPT, layout_prompt_sha1, layout_schema, layout_user_text, span_prompt_sha1,
    span_schema, span_user_text
)
from src.khotangtucngu.review import read_log, rebuild
from src.khotangtucngu.settings import (
    BOOK_DIR, FRONT_MATTER, LABEL_STRIP_PX, LAYOUT_IMAGE, LAYOUT_MAX_TOKENS, PAGE_DPI, PAGE_IMAGE, PARTS,
    REPETITION_PENALTY, REQUEST_TIMEOUT, RETRY_TEMPERATURE, SECTIONS, SPAN_MAX_TOKENS, SPAN_STOP, STORE_DIR
)
from src.khotangtucngu import topic_index
from src.khotangtucngu.vision_ocr import saved_lines, vision_problem
from src.providers import vlm_requests
from src.providers.vlm_requests import (
    Model, Phase, Request, current_answer, data_url, file_sha1, image_messages, page_set, print_token_stats,
    read_json, read_result, sha1, write_json
)

HERE = os.path.dirname(os.path.abspath(__file__))
# The modules serve.py rebuilds the Proverb Entries with, copied into <store>/khotangtucngu/
REVIEW_CODE = ("assembly.py", "citations.py", "diacritics.py", "review.py")
LAYOUT = Phase("layout", step="khotangtucngu_layout", max_tokens=LAYOUT_MAX_TOKENS, thinking=False,
               retry_temperature=RETRY_TEMPERATURE, timeout=REQUEST_TIMEOUT, repetition_penalty=REPETITION_PENALTY)
SPAN = Phase("span", step="khotangtucngu_span", max_tokens=SPAN_MAX_TOKENS, thinking=False,
             retry_temperature=RETRY_TEMPERATURE, timeout=REQUEST_TIMEOUT, repetition_penalty=REPETITION_PENALTY,
             stop=SPAN_STOP)


def parse_args():
    parser = argparse.ArgumentParser(description="Transcribe the Proverb Entries of one Kho tàng tục ngữ PDF Part")
    which = parser.add_mutually_exclusive_group(required=True)
    for key, part in PARTS.items():
        which.add_argument(f"--{key}", dest="part", action="store_const", const=key,
                           help=f"{part.pdf}, proverb pages {part.proverb_pages[0]}-{part.proverb_pages[1]}")
    for key, section in SECTIONS.items():
        which.add_argument(f"--{key}", dest="part", action="store_const", const=key,
                           help=f"{section.pdf}, PDF pages {section.proverb_pages[0]}-{section.proverb_pages[1]}")
    parser.add_argument("--pages", help="Only these PDF pages, e.g. 36-45,420-421 (default: the Part's proverb pages, "
                                        "or the section's pages)")
    parser.add_argument("--model-name", default=DEFAULT_LLM_MODEL)
    parser.add_argument("--vllm-url", default=DEFAULT_VLLM_URL)
    parser.add_argument("--dry-run", action="store_true",
                        help="Send nothing; count every request's prompt tokens and check they fit the context window")
    parser.add_argument("--check-reads", action="store_true",
                        help="Only check this run's pages have current Vision reads: the job does so before its server")
    return parser.parse_args()


def layout_stamp(page, found):
    """What a page's layout answer depends on beyond the phase's stamp: its user text and the lines it numbers."""
    return {"user_sha1": sha1(layout_user_text(page)), "lines_sha1": sha1(json.dumps(found["lines"]))}


def span_stamp(page, span):
    """What an Entry Span's answer depends on beyond the phase's stamp: its user text (the two reads of its lines with
    it), its lines and its crop."""
    return {"user_sha1": sha1(span_user_text(page, span["leading"], span["readings"])),
            "lines": [span["first"], span["last"]], "box": span["box"]}


def with_readings(spans, record):
    """Gives each of a page's `spans` its "readings", [(Line Number, line read, page read)], and its lines' "crop_reads",
    from the page's Vision `record`."""
    for span in spans:
        lines = record["lines"][span["first"] - 1:span["last"]]
        span["readings"] = [(line["n"], line["line_read"], line["page_read"]) for line in lines]
        span["crop_reads"] = [line["crop_reads"] for line in lines]


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
    """The Entry Span requests of `page_spans`' Entry Spans, which have their "readings" (see `with_readings`)."""
    schema = span_schema()
    for page, spans in page_spans.items():
        for span in spans:
            yield Request(span_key(page, span["first"]), (
                lambda page=page, span=span: image_messages(
                    SPAN_SYSTEM_PROMPT,
                    [(f"Entry Span of PDF page {page}:", data_url(span_image(doc, page, span["box"]), "image/png"))],
                    span_user_text(page, span["leading"], span["readings"]))
            ), schema, span_stamp(page, span))


def bands_of(log, page):
    """The bands of a page's Confirmed Spans, from `log` (review.read_log)."""
    return [record["band"] for record in log["confirmed"].get(page, [])]


def complete_line(page, found, log):
    """A page's "page_complete" line if it still applies: every line from its body start down falls in a band, so the
    page needs no request. Once a span is undone, or the line finder changes, it may not."""
    line = log["complete"].get(page)
    lines = found["lines"]
    if line is None or not 1 <= line["body_start"] <= len(lines):
        return None
    bands = bands_of(log, page)
    return line if all(in_band(l, bands) for l in lines[line["body_start"] - 1:]) else None


def page_answer(page, found, record, pdf_sha1, layout_dir, layout_base, spans_dir, span_base, log):
    """
    (answer, None) for a page whose every request is current or needs none. Its answer is the printed page number and
    first line from its layout answer (or its "page_complete" line), the PDF's hash, the page's size, its spans top to
    bottom and their Blocks in order: an Entry Span's from its answer, a Confirmed Span's the model's from its record, so
    undoing it needs no run. Each span has what review.lay_confirmed names. Else (None, why it has none, and the saved
    result of the request with no current answer, or None).
    """
    if found is None:
        return None, "never ran", None
    if not found["lines"]:
        return None, "no printed line was found on it", None
    complete, spans, pieces = complete_line(page, found, log), [], []
    if complete:
        printed, body_start = complete["printed_page"], complete["body_start"]
    else:
        layout, why = current_answer(layout_dir, page_key(page), {**layout_base, **layout_stamp(page, found)})
        if layout is None:
            return (None, why if why == "never ran" else f"layout request {why}",
                    os.path.join(layout_dir, f"{page_key(page)}.json"))
        why = vision_problem(record, found, pdf_sha1)
        if why:
            return None, f"Vision read {why}", None
        printed, body_start = layout["printed_page"], layout["body_start"]
        spans = entry_spans(found, layout, bands_of(log, page))
        with_readings(spans, record)
    for span in spans:
        key = span_key(page, span["first"])
        answer, why = current_answer(spans_dir, key, {**span_base, **span_stamp(page, span)})
        if answer is None:
            return (None, f"Entry Span {key} (Line Numbers {span['first']}-{span['last']}) {why}",
                    os.path.join(spans_dir, f"{key}.json"))
        pieces.append((span, answer["blocks"]))
    for held in log["confirmed"].get(page, []):
        pieces.append(({"first": held["first"], "last": held["last"], "leading": held["leading"], "box": held["crop"],
                        "band": held["band"], "readings": held["readings"], "crop_reads": held["crop_reads"]},
                       held["model_blocks"]))
    pieces.sort(key=lambda piece: piece[0]["band"][0])
    blocks = []
    for span, span_blocks in pieces:
        span["blocks"] = [len(blocks), len(blocks) + len(span_blocks)]
        blocks += span_blocks
    return {"printed_page": printed, "body_start": body_start, "pdf_sha1": pdf_sha1, "size": found["size"],
            "blocks": blocks, "spans": [span for span, _ in pieces]}, None, None


def print_missing(missing):
    """Every page with no answer and why; for a request that ran and failed, each attempt from its saved result."""
    print(f"[Kho tàng tục ngữ] {len(missing)} page(s) with no answer")
    for reason, result in missing:
        print(f"  {reason}")
        r = read_json(result) if result and os.path.exists(result) else None
        if r is None or r.get("status") == "ok":
            continue
        for a in r.get("attempt_log") or []:
            print(f"    attempt {a['attempt']}: {a['status']} after {a['elapsed_s']}s, "
                  f"{a.get('completion_tokens') or 0} token(s), finish_reason {a.get('finish_reason')}: "
                  f"{a.get('error')}")
        print(f"    result, with the last reply: {result}")


def main():
    args = parse_args()
    if args.part in SECTIONS:
        topic_index.main(args)
        return
    part = PARTS[args.part]
    pdf = part_pdf(part.pdf)
    if pdf is None:
        sys.exit(f"[Kho tàng tục ngữ] No PDF '{part.pdf}' in {BOOK_DIR} for --{args.part}")
    doc = open_pdf(pdf, part)
    n_pages = len(doc)
    first, last = part.proverb_pages
    only = page_set(args.pages, n_pages) if args.pages else list(range(first, min(last, n_pages) + 1))
    only = [page for page in only if page not in part.skipped_pages]

    store = os.path.join(STORE_DIR, args.part)
    lines_dir, vision_dir, layout_dir, spans_dir = (os.path.join(store, d)
                                                    for d in ("lines", "vision", "layout", "spans"))
    usage_file = os.path.join(store, "token_usage.jsonl")
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
                   "prompt_sha1": layout_prompt_sha1(), "repetition_penalty": REPETITION_PENALTY}
    span_base = {"pdf_sha1": pdf_sha1, "page_dpi": PAGE_DPI, "page_image": PAGE_IMAGE,
                 "prompt_sha1": span_prompt_sha1(), "repetition_penalty": REPETITION_PENALTY}

    # -- the Mac's printed lines and Vision reads, of every page saved from this PDF: this run's must all be current
    found, records, unread = {}, {}, []
    for page in range(1, n_pages + 1):
        lines = saved_lines(lines_dir, page, pdf_sha1, dict(part.turned_pages).get(page, 0))
        if lines is not None:
            found[page], records[page] = lines, read_result(vision_dir, page_key(page))
    for page in only:
        why = "no printed lines from this PDF"
        if page in found:
            why = vision_problem(records[page], found[page], pdf_sha1)
        if why:
            unread.append(f"  {page_key(page)}: {why}")
    if unread:
        sys.exit(f"[Kho tàng tục ngữ] {len(unread)} page(s) of this run have no current Vision read. On the Mac, run "
                 f"python3 -m src.khotangtucngu.vision_ocr --{args.part} with these pages, and copy its output here:\n"
                 + "\n".join(unread))

    # -- the developer's decisions: bands mean something only on the PDF they were made from
    log = read_log(store)
    other_pdf = [page for page, held in sorted(log["confirmed"].items()) if any(r["pdf_sha1"] != pdf_sha1 for r in held)]
    if other_pdf:
        sys.exit(f"[Kho tàng tục ngữ] {store}/review.jsonl has Confirmed Spans made from another PDF, on PDF page(s) "
                 f"{', '.join(map(str, other_pdf))}: their Blocks would be placed on different text")
    if args.check_reads:
        print(f"[Kho tàng tục ngữ] All {len(only)} page(s) of this run have current Vision reads")
        return
    to_read = [page for page in only if not complete_line(page, found[page], log)]
    print(f"[Kho tàng tục ngữ] {sum(map(len, log['confirmed'].values()))} Confirmed Span(s) in the review log, "
          f"{len(only) - len(to_read)} page(s) of this run fully confirmed: no request for them")

    if args.dry_run:
        with open(os.path.join(store, "dry_run_tokens.jsonl"), "w", encoding="utf-8") as out:
            vlm_requests.count_tokens(list(layout_requests(doc, to_read, found)), LAYOUT, args.model_name, out,
                                      label="Layout requests")
        print(f"[Dry Run] Per-request counts in {store}/dry_run_tokens.jsonl")
        return

    model = Model(args.model_name, args.vllm_url)
    vlm_requests.run_phase(layout_requests(doc, to_read, found), layout_dir, layout_base,
                           label="[Kho tàng tục ngữ] Layout requests", phase=LAYOUT, model=model, usage_file=usage_file)
    page_spans = {}
    for page in to_read:
        if found[page]["lines"]:
            layout, _ = current_answer(layout_dir, page_key(page), {**layout_base, **layout_stamp(page, found[page])})
            if layout is not None:
                page_spans[page] = entry_spans(found[page], layout, bands_of(log, page))
                with_readings(page_spans[page], records[page])
    vlm_requests.run_phase(span_requests(doc, page_spans), spans_dir, span_base,
                           label="[Kho tàng tục ngữ] Entry Span requests", phase=SPAN, model=model,
                           usage_file=usage_file)

    # -- outputs, rebuilt from every saved answer
    answers, readings, flagged, missing, no_answer = {}, {}, {}, [], []
    for page in range(1, n_pages + 1):
        # A skipped page has no answer and is no missing page: nothing carries over it, as across any page with none
        if page in part.skipped_pages:
            continue
        answer, why, result = page_answer(page, found.get(page), records.get(page), pdf_sha1, layout_dir, layout_base,
                                  spans_dir, span_base, log)
        if answer is not None:
            answers[page] = answer
            reads = [(line_read, page_read) for span in answer["spans"] for _, line_read, page_read in span["readings"]]
            readings[page] = "\n".join(read_of_line(*read) for read in reads)
            flagged[page] = flagged_reads(reads, [crops for span in answer["spans"] for crops in span["crop_reads"]])
        # A page outside this run counts only if its requests ran and one failed, or were made from other input: the
        # Mac may have read the whole Part for a job over a small batch
        elif page in only or (why != "never ran" and found[page]["lines"]):
            missing.append(warning(PAGE_MISSING, page_key(page), f"PDF page {page} has no answer: {why}", page))
            no_answer.append((f"PDF page {page}: {why}", result))
        if (page in only or page in answers) and found[page]["missed"]:
            patches = found[page]["missed"]
            top, bottom = min(m[1] for m in patches), max(m[3] for m in patches)
            missing.append(warning(INK_OUTSIDE, page_key(page), f"PDF page {page} has {len(patches)} patch(es) of "
                                   f"ink outside every printed line found ({top}-{bottom} px down the 300 dpi scan), "
                                   f"in no Entry Span", page))
    entries, warnings, pages, _ = rebuild(answers, log, abbreviations, part.book_page_offset, readings, flagged,
                                          part.skipped_pages, part.scan_gaps)
    # rebuild's Warning ids are unique, and a missing page's and a page's missed ink are their own
    warnings = priority_first(missing + warnings)

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
    write_json(os.path.join(store, "answers.json"), {str(p): answers[p] for p in sorted(answers)})
    write_json(os.path.join(store, "readings.json"), {str(p): readings[p] for p in sorted(readings)})
    write_json(os.path.join(store, "agreed.json"), {str(p): flagged[p] for p in sorted(flagged)})
    write_json(os.path.join(store, "entries.json"), {"part": args.part, "book_page_offset": part.book_page_offset,
                                                     "skipped_pages": list(part.skipped_pages),
                                                     "scan_gaps": [list(gap) for gap in part.scan_gaps],
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
    if no_answer:
        print_missing(no_answer)
    print(f"[Kho tàng tục ngữ] Entries in {store}/entries.json, Warnings in {store}/warnings.json")
    print(f"[Kho tàng tục ngữ] To review the Part: cd {store} && python3 serve.py")
    print_token_stats(usage_file)


if __name__ == "__main__":
    main()
