"""
The cluster's job for the Topic Index (Hệ thống tra cứu theo chủ đề) of Part 4's PDF, run by cli.py for a key of
settings.SECTIONS:

    python3 -m src.khotangtucngu.cli --part-4-final-section [--pages 547-556,595-600] [--dry-run] [--check-reads]

With no --pages, every page of the section (547-674); --pages outside it are left out. As for a Part, a Mac first finds
each page's printed lines and reads them with Apple Vision (vision_ocr.py --part-4-final-section), and the job stops
before any request, naming the pages of its run with no current read; --check-reads does only that.

Each page's Index Lines are classified from their Vision reads (topics.classify_page), and each but a Running Head is
read by the model in a request of its own, from its crop at PAGE_DPI (pages.index_line_box): a number line's with no
Vision read in its prompt, a heading line's with its two reads as a hint (prompts.py,
docs/adr/0007-number-lines-read-without-a-hint.md beside the GLOSSARY). Each request is tried up to 3 times, its answer
saved and stamped as a Part's are, so a run redoes only the requests whose answer is missing, failed or stamped
differently, and runs over different pages add up. The outputs are rebuilt from every saved answer, not only this
run's, with the store's review.jsonl laid over them (topics.py), which no run writes. Writes to the section's store,
vsc-project/khoTangTucNguoiNguoiViet/store/<key>/:

  lines/pNNN-LMM.json     one answer per Index Line, by its page and Line Number, beside the Mac's lines/pNNN.json
  answers.json            every page's Index Lines with their band, crop, kind, both Vision reads, the values parsed
                          from them, the model's answer and whether the reads agree, so the review server needs no PDF
  entry_names.json        the names of the Proverb Entries of every Part whose store has an answers.json, with its
                          review log laid over, which the Exists check reads, the names a Part's number_jumps or
                          scan_gaps lose, and the Parts with no answers.json
  topics.json             the Topic Index assembled with the Confirmed Lines laid over
  warnings.json           every Warning: disagreements and single reads first, then unclassified lines, kinds the
                          model's read contradicts, the Count, Exists, Ascending, Letter order and Heading number
                          checks, lines with no owner, Parts with no answers.json, pages with no lines and ink outside
                          every line found
  pages/pNNN.png          each page, for the review server
  serve.py, web/,         the review server (topic_serve.py), its page (topic_web/), and the code it rebuilds the
  khotangtucngu/          index with (topics.py, with assembly.py, citations.py and diacritics.py), copied from this
                          package on every run: `python3 serve.py` in the store (on any machine, nothing to install)
  review.jsonl            the review log of Confirmed Lines, which serve.py appends to (see topics.py). No run writes
                          or rewrites it
  token_usage.jsonl       one line per request, summarized at the end by step
"""
import os
import shutil
import sys

from src.khotangtucngu.citations import Abbreviations, load_abbreviations
from src.khotangtucngu.export import with_confirmed
from src.khotangtucngu.pages import index_line_box, open_pdf, page_key, part_pdf, review_image, span_image, span_key
from src.khotangtucngu.prompts import (
    INDEX_HEADING_SYSTEM_PROMPT, INDEX_NUMBERS_SYSTEM_PROMPT, index_heading_prompt_sha1, index_heading_schema,
    index_heading_user_text, index_numbers_prompt_sha1, index_numbers_schema, index_numbers_user_text
)
from src.khotangtucngu.settings import (
    BOOK_DIR, FRONT_MATTER, INDEX_MAX_TOKENS, PAGE_DPI, PAGE_IMAGE, PARTS, REPETITION_PENALTY, REQUEST_TIMEOUT,
    RETRY_TEMPERATURE, SECTIONS, STORE_DIR
)
from src.khotangtucngu.topics import (
    NOT_INDEX, NUMBER_KINDS, agreement, classify_page, read_log, rebuild, vision_values
)
from src.khotangtucngu.vision_ocr import saved_lines, vision_problem
from src.providers import vlm_requests
from src.providers.vlm_requests import (
    Model, Phase, Request, current_answer, data_url, file_sha1, image_messages, page_set, print_token_stats,
    read_result, sha1, write_json
)

HERE = os.path.dirname(os.path.abspath(__file__))
# The modules serve.py rebuilds the index with, copied into <store>/khotangtucngu/
REVIEW_CODE = ("assembly.py", "citations.py", "diacritics.py", "topics.py")
NUMBERS = Phase("index_numbers", step="khotangtucngu_index_numbers", max_tokens=INDEX_MAX_TOKENS, thinking=False,
                retry_temperature=RETRY_TEMPERATURE, timeout=REQUEST_TIMEOUT, repetition_penalty=REPETITION_PENALTY)
