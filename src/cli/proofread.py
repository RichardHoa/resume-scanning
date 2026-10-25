"""
CLI Entrypoint for the AI Proofreading Pass over a scanned book (see src/pipelines/proofreader.py)

Reads <book-dir>, the folder `python -m vsc_ocr prepare-ai <book>` writes in the vsc repo (book.json, book.raw.md,
pages.jsonl, notes.json, spellings.yaml if the book has Spelling Rules, titles.yaml if it has Story Titles,
images/), and writes to
<book-dir>/ai-pass/<time>/ (or --run-dir):

  phase1/pNNNN.json      one transcription per page
  phase2/<note-id>.json  one result per note the code could not pair with its call
  book.phase1.md         the pages joined into the book, notes paired where the code could, names spelled as the
                         Spelling Rules or else the story's OCR print them
  book.ai.md             ... and the Phase 2 calls placed: review with `review <book> --ai` in the vsc repo
  boxes.jsonl            each block's boxes on the scans, for the review page
  ai_corrections.jsonl   book.raw.md -> book.ai.md as AI Proposals, in the shape of the review tool's corrections.jsonl
  coverage.jsonl         per page: OCR lines the transcription missed, text it added, OCR lines left out as noise,
                         the printed page number
  dropped.jsonl          pages with no transcription and answers that could not be applied, and why

A re-run with --run-dir only runs the tasks with no successful result yet; the books and logs are always rebuilt
from all saved results. --no-ocr-hint sends each page's image without its OCR lines (and its story's names).
--ocr-marks keeps the OCR's marks on a word the model read with the same letters where both OCR engines agree. To
measure it, make two copies of a finished run, rebuild one with `--run-dir <a> --phase 1` and the other with
`--run-dir <b> --phase 1 --ocr-marks` (no model calls: every page is done; neither keeps its Phase 2 notes, so
they compare alike), then `python3 scripts/proofread/compare_ocr_hint.py <b> <a> --book-dir <book-dir>` ("with hint" is b). --dry-run sends nothing: it
counts each task's prompt tokens with the model's own processor (images included) to check they fit the context
window.
"""
import os
import sys

# Ensure repository root is in sys.path for 'src' package imports
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import argparse
import base64
import glob
import hashlib
import json
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime

from src.core.config import (
    DEFAULT_LLM_MODEL, DEFAULT_VLLM_URL, VLLM_MAX_MODEL_LEN, VLLM_MAX_CONCURRENT_REQUESTS,
    PROOFREAD_PAGE_MAX_TOKENS, PROOFREAD_NOTE_MAX_TOKENS, PROOFREAD_RETRY_TEMPERATURE
)
from src.pipelines.proofreader import (
    FLAG, apply_note_results, assemble, enforce_spellings, flag_leftovers, note_tasks, page_names, read_page,
    spelling_rules, story_titles
)
from src.prompts.proofread_prompts import (
    NOTE_SYSTEM_PROMPT, note_schema, note_user_text, transcribe_schema, transcribe_system_prompt,
    transcribe_user_text
)

ATTEMPTS = 3    # the first try and two retries
PHASES = {
    1: dict(step="proofread_page", max_tokens=PROOFREAD_PAGE_MAX_TOKENS, thinking=False),
    2: dict(step="proofread_note", max_tokens=PROOFREAD_NOTE_MAX_TOKENS, thinking=True),
}


