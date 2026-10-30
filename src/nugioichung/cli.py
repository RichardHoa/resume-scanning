"""
CLI Entrypoint for transcribing one Nữ Giới Chung Issue PDF (e.g. vsc-project/NuGioiChung/So1_Feb1_1918.pdf).

    python3 -m src.nugioichung.cli <issue.pdf> [--pages 1,2,6,13] [--pass layout|transcribe|all] [--run-dir <dir>]

Writes to vsc-project/NuGioiChung/runs/<issue>/<time>/ (or --run-dir):

  requests/layout/pNN.json          one layout answer per page; pNN/ holds its image as sent and its prompts
  requests/read/pNN-rMM.json        the printed lines of each Region, or pNN-rMM-sKK.json of each Strip of a tall
                                    Region; the folder of the same name holds its crop as sent and its prompts
  requests/format/pNN-rMM.json      the same Region's or Strip's text as Markdown, likewise (none for Footnotes)
  issue.md                          the Issue as Markdown, its Items in reading order, Footnotes paired with calls
  articles.csv                      one row per Article, in the old datasheet's columns
  pages/pNN.png                     each page, for the review viewer
  viewer.json                       the Issue's Items with the place on a page each stretch of their text was
                                    printed, each page's Regions and Strips with their printed lines and requests,
                                    and every Warning: pages with no layout, Regions left out, requests with no
                                    transcription, printed lines that didn't match the lines read, format answers not
                                    used, unpaired Footnotes and calls, and text outside any Region
  serve.py                          the review viewer: `python3 serve.py` in the run folder (on any machine, nothing
                                    to install) shows the Issue's text beside its pages, and appends each Resolution
                                    of a Warning and each Correction of the text to review.jsonl
  web/                              the viewer's page (index.html, style.css, app.js), served by serve.py
  token_usage.jsonl                 one line per request sent in this run folder, summarized at the end

Saved answers are stamped with the PDF's hash, the image settings and a hash of the prompts, so a run continued
with --run-dir only redoes requests that failed or never ran, and the outputs are always rebuilt from all saved
answers (review.jsonl is kept). The transcription pass runs each Region's or Strip's read request, then its format
request, given the read lines joined into paragraphs by code where they match the printed lines found on the scan.
--pages picks the pages whose requests run. --dry-run sends nothing: it counts each request's prompt tokens
with the model's own processor (images included) to check they fit the context window; transcription requests can
only be counted for pages that already have a layout answer, and format requests for Regions and Strips that
already have a read answer.
"""
import os
import sys

# Ensure repository root is in sys.path for 'src' package imports
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import argparse
import re
from datetime import datetime

import fitz

from src.core.config import DEFAULT_LLM_MODEL, DEFAULT_VLLM_URL
from src.nugioichung.assembly import (
    issue_markdown, issue_title, item_text, join_items, render_items, write_articles_csv
)
from src.nugioichung.layout import check_layout, layout_requests, page_stamp
from src.nugioichung.prompts import (
    FORMAT_SYSTEM_PROMPT, LAYOUT_SYSTEM_PROMPT, READ_SYSTEM_PROMPT, format_schema, layout_schema, prompt_sha1_input,
    read_schema
)
from src.nugioichung.settings import (
    CROP_DPI, LAYOUT_LONG_SIDE, LAYOUT_MAX_TOKENS, REQUEST_TIMEOUT, RETRY_TEMPERATURE, TRANSCRIBE_MAX_TOKENS
)
from src.nugioichung.regions import ARTICLE, page_key, warning
from src.nugioichung.transcribe import (
    check_read, format_requests, format_stamp, needs_format, read_requests, read_stamp, transcription
)
from src.providers import vlm_requests
from src.nugioichung.viewer import request_entry, write_viewer
from src.providers.vlm_requests import (
    Model, Phase, current_answer, file_sha1, is_current, page_set, print_token_stats, read_result, sha1,
    unique_ids
)