HEADING = Phase("index_heading", step="khotangtucngu_index_heading", max_tokens=INDEX_MAX_TOKENS, thinking=False,
                retry_temperature=RETRY_TEMPERATURE, timeout=REQUEST_TIMEOUT, repetition_penalty=REPETITION_PENALTY)


def numbers_problem(answer):
    """Why a number line's answer can't be used, or None: the schema holds it to a letter and whole numbers."""
    if not isinstance(answer.get("letter"), str) or not isinstance(answer.get("numbers"), list) \
            or not all(isinstance(x, int) and not isinstance(x, bool) and x >= 0 for x in answer["numbers"]):
        return "no letter and list of whole numbers"
    return None


def heading_problem(answer):
    return None if isinstance(answer.get("text"), str) and answer["text"].strip() else "no text"


def plan_pages(found, records, pages, pdf_sha1):
    """Each of `pages`' Index Lines with its kind, crop and Vision reads, {page: [line]}, classified in PDF order, a
    heading open at the end of one page carrying onto the next. Pages with no current Vision read are left out."""
    plans, heading_open, previous = {}, False, None
    for page in pages:
        if page not in found or vision_problem(records[page], found[page], pdf_sha1):
            continue
        if previous != page - 1:
            heading_open = False
        previous = page
        lines = [{"n": r["n"], "line": line, "band": line[:2], "crop": index_line_box(found[page], r["n"]),
                  "line_read": r["line_read"], "page_read": r["page_read"]}
                 for r, line in zip(records[page]["lines"], found[page]["lines"])]
        kinds, heading_open = classify_page(lines, found[page]["size"], heading_open)
        for line, kind in zip(lines, kinds):
            line["kind"] = kind
        plans[page] = lines
    return plans


def is_number_line(line):
    return line["kind"] in NUMBER_KINDS


def line_stamp(page, line):
    """What an Index Line's answer depends on beyond its phase's stamp: its user text (a heading's with its reads) and
    its crop."""
    text = (index_numbers_user_text(page, line["n"]) if is_number_line(line)
            else index_heading_user_text(page, line["n"], line["line_read"], line["page_read"]))
    return {"user_sha1": sha1(text), "box": line["crop"]}


def line_requests(doc, plans, numbers):
    """The requests of `plans`' number lines (`numbers`) or heading lines; a Running Head has none."""
    schema = index_numbers_schema() if numbers else index_heading_schema()
    for page, lines in plans.items():
        for line in lines:
            if line["kind"] == NOT_INDEX or is_number_line(line) != numbers:
                continue
            system, text = ((INDEX_NUMBERS_SYSTEM_PROMPT, index_numbers_user_text(page, line["n"])) if numbers else
                            (INDEX_HEADING_SYSTEM_PROMPT,
                             index_heading_user_text(page, line["n"], line["line_read"], line["page_read"])))
            yield Request(span_key(page, line["n"]), (
                lambda page=page, line=line, system=system, text=text: image_messages(
                    system, [(f"Line {line['n']} of PDF page {page}:",
                              data_url(span_image(doc, page, line["crop"]), "image/png"))], text)
            ), schema, line_stamp(page, line), check=numbers_problem if numbers else heading_problem)


def answered_line(page, line, lines_dir, numbers_base, heading_base):
    """An Index Line for answers.json (see topics.py), with the model's current answer, or why it has none."""
    kind = line["kind"]
    vision = vision_values(kind, line["line_read"], line["page_read"])
    vlm, why = None, None
    if kind != NOT_INDEX:
        base = numbers_base if is_number_line(line) else heading_base
        answer, why = current_answer(lines_dir, span_key(page, line["n"]), {**base, **line_stamp(page, line)})
        if answer is not None:
            vlm = ({"letter": answer["letter"], "numbers": answer["numbers"]} if is_number_line(line)
                   else {"text": answer["text"].strip()})
    return {"n": line["n"], "band": line["band"], "crop": line["crop"], "kind": kind, "line_read": line["line_read"],
            "page_read": line["page_read"], "vision": vision, "vlm": vlm, "vlm_why": why,
            "agreement": agreement(kind, vision, vlm)}


def has_run(page, lines, lines_dir):
    """Whether any request of a page's lines ever ran: a page outside this run is in answers.json only then."""
    return any(read_result(lines_dir, span_key(page, line["n"])) is not None for line in lines)


