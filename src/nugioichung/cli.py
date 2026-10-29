"""
CLI Entrypoint for transcribing one Nữ Giới Chung Issue PDF (e.g. vsc-project/NuGioiChung/So1_Feb1_1918.pdf).

    python3 -m src.nugioichung.cli <issue.pdf> [--pages 1,2,6,13] [--pass layout|transcribe|all] [--run-dir <dir>]

Writes to vsc-project/NuGioiChung/runs/<issue>/<time>/ (or --run-dir):

  requests/layout/pNN.json          one layout answer per page; pNN/ holds its image as sent and its prompts
  requests/transcribe/pNN-rMM.json  one transcription per Region, or pNN-rMM-sKK.json per Strip of a tall Region;
                                    the folder of the same name holds its crop as sent and its prompts
  layout/pNN.png                    each page with its snapped Regions outlined and numbered, Strip cuts dashed,
                                    and ⚠ on printed text outside any Region
  issue.md                          the Issue as Markdown, its Items in reading order, Footnotes paired with calls
  articles.csv                      one row per Article, in the old datasheet's columns
  dropped.jsonl                     what needs looking at, and why: pages with no layout, Regions left out,
                                    requests with no transcription, unpaired Footnotes and calls, and text outside
                                    any Region
  inspect.html                      page → Regions → Strips: the drawn page, then each request's image, prompt and
                                    answer

Saved answers are stamped with the PDF's hash, the image settings and a hash of the prompts, so a run continued
with --run-dir only redoes requests that failed or never ran, and the outputs are always rebuilt from all saved
answers. --pages picks the pages whose requests run. --dry-run sends nothing: it counts each request's prompt tokens
with the model's own processor (images included) to check they fit the context window; transcription requests can
only be counted for pages that already have a layout answer.
"""
import os
import sys

# Ensure repository root is in sys.path for 'src' package imports
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import argparse
import hashlib
import re
from datetime import datetime

import fitz

from src.core.config import DEFAULT_LLM_MODEL, DEFAULT_VLLM_URL
from src.nugioichung.assembly import issue_markdown, issue_title, join_items, render_items, write_articles_csv
from src.nugioichung.inspection import draw_layout, drawn_page, write_inspect
from src.nugioichung.layout import check_layout, layout_requests, page_stamp
from src.nugioichung.pages import layout_image
from src.nugioichung.prompts import (
    LAYOUT_SYSTEM_PROMPT, TRANSCRIBE_SYSTEM_PROMPT, footnotes_schema, layout_schema, prompt_sha1_input,
    transcribe_schema
)
from src.nugioichung.settings import (
    CROP_DPI, LAYOUT_LONG_SIDE, LAYOUT_MAX_TOKENS, RETRY_TEMPERATURE, TRANSCRIBE_MAX_TOKENS
)
from src.nugioichung.regions import ARTICLE, page_key
from src.nugioichung.transcribe import check_transcription, cut_stamp, transcribe_requests
from src.providers import vlm_requests
from src.providers.vlm_requests import Model, Phase, current_answer, is_current, read_result, sha1, write_jsonl