RUNS_DIR = os.path.join(_PROJECT_ROOT, "vsc-project", "NuGioiChung", "runs")
PASSES = {
    "layout": Phase("layout", step="nugioichung_layout", max_tokens=LAYOUT_MAX_TOKENS, thinking=False,
                    retry_temperature=RETRY_TEMPERATURE, timeout=REQUEST_TIMEOUT),
    "read": Phase("read", step="nugioichung_read", max_tokens=TRANSCRIBE_MAX_TOKENS, thinking=False,
                  retry_temperature=RETRY_TEMPERATURE, timeout=REQUEST_TIMEOUT),
    "format": Phase("format", step="nugioichung_format", max_tokens=TRANSCRIBE_MAX_TOKENS, thinking=False,
                    retry_temperature=RETRY_TEMPERATURE, timeout=REQUEST_TIMEOUT),
}
MONTHS = {"jan": "Janvier", "feb": "Février", "mar": "Mars", "apr": "Avril", "may": "Mai", "jun": "Juin",
          "jul": "Juillet", "aug": "Août", "sep": "Septembre", "oct": "Octobre", "nov": "Novembre", "dec": "Décembre"}


def parse_args():
    parser = argparse.ArgumentParser(description="Transcribe one Nữ Giới Chung Issue PDF")
    parser.add_argument("pdf", help="The Issue PDF, named like So1_Feb1_1918.pdf")
    parser.add_argument("--run-dir", help=f"Continue this run instead of starting {RUNS_DIR}/<issue>/<time>/")
    parser.add_argument("--pages", help="Only run the requests of these PDF pages, e.g. 1,2,6,13 or 1-4")
    parser.add_argument("--pass", dest="which", choices=["layout", "transcribe", "all"], default="all")
    parser.add_argument("--model-name", default=DEFAULT_LLM_MODEL)
    parser.add_argument("--vllm-url", default=DEFAULT_VLLM_URL)
    parser.add_argument("--dry-run", action="store_true",
                        help="Send nothing; count every request's prompt tokens and check they fit the context window")
    return parser.parse_args()


def parse_issue(stem):
    """'So1_Feb1_1918' -> {"number": 1, "date": "1er Février 1918", "published": "01/02/1918"}: the date as the paper
    prints it, and as the old datasheet's Ngày xuất bản (day/month/year)."""
    m = re.fullmatch(r"So(\d+)_([A-Za-z]{3})(\d{1,2})_(\d{4})", stem)
    if not m or m.group(2).lower() not in MONTHS:
        sys.exit(f"[Nữ Giới Chung] Cannot read the Issue number and date from '{stem}': name the PDF like "
                 f"So1_Feb1_1918.pdf")
    day, month = int(m.group(3)), list(MONTHS).index(m.group(2).lower()) + 1
    return {"number": int(m.group(1)),
            "date": f"{'1er' if day == 1 else day} {MONTHS[m.group(2).lower()]} {m.group(4)}",
            "published": f"{day:02d}/{month:02d}/{m.group(4)}"}


def request_status(results_dir, key, stamp):
    """A request's status for the summary: its saved status, "made from other input" or "never ran"."""
    r = read_result(results_dir, key)
    if r is None:
        return "never ran"
    if r.get("status") == "ok" and not is_current(r, stamp):
        return "made from other input"
    return r.get("status")