def entry_names():
    """
    entry_names.json: {"parts": the Parts whose store has an answers.json, "missing_parts": the others, "names":
    {letter: its Proverb Entries' numbers}, "unresolved": [[letter, first, last]]}. A Part's entries are rebuilt with its
    review log, as its export does. The numbers a Part's number_jumps skip are unresolved, and so are those between the
    last entry before a scan gap and the first after it, of one letter: lost in the book or its scan, not misread.
    """
    abbreviations = Abbreviations(load_abbreviations(FRONT_MATTER))
    names, unresolved, parts, missing = {}, [], [], []
    for key, part in PARTS.items():
        store = os.path.join(STORE_DIR, key)
        if not os.path.exists(os.path.join(store, "answers.json")):
            missing.append(key)
            continue
        parts.append(key)
        entries, _, _ = with_confirmed(store, abbreviations, part.book_page_offset, part.skipped_pages, part.scan_gaps)
        for entry in entries:
            names.setdefault(entry["letter"], set()).add(entry["number"])
        unresolved += [[letter, before + 1, after - 1] for letter, before, after in part.number_jumps]
        for resumes, _ in part.scan_gaps:
            before = [e for e in entries if e["pdf_pages"][0] < resumes]
            after = [e for e in entries if e["pdf_pages"][0] >= resumes]
            if before and after and before[-1]["letter"] == after[0]["letter"] \
                    and after[0]["number"] > before[-1]["number"] + 1:
                gap = [before[-1]["letter"], before[-1]["number"] + 1, after[0]["number"] - 1]
                if gap not in unresolved:
                    unresolved.append(gap)
    return {"parts": parts, "missing_parts": missing,
            "names": {letter: sorted(numbers) for letter, numbers in names.items()}, "unresolved": unresolved}