RUNS_DIR = os.path.join(_PROJECT_ROOT, "vsc-project", "NuGioiChung", "runs")
PASSES = {
    "layout": Phase("layout", step="nugioichung_layout", max_tokens=LAYOUT_MAX_TOKENS, thinking=False,
                    retry_temperature=RETRY_TEMPERATURE),
    "transcribe": Phase("transcribe", step="nugioichung_transcribe", max_tokens=TRANSCRIBE_MAX_TOKENS,
                        thinking=False, retry_temperature=RETRY_TEMPERATURE),
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


def page_set(spec, n_pages):
    """'1-4,13' -> [1, 2, 3, 4, 13]; None -> every page."""
    if not spec:
        return list(range(1, n_pages + 1))
    pages = set()
    for part in spec.split(","):
        a, _, b = part.strip().partition("-")
        pages.update(range(int(a), int(b or a) + 1))
    return sorted(p for p in pages if 1 <= p <= n_pages)


def request_status(results_dir, key, stamp):
    """A request's status for the summary: its saved status, "made from other input" or "never ran"."""
    r = read_result(results_dir, key)
    if r is None:
        return "never ran"
    if r.get("status") == "ok" and not is_current(r, stamp):
        return "made from other input"
    return r.get("status")


def file_sha1(path):
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


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
    transcribe_dir = os.path.join(run_dir, "requests", "transcribe")
    os.makedirs(run_dir, exist_ok=True)
    print(f"[Nữ Giới Chung] Số {issue['number']}, {issue['date']}: {n_pages} pages, running "
          f"{'+'.join(passes)} on {len(only)}; run folder {run_dir}")

    pdf_sha1 = file_sha1(pdf)
    layout_stamp = {"pdf_sha1": pdf_sha1, "layout_long_side": LAYOUT_LONG_SIDE,
                    "prompt_sha1": sha1(prompt_sha1_input(LAYOUT_SYSTEM_PROMPT, layout_schema()))}
    transcribe_stamp = {"pdf_sha1": pdf_sha1, "crop_dpi": CROP_DPI,
                        "prompt_sha1": sha1(prompt_sha1_input(TRANSCRIBE_SYSTEM_PROMPT,
                                                              [transcribe_schema(), footnotes_schema()]))}

    def saved_layouts():
        """Checked layouts of every page with a current layout answer, the Regions they left out, and why each other
        page has none."""
        layouts, problems, no_layout = {}, [], {}
        for page in range(1, n_pages + 1):
            answer, why = current_answer(layout_dir, page_key(page), {**layout_stamp, **page_stamp(page)})
            if answer is None:
                no_layout[page] = why
                continue
            layouts[page], left_out = check_layout(doc, page, answer)
            problems += left_out
        return layouts, problems, no_layout

    model = Model(args.model_name, args.vllm_url)
    if args.dry_run:
        with open(os.path.join(run_dir, "dry_run_tokens.jsonl"), "w", encoding="utf-8") as out:
            if "layout" in passes:
                vlm_requests.count_tokens(list(layout_requests(doc, only)), PASSES["layout"], args.model_name, out,
                                          label="Layout pass")
            if "transcribe" in passes:
                layouts, _, _ = saved_layouts()
                vlm_requests.count_tokens(list(transcribe_requests(doc, layouts, only)), PASSES["transcribe"],
                                          args.model_name, out, label="Transcription pass")
                missing = [p for p in only if p not in layouts]
                if missing:
                    print(f"[Dry Run] Transcription requests not counted for page(s) {missing}: no layout answer yet")
        print(f"[Dry Run] Per-request counts in {run_dir}/dry_run_tokens.jsonl")
        return

    if "layout" in passes:
        vlm_requests.run_phase(layout_requests(doc, only), layout_dir, layout_stamp, label="[Nữ Giới Chung] Layout pass",
                               phase=PASSES["layout"], model=model, save_requests=True)
    layouts, dropped, no_layout = saved_layouts()
    if "transcribe" in passes:
        vlm_requests.run_phase(transcribe_requests(doc, layouts, only), transcribe_dir, transcribe_stamp,
                               label="[Nữ Giới Chung] Transcription pass", phase=PASSES["transcribe"], model=model,
                               save_requests=True)

    # -- outputs, rebuilt from the saved answers alone
    transcriptions, transcribe_statuses = {}, []
    for layout in layouts.values():
        for region in layout.regions:
            for cut in region.cuts:
                stamp = {**transcribe_stamp, **cut_stamp(region, cut)}
                answer, why = current_answer(transcribe_dir, cut.key, stamp)
                checked = check_transcription(region, answer) if answer is not None else None
                transcriptions[cut.key] = (checked, why)
                transcribe_statuses.append(request_status(transcribe_dir, cut.key, stamp))
    items = join_items(layouts)
    texts, gaps, unpaired = render_items(items, transcriptions)
    with open(os.path.join(run_dir, "issue.md"), "w", encoding="utf-8") as f:
        f.write(issue_markdown(issue, items, texts))
    write_articles_csv(os.path.join(run_dir, "articles.csv"), issue, items, texts)

    os.makedirs(os.path.join(run_dir, "layout"), exist_ok=True)
    for page, layout in layouts.items():
        draw_layout(layout_image(doc, page), layout, os.path.join(run_dir, drawn_page(page)))
    shown = sorted(set(only) | set(layouts))
    write_inspect(run_dir, issue_title(issue), shown, layouts, layout_dir,
                  transcribe_dir, layout_stamp, transcribe_stamp)

    # A page outside --pages counts only if its layout request ran and failed
    unread = [{"task": f"page {p}", "why": f"no layout answer: {why}"} for p, why in sorted(no_layout.items())
              if p in only or why != "never ran"]
    outside = [{"task": f"page {p}", "why": f"text outside any Region at {box}"}
               for p, layout in sorted(layouts.items()) for box in layout.outside]
    write_jsonl(os.path.join(run_dir, "dropped.jsonl"), unread + dropped + gaps + unpaired + outside)

    layout_statuses = [request_status(layout_dir, page_key(p), {**layout_stamp, **page_stamp(p)}) for p in shown]
    for name, statuses in (("Layout", layout_statuses), ("Transcription", transcribe_statuses)):
        print(f"[Nữ Giới Chung] {name} requests: {({s: statuses.count(s) for s in sorted(set(statuses))})}")
    n_regions = sum(len(layout.regions) for layout in layouts.values())
    n_strips = sum(len(r.strips) for layout in layouts.values() for r in layout.regions)
    print(f"[Nữ Giới Chung] {len(layouts)} page(s) laid out, {n_regions} Region(s), {n_strips} Strip(s), "
          f"{len(items)} Item(s), {sum(i['kind'] == ARTICLE for i in items)} Article(s)")
    print(f"[Nữ Giới Chung] To look at (see dropped.jsonl): {len(unread)} page(s) with no layout, {len(dropped)} "
          f"Region(s) left out, {len(gaps)} request(s) with no transcription, {len(unpaired)} unpaired Footnote(s) "
          f"or call(s), {len(outside)} patch(es) of text outside any Region")
    print(f"[Nữ Giới Chung] Open {run_dir}/inspect.html to check the run, and read {run_dir}/issue.md")

if __name__ == "__main__":
    main()