def parse_args():
    parser = argparse.ArgumentParser(description="AI Proofreading Pass over a scanned book")
    parser.add_argument("--book-dir", default=os.path.join(_PROJECT_ROOT, "vsc-project"),
                        help="The data-for-ai/<book>/ folder from `python -m vsc_ocr prepare-ai` (default: vsc-project/)")
    parser.add_argument("--run-dir", help="Continue this run instead of starting <book-dir>/ai-pass/<time>/")
    parser.add_argument("--phase", choices=["1", "2", "all"], default="all")
    parser.add_argument("--pages", help="Only these PDF pages, e.g. 10-40,52 (a note goes with the page it is printed on)")
    parser.add_argument("--no-ocr-hint", action="store_true",
                        help="Send each page's image without its OCR lines (to compare with a run that sends them)")
    parser.add_argument("--ocr-marks", action="store_true",
                        help="Keep the OCR's marks on a word the model read with the same letters, where both OCR "
                             "engines agree (see the docstring to measure it first)")
    parser.add_argument("--model-name", default=DEFAULT_LLM_MODEL)
    parser.add_argument("--vllm-url", default=DEFAULT_VLLM_URL)
    parser.add_argument("--dry-run", action="store_true",
                        help="Send nothing; count every task's prompt tokens and check they fit the context window")
    return parser.parse_args()


def page_set(spec):
    """'10-40,52' -> {10, ..., 40, 52}; None -> None (every page)."""
    if not spec:
        return None
    pages = set()
    for part in spec.split(","):
        a, _, b = part.strip().partition("-")
        pages.update(range(int(a), int(b or a) + 1))
    return pages


def join_blocks(blocks):
    return "\n\n".join(blocks) + "\n"


def write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


def read_json(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)


def read_yaml(path):
    import yaml
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


# -- page images
def data_url(path):
    with open(path, "rb") as f:
        return "data:image/jpeg;base64," + base64.b64encode(f.read()).decode("ascii")


def messages_for(system, images, text, images_dir):
    content = []
    for p in images:
        content.append({"type": "text", "text": f"Scan of PDF page {p}:"})
        content.append({"type": "image_url", "image_url": {"url": data_url(os.path.join(images_dir, f"p{p:04d}.jpg"))}})
    content.append({"type": "text", "text": text})
    return [{"role": "system", "content": system}, {"role": "user", "content": content}]


# -- tasks: (key, images, messages, schema)
def page_requests(entries, only, images_dir, ocr_hint, names):
    system = transcribe_system_prompt(ocr_hint)
    for page in sorted(entries):
        if only and page not in only:
            continue
        text = transcribe_user_text(entries[page], ocr_hint, names.get(page, ()))
        yield f"p{page:04d}", [page], (
            lambda page=page, text=text: messages_for(system, [page], text, images_dir)
        ), transcribe_schema()


def note_requests(blocks, pages, only, images_dir):
    for t in note_tasks(blocks, pages):
        if only and t["note_page"] not in only:
            continue
        images = [t["note_page"]] if t["note_page"] else []
        text = note_user_text(t["note_id"], t["definition"], t["note_page"], t["candidates"], t["whole_story"])
        yield t["note_id"], images, (
            lambda images=images, text=text: messages_for(NOTE_SYSTEM_PROMPT, images, text, images_dir)
        ), note_schema([i for i, _ in t["candidates"]])


# -- running
def run_one(key, phase, build_messages, schema, args, out_path, stamp):
    from src.providers import vllm_client
    cfg = PHASES[phase]
    result = {"task": key, "phase": phase, "model": args.model_name, **stamp}
    for attempt in range(1, ATTEMPTS + 1):
        result["attempts"] = attempt
        try:
            reply = vllm_client.chat(
                args.vllm_url, args.model_name, build_messages(),
                temperature=0.0 if attempt == 1 else PROOFREAD_RETRY_TEMPERATURE,
                json_schema=schema, max_tokens=cfg["max_tokens"], step=cfg["step"],
                enable_thinking=cfg["thinking"]
            )
        except RuntimeError as e:
            too_long = "context length" in str(e) or "max_model_len" in str(e)
            result.update(status="too_long" if too_long else "failed", error=str(e))
            if too_long:
                break
            continue
        result.update(reasoning=reply.reasoning, finish_reason=reply.finish_reason,
                      completion_tokens=reply.completion_tokens, content=reply.content)
        try:
            answer = json.loads(reply.content)
        except json.JSONDecodeError as e:
            result.update(status="failed", error=f"answer is not JSON ({e}); finish_reason={reply.finish_reason}")
            continue
        result.update(status="ok", error=None, answer=answer)
        break
    write_json(out_path, result)
    return result