def main():
    args = parse_args()
    pdf = os.path.abspath(args.pdf)
    if not os.path.exists(pdf):
        sys.exit(f"[Nữ Giới Chung] No such PDF: {pdf}")
    stem = os.path.splitext(os.path.basename(pdf))[0]
    issue = parse_issue(stem)
    doc = fitz.open(pdf)
    n_pages = len(doc)
    only = page_set(args.pages, n_pages)
    passes = ["layout", "transcribe"] if args.which == "all" else [args.which]

    run_dir = os.path.abspath(args.run_dir) if args.run_dir else os.path.join(
        RUNS_DIR, stem, datetime.now().strftime("%Y%m%d-%H%M%S"))
    layout_dir = os.path.join(run_dir, "requests", "layout")
    read_dir = os.path.join(run_dir, "requests", "read")
    format_dir = os.path.join(run_dir, "requests", "format")
    usage_file = os.path.join(run_dir, "token_usage.jsonl")
    os.makedirs(run_dir, exist_ok=True)
    print(f"[Nữ Giới Chung] Số {issue['number']}, {issue['date']}: {n_pages} pages, running "
          f"{'+'.join(passes)} on {len(only)}; run folder {run_dir}")

    pdf_sha1 = file_sha1(pdf)
    layout_stamp = {"pdf_sha1": pdf_sha1, "layout_long_side": LAYOUT_LONG_SIDE,
                    "prompt_sha1": sha1(prompt_sha1_input(LAYOUT_SYSTEM_PROMPT, layout_schema()))}
    read_pass_stamp = {"pdf_sha1": pdf_sha1, "crop_dpi": CROP_DPI,
                       "prompt_sha1": sha1(prompt_sha1_input(READ_SYSTEM_PROMPT, read_schema()))}
    format_pass_stamp = {"pdf_sha1": pdf_sha1, "crop_dpi": CROP_DPI,
                         "prompt_sha1": sha1(prompt_sha1_input(FORMAT_SYSTEM_PROMPT, format_schema()))}

    def saved_layouts():
        """Checked layouts of every page with a current layout answer, the Warnings of the Regions they left out, and
        why each other page has none."""
        layouts, problems, no_layout = {}, [], {}
        for page in range(1, n_pages + 1):
            answer, why = current_answer(layout_dir, page_key(page), {**layout_stamp, **page_stamp(page)})
            if answer is None:
                no_layout[page] = why
                continue
            layouts[page], left_out = check_layout(doc, page, answer)
            problems += left_out
        return layouts, problems, no_layout

    def saved_reads(layouts):
        """{cut key: (checked read answer or None, why it has none)} for every Region and Strip laid out."""
        reads = {}
        for layout in layouts.values():
            for region in layout.regions:
                for cut in region.cuts:
                    answer, why = current_answer(read_dir, cut.key, {**read_pass_stamp, **read_stamp(region, cut)})
                    reads[cut.key] = (check_read(answer, cut) if answer is not None else None, why)
        return reads

    model = Model(args.model_name, args.vllm_url)
    if args.dry_run:
        with open(os.path.join(run_dir, "dry_run_tokens.jsonl"), "w", encoding="utf-8") as out:
            if "layout" in passes:
                vlm_requests.count_tokens(list(layout_requests(doc, only)), PASSES["layout"], args.model_name, out,
                                          label="Layout pass")
            if "transcribe" in passes:
                layouts, _, _ = saved_layouts()
                vlm_requests.count_tokens(list(read_requests(doc, layouts, only)), PASSES["read"],
                                          args.model_name, out, label="Read requests")
                vlm_requests.count_tokens(list(format_requests(doc, layouts, only, saved_reads(layouts))),
                                          PASSES["format"], args.model_name, out, label="Format requests")
                missing = [p for p in only if p not in layouts]
                if missing:
                    print(f"[Dry Run] Transcription requests not counted for page(s) {missing}: no layout answer yet")
                print("[Dry Run] Format requests are counted only for Regions and Strips with a read answer")
        print(f"[Dry Run] Per-request counts in {run_dir}/dry_run_tokens.jsonl")
        return

    if "layout" in passes:
        vlm_requests.run_phase(layout_requests(doc, only), layout_dir, layout_stamp, label="[Nữ Giới Chung] Layout pass",
                               phase=PASSES["layout"], model=model, save_requests=True, usage_file=usage_file)
    layouts, left_out, no_layout = saved_layouts()
    if "transcribe" in passes:
        vlm_requests.run_phase(read_requests(doc, layouts, only), read_dir, read_pass_stamp,
                               label="[Nữ Giới Chung] Read requests", phase=PASSES["read"], model=model,
                               save_requests=True, usage_file=usage_file)
    reads = saved_reads(layouts)
    if "transcribe" in passes:
        vlm_requests.run_phase(format_requests(doc, layouts, only, reads), format_dir, format_pass_stamp,
                               label="[Nữ Giới Chung] Format requests", phase=PASSES["format"], model=model,
                               save_requests=True, usage_file=usage_file)

    # -- outputs, rebuilt from the saved answers alone
    transcriptions, cuts, requests, mismatched, unformatted = {}, {}, {}, [], []
    read_statuses, format_statuses = [], []
    for layout in layouts.values():
        for region in layout.regions:
            for cut in region.cuts:
                cuts[cut.key] = cut
                read, why = reads[cut.key]
                status = request_status(read_dir, cut.key, {**read_pass_stamp, **read_stamp(region, cut)})
                read_statuses.append(status)
                requests[cut.key] = [request_entry(run_dir, read_dir, "read", cut.key, status)]
                if read is None:
                    transcriptions[cut.key] = (None, why)
                    continue
                if read["printed"] is None:
                    mismatched.append(warning("lines", cut.key, f"{cut.label}: {len(cut.lines)} printed lines found, "
                                              f"{len(read['lines'])} read", cut.page, cut.box))
                formatted = None
                if needs_format(region, read):
                    stamp = {**format_pass_stamp, **format_stamp(region, cut, read)}
                    formatted, why = current_answer(format_dir, cut.key, stamp)
                    status = request_status(format_dir, cut.key, stamp)
                    format_statuses.append(status)
                    requests[cut.key].append(request_entry(run_dir, format_dir, "format", cut.key, status))
                checked, fallback = transcription(region, cut, read, formatted, why)
                transcriptions[cut.key] = (checked, None)
                # As with layouts, a format request outside --pages counts only if it ran and failed
                if fallback and (region.page in only or why != "never ran"):
                    unformatted.append(warning("unformatted", cut.key, f"{cut.label}: {fallback}", cut.page, cut.box))
    items = join_items(layouts)
    blocks, assembled = render_items(items, transcriptions, cuts)
    gaps = [w for w in assembled if w["kind"] == "not_transcribed"]
    unpaired = [w for w in assembled if w["kind"] != "not_transcribed"]
    texts = [item_text(item_blocks) for item_blocks in blocks]
    with open(os.path.join(run_dir, "issue.md"), "w", encoding="utf-8") as f:
        f.write(issue_markdown(issue, items, texts))
    write_articles_csv(os.path.join(run_dir, "articles.csv"), issue, items, texts)

    # A page outside --pages counts only if its layout request ran and failed
    unread = [warning("no_layout", page_key(p), f"page {p} has no layout answer: {why}", p)
              for p, why in sorted(no_layout.items()) if p in only or why != "never ran"]
    outside = [warning("outside", f"{page_key(p)}-" + "-".join(map(str, box)),
                       f"printed text outside any Region at {box}", p, box)
               for p, layout in sorted(layouts.items()) for box in layout.outside]
    warnings = unique_ids(sorted(unread + left_out + gaps + mismatched + unformatted + unpaired + outside,
                                 key=lambda w: w["page"]))
    # Every page a Warning concerns is shown, even one outside --pages whose layout request failed
    shown = sorted(set(only) | set(layouts) | {w["page"] for w in warnings})
    write_viewer(run_dir, doc, issue_title(issue), shown, layouts, reads, requests, items, blocks, warnings, cuts)

    layout_statuses = [request_status(layout_dir, page_key(p), {**layout_stamp, **page_stamp(p)}) for p in shown]
    for name, statuses in (("Layout", layout_statuses), ("Read", read_statuses), ("Format", format_statuses)):
        print(f"[Nữ Giới Chung] {name} requests: {({s: statuses.count(s) for s in sorted(set(statuses))})}")
    n_regions = sum(len(layout.regions) for layout in layouts.values())
    n_strips = sum(len(r.strips) for layout in layouts.values() for r in layout.regions)
    n_matched = sum(read is not None and read["printed"] is not None for read, _ in reads.values())
    print(f"[Nữ Giới Chung] {len(layouts)} page(s) laid out, {n_regions} Region(s), {n_strips} Strip(s), "
          f"{len(items)} Item(s), {sum(i['kind'] == ARTICLE for i in items)} Article(s); printed lines matched in "
          f"{n_matched} of {sum(read is not None for read, _ in reads.values())} Region(s) and Strip(s) read")
    print(f"[Nữ Giới Chung] {len(warnings)} Warning(s): {len(unread)} page(s) with no layout, {len(left_out)} "
          f"Region(s) left out, {len(gaps)} request(s) with no transcription, {len(mismatched)} with printed lines "
          f"not matched, {len(unformatted)} format answer(s) not used, {len(unpaired)} unpaired Footnote(s) or "
          f"call(s), {len(outside)} patch(es) of text outside any Region")
    print(f"[Nữ Giới Chung] To review the run: cd {run_dir} && python3 serve.py   (the Issue is in issue.md)")
    print_token_stats(usage_file)

if __name__ == "__main__":
    main()