def main(args):
    key = args.part
    section = SECTIONS[key]
    pdf = part_pdf(section.pdf)
    if pdf is None:
        sys.exit(f"[Kho tàng tục ngữ] No PDF '{section.pdf}' in {BOOK_DIR} for --{key}")
    doc = open_pdf(pdf, section)
    first, last = section.proverb_pages
    section_pages = list(range(first, min(last, len(doc)) + 1))
    only = [page for page in page_set(args.pages, len(doc)) if first <= page <= last] if args.pages else section_pages

    store = os.path.join(STORE_DIR, key)
    lines_dir, vision_dir = os.path.join(store, "lines"), os.path.join(store, "vision")
    usage_file = os.path.join(store, "token_usage.jsonl")
    print(f"[Kho tàng tục ngữ] {key} ({section.pdf}): the Topic Index, PDF pages {first}-{last}, running {len(only)} "
          f"({'--pages ' + args.pages if args.pages else 'every page'}); store {store}")

    pdf_sha1 = file_sha1(pdf)
    found, records, unread = {}, {}, []
    for page in section_pages:
        lines = saved_lines(lines_dir, page, pdf_sha1, 0)
        if lines is not None:
            found[page], records[page] = lines, read_result(vision_dir, page_key(page))
    for page in only:
        why = vision_problem(records[page], found[page], pdf_sha1) if page in found else "no printed lines from this PDF"
        if why:
            unread.append(f"  {page_key(page)}: {why}")
    if unread:
        sys.exit(f"[Kho tàng tục ngữ] {len(unread)} page(s) of this run have no current Vision read. On the Mac, run "
                 f"python3 -m src.khotangtucngu.vision_ocr --{key} with these pages, and copy its output here:\n"
                 + "\n".join(unread))

    log = read_log(store)
    other_pdf = [page for page, held in sorted(log.items()) if any(r["pdf_sha1"] != pdf_sha1 for r in held)]
    if other_pdf:
        sys.exit(f"[Kho tàng tục ngữ] {store}/review.jsonl has Confirmed Lines made from another PDF, on PDF page(s) "
                 f"{', '.join(map(str, other_pdf))}: their values would be laid over different lines")
    if args.check_reads:
        print(f"[Kho tàng tục ngữ] All {len(only)} page(s) of this run have current Vision reads")
        return

    plans = plan_pages(found, records, section_pages, pdf_sha1)
    run_plans = {page: plans[page] for page in only}
    numbers_base = {"pdf_sha1": pdf_sha1, "page_dpi": PAGE_DPI, "page_image": PAGE_IMAGE,
                    "prompt_sha1": index_numbers_prompt_sha1(), "repetition_penalty": REPETITION_PENALTY}
    heading_base = {**numbers_base, "prompt_sha1": index_heading_prompt_sha1()}

    if args.dry_run:
        with open(os.path.join(store, "dry_run_tokens.jsonl"), "w", encoding="utf-8") as out:
            for phase, numbers, label in ((NUMBERS, True, "Number line requests"),
                                          (HEADING, False, "Heading line requests")):
                vlm_requests.count_tokens(list(line_requests(doc, run_plans, numbers)), phase, args.model_name, out,
                                          label=label)
        print(f"[Dry Run] Per-request counts in {store}/dry_run_tokens.jsonl")
        return

    model = Model(args.model_name, args.vllm_url)
    vlm_requests.run_phase(line_requests(doc, run_plans, True), lines_dir, numbers_base,
                           label="[Kho tàng tục ngữ] Number line requests", phase=NUMBERS, model=model,
                           usage_file=usage_file)
    vlm_requests.run_phase(line_requests(doc, run_plans, False), lines_dir, heading_base,
                           label="[Kho tàng tục ngữ] Heading line requests", phase=HEADING, model=model,
                           usage_file=usage_file)

    # -- outputs, rebuilt from every saved answer
    pages = {}
    for page in section_pages:
        if page not in only and not (page in plans and has_run(page, plans[page], lines_dir)):
            continue
        lines = plans.get(page, [])
        why = None if lines else ("no printed line was found on it" if page in found else "it has no Vision read")
        pages[str(page)] = {"pdf_sha1": pdf_sha1, "size": found[page]["size"] if page in found else None,
                            "book_page": page + section.book_page_offset, "image": f"pages/{page_key(page)}.png",
                            "missed": found[page]["missed"] if page in found else [], "why": why,
                            "lines": [answered_line(page, line, lines_dir, numbers_base, heading_base)
                                      for line in lines]}
    answers = {"section": {"key": key, "pages": [first, last], "book_page_offset": section.book_page_offset},
               "pages": pages}
    names = entry_names()
    result = rebuild(answers, log, names)

    os.makedirs(os.path.join(store, "pages"), exist_ok=True)
    for page in sorted(map(int, pages)):
        image = os.path.join(store, "pages", f"{page_key(page)}.png")
        # This run's pages are drawn again; others only if missing
        if page in only or not os.path.exists(image):
            with open(image, "wb") as f:
                f.write(review_image(doc, page))
    write_json(os.path.join(store, "answers.json"), answers)
    write_json(os.path.join(store, "entry_names.json"), names)
    write_json(os.path.join(store, "topics.json"), {"topics": result["topics"]})
    write_json(os.path.join(store, "warnings.json"), result["warnings"])
    # The review server's and the rebuild's single master copies are this package's; review.jsonl beside them is
    # never touched
    shutil.copyfile(os.path.join(HERE, "topic_serve.py"), os.path.join(store, "serve.py"))
    shutil.copytree(os.path.join(HERE, "topic_web"), os.path.join(store, "web"), dirs_exist_ok=True)
    code = os.path.join(store, "khotangtucngu")
    os.makedirs(code, exist_ok=True)
    for name in REVIEW_CODE:
        shutil.copyfile(os.path.join(HERE, name), os.path.join(code, name))
    with open(os.path.join(code, "__init__.py"), "w", encoding="utf-8") as f:
        f.write('"""Copied from src/khotangtucngu by topic_index.py: what serve.py rebuilds the Topic Index with."""\n')

    lines = [line for p in pages.values() for line in p["lines"]]
    counts = lambda field: {v: sum(1 for l in lines if l[field] == v) for v in sorted({l[field] for l in lines})}
    kinds = {}
    for w in result["warnings"]:
        kinds[w["kind"]] = kinds.get(w["kind"], 0) + 1
    print(f"[Kho tàng tục ngữ] {len(pages)} page(s), {len(lines)} Index Line(s) in the store: {counts('kind')}")
    print(f"[Kho tàng tục ngữ] Reads: {counts('agreement')}; {sum(len(held) for held in log.values())} Confirmed "
          f"Line(s) in the review log")
    if names["missing_parts"]:
        print(f"[Kho tàng tục ngữ] No answers.json for {', '.join(names['missing_parts'])}: their entry names are "
              f"unchecked")
    print(f"[Kho tàng tục ngữ] {sum(len(t['subtopics']) for t in result['topics'])} tiểu chủ đề under "
          f"{len(result['topics'])} chủ đề")
    print(f"[Kho tàng tục ngữ] {len(result['warnings'])} Warning(s): {kinds}")
    print(f"[Kho tàng tục ngữ] Index in {store}/topics.json, Warnings in {store}/warnings.json")
    print(f"[Kho tàng tục ngữ] To review the index: cd {store} && python3 serve.py")
    print_token_stats(usage_file)