def run_phase(phase, requests, args, results_dir, stamp):
    os.makedirs(results_dir, exist_ok=True)
    todo = []
    for key, _, build, schema in requests:
        path = os.path.join(results_dir, f"{key}.json")
        if os.path.exists(path):
            done = read_json(path)
            if done.get("status") == "ok" and all(done.get(k) == v for k, v in stamp.items()):
                continue
        todo.append((key, build, schema, path))
    print(f"[Proofread] Phase {phase}: {len(todo)} task(s) to run, concurrency {VLLM_MAX_CONCURRENT_REQUESTS}")
    counts = {}
    with ThreadPoolExecutor(max_workers=VLLM_MAX_CONCURRENT_REQUESTS) as pool:
        futures = {pool.submit(run_one, key, phase, build, schema, args, path, stamp): key
                   for key, build, schema, path in todo}
        for n, fut in enumerate(as_completed(futures), 1):
            r = fut.result()
            counts[r["status"]] = counts.get(r["status"], 0) + 1
            if r["status"] != "ok":
                print(f"  [{n}/{len(todo)}] {r['task']}: {r['status']} after {r['attempts']} attempt(s): "
                      f"{(r.get('error') or '')[:200]}")
            elif n % 25 == 0 or n == len(todo):
                print(f"  [{n}/{len(todo)}] {counts}")


def load_results(results_dir, stamp):
    """Successful answers by task key, from results made against the same input (`stamp`)."""
    out = {}
    for path in sorted(glob.glob(os.path.join(results_dir, "*.json"))):
        r = read_json(path)
        if r.get("status") == "ok" and all(r.get(k) == v for k, v in stamp.items()):
            out[r["task"]] = r["answer"]
    return out


def sha1(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()


# -- dry run
def count_tokens(requests, phase, model_name, out_file):
    from io import BytesIO
    from PIL import Image
    from transformers import AutoProcessor
    processor = AutoProcessor.from_pretrained(model_name, trust_remote_code=True)
    cfg = PHASES[phase]
    counts = []
    for key, _, build, _ in requests:
        hf_messages = []
        for m in build():
            parts = m["content"] if isinstance(m["content"], list) else [{"type": "text", "text": m["content"]}]
            hf_parts = []
            for part in parts:
                if part["type"] == "image_url":
                    raw = base64.b64decode(part["image_url"]["url"].split(",", 1)[1])
                    hf_parts.append({"type": "image", "image": Image.open(BytesIO(raw)).convert("RGB")})
                else:
                    hf_parts.append(part)
            hf_messages.append({"role": m["role"], "content": hf_parts})
        ids = processor.apply_chat_template(hf_messages, add_generation_prompt=True, tokenize=True,
                                            return_dict=True, enable_thinking=cfg["thinking"])["input_ids"]
        n = len(ids[0]) if ids and isinstance(ids[0], list) else len(ids)
        counts.append(n)
        out_file.write(json.dumps({"phase": phase, "task": key, "prompt_tokens": n,
                                   "max_tokens": cfg["max_tokens"]}) + "\n")
    if not counts:
        print(f"[Dry Run] Phase {phase}: no tasks")
        return
    s = sorted(counts)
    over = sum(1 for n in counts if n + cfg["max_tokens"] > VLLM_MAX_MODEL_LEN)
    print(f"[Dry Run] Phase {phase}: {len(s)} tasks, prompt tokens p50 {s[len(s) // 2]} / "
          f"p95 {s[min(len(s) - 1, len(s) * 95 // 100)]} / max {s[-1]}; + max_tokens {cfg['max_tokens']} "
          f"vs context {VLLM_MAX_MODEL_LEN}: {over} task(s) would not fit")


def write_jsonl(path, rows):
    with open(path, "w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


def main():
    args = parse_args()
    book_dir = os.path.abspath(args.book_dir)
    raw_path = os.path.join(book_dir, "book.raw.md")
    if not os.path.exists(os.path.join(book_dir, "book.json")):
        sys.exit(f"[Proofread] No book.json in {book_dir}: copy the data-for-ai/<book>/ folder that "
                 f"`python -m vsc_ocr prepare-ai <book>` makes in the vsc repo")
    book = read_json(os.path.join(book_dir, "book.json"))
    with open(raw_path, encoding="utf-8") as f:
        raw_text = f.read()
    if book["raw_sha1"] != sha1(raw_text):
        sys.exit("[Proofread] book.raw.md is not the one book.json was made from: re-run prepare-ai and copy the folder")
    with open(os.path.join(book_dir, "pages.jsonl"), encoding="utf-8") as f:
        pages_text = f.read()
    entries = {e["page"]: e for e in (json.loads(line) for line in pages_text.splitlines() if line.strip())}
    notes_path = os.path.join(book_dir, "notes.json")
    known_notes = read_json(notes_path)["notes"] if os.path.exists(notes_path) else []
    images_dir = os.path.join(book_dir, "images")
    spellings_path = os.path.join(book_dir, "spellings.yaml")
    rules = spelling_rules(read_yaml(spellings_path) if os.path.exists(spellings_path) else None)
    titles_path = os.path.join(book_dir, "titles.yaml")
    titles = story_titles(read_yaml(titles_path) if os.path.exists(titles_path) else None)
    names = page_names(raw_text, entries, rules, titles=titles)

    run_dir = os.path.abspath(args.run_dir) if args.run_dir else os.path.join(
        book_dir, "ai-pass", datetime.now().strftime("%Y%m%d-%H%M%S"))
    os.makedirs(run_dir, exist_ok=True)
    only = page_set(args.pages)
    phases = [1, 2] if args.phase == "all" else [int(args.phase)]
    ocr_hint = not args.no_ocr_hint
    print(f"[Proofread] Run folder: {run_dir}" + ("" if ocr_hint else " (no OCR hint)")
          + (" (OCR marks kept)" if args.ocr_marks else "")
          + f"; {len(rules['words'])} word and {len(rules['phrases'])} phrase Spelling Rule(s)"
          + f", {len(titles)} Story Title(s)")

    phase1_stamp = {"input_sha1": sha1(pages_text), "dpi": book["dpi"], "ocr_hint": ocr_hint}

    def phase1_book():
        """The pages read joined into the book, then its names and Spelling Rules enforced (both edit in place)."""
        results = load_results(os.path.join(run_dir, "phase1"), phase1_stamp)
        read = {int(k[1:]): read_page(entries[int(k[1:])], a, args.ocr_marks, rules["depends"])
                for k, a in results.items() if int(k[1:]) in entries}
        book = assemble(raw_text, read, known_notes, titles)
        return book, enforce_spellings(book.blocks, book.pages, raw_text, entries, rules, titles)

    if args.dry_run:
        with open(os.path.join(run_dir, "dry_run_tokens.jsonl"), "w", encoding="utf-8") as out:
            if 1 in phases:
                count_tokens(list(page_requests(entries, only, images_dir, ocr_hint, names)), 1, args.model_name, out)
            if 2 in phases:
                _, p1 = phase1_book()
                count_tokens(list(note_requests(p1.blocks, p1.pages, only, images_dir)), 2, args.model_name, out)
        print(f"[Dry Run] Per-task counts in {run_dir}/dry_run_tokens.jsonl")
        return

    if 1 in phases:
        run_phase(1, page_requests(entries, only, images_dir, ocr_hint, names), args, os.path.join(run_dir, "phase1"),
                  phase1_stamp)
    book1, p1 = phase1_book()
    p1_text = join_blocks(p1.blocks)
    with open(os.path.join(run_dir, "book.phase1.md"), "w", encoding="utf-8") as f:
        f.write(p1_text)

    # Phase 2 answers name blocks of the Phase 1 output, so they only count against that same output
    phase2_stamp = {"input_sha1": sha1(p1_text), "dpi": book["dpi"]}
    if 2 in phases:
        run_phase(2, note_requests(p1.blocks, p1.pages, only, images_dir), args, os.path.join(run_dir, "phase2"),
                  phase2_stamp)
    answers = load_results(os.path.join(run_dir, "phase2"), phase2_stamp)
    for note_id, a in answers.items():
        prefix = f"[^{note_id}]:"
        a["definition"] = a.get("definition", "").strip()
        if a["definition"].startswith(prefix):
            a["definition"] = a["definition"][len(prefix):].strip()
    p2 = apply_note_results(p1.blocks, p1.pages, answers)
    p3 = flag_leftovers(p2.blocks, p2.pages)

    with open(os.path.join(run_dir, "book.ai.md"), "w", encoding="utf-8") as f:
        f.write(join_blocks(p3.blocks))
    # Phase 2 only edits blocks in place, so the Phase 1 boxes still line up; the sha1 tells review an edited block
    write_jsonl(os.path.join(run_dir, "boxes.jsonl"),
                ({"i": i, "sha1": sha1(b), "boxes": bx} for i, (b, bx) in enumerate(zip(p3.blocks, book1.boxes))))
    now = datetime.now().isoformat(timespec="seconds")
    write_jsonl(os.path.join(run_dir, "ai_corrections.jsonl"),
                ({"time": now, **p, "phase": phase, "model": args.model_name}
                 for phase, proposals in ((1, book1.proposals + p1.proposals), (2, p2.proposals + p3.proposals))
                 for p in proposals))
    write_jsonl(os.path.join(run_dir, "coverage.jsonl"), book1.coverage)
    read_pages = {c["page"] for c in book1.coverage}
    unread = [{"task": f"page {p}", "why": "no successful transcription"}
              for p in sorted(entries) if (not only or p in only) and p not in read_pages]
    write_jsonl(os.path.join(run_dir, "dropped.jsonl"), unread + p2.dropped)

    for phase in (1, 2):
        rd = os.path.join(run_dir, f"phase{phase}")
        statuses = [read_json(p).get("status") for p in glob.glob(os.path.join(rd, "*.json"))]
        if statuses:
            summary = {s: statuses.count(s) for s in sorted(set(statuses))}
            print(f"[Proofread] Phase {phase} task results: {summary}")
    coverage = book1.coverage
    missed = sum(len(c["missed"]) for c in coverage)
    added = sum(len(c["added"]) for c in coverage)
    left_out = sum(len(c.get("left_out", [])) for c in coverage)
    off = [c["page"] for c in coverage if c["printed_page_ok"] is False]
    print(f"[Proofread] {len(coverage)} pages read: {missed} OCR line(s) missed (put back as ⚠ ai-missed?), "
          f"{added} block(s) with text no OCR line is under (⚠), {left_out} OCR line(s) left out as noise"
          + (f"; printed page number differs from the expected one on pdf {off}" if off else ""))
    ruled = sum(1 for p in p1.proposals if p.get("rule"))
    flagged = sum(1 for p in p1.proposals if p["after"][0].endswith(FLAG) and not p["before"][0].endswith(FLAG))
    marked = sum(len(c.get("ocr_marks", [])) for c in coverage)
    print(f"[Proofread] Spellings: {len(p1.proposals)} block(s) changed or flagged ({ruled} by a Spelling Rule, "
          f"{flagged} with a name still spelled two ways)"
          + (f"; {marked} word(s) took the OCR's marks" if marked else ""))
    print(f"[Proofread] {len(book1.proposals) + len(p1.proposals)} Phase 1 and "
          f"{len(p2.proposals) + len(p3.proposals)} Phase 2 AI Proposals, "
          f"{len(unread) + len(p2.dropped)} dropped")
    print(f"[Proofread] Copy book.ai.md, ai_corrections.jsonl and boxes.jsonl from {run_dir} "
          f"to data/books/<book>/ai/ in the vsc repo, then run `python -m vsc_ocr review <book> --ai`")


if __name__ == "__main__":
    main()
