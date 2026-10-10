"""
CLI Entrypoint for the AI Proofreading Pass over a scanned book (see src/pipelines/proofreader.py)

Reads <book-dir>/book.raw.md, <book-dir>/pages.jsonl (from `python -m vsc_ocr export-pages` in the vsc repo) and
the book's scanned PDF, and writes to <book-dir>/ai-pass/<time>/ (or --run-dir):

  phase1/pNNNN.json      one result per page task
  phase2/<note-id>.json  one result per note task
  book.phase1.md         book.raw.md with the Phase 1 AI Proposals applied
  book.ai.md             ... and the Phase 2 ones: review with `diff book.raw.md book.ai.md`
  ai_corrections.jsonl   every AI Proposal, in the shape of the review tool's corrections.jsonl
  dropped.jsonl          answers that could not be applied, and why

A re-run with --run-dir only runs the tasks with no successful result yet; the books and logs are always rebuilt
from all saved results. --dry-run sends nothing: it counts each task's prompt tokens with the model's own
processor (images included) to check they fit the context window.
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
    apply_note_results, apply_page_results, block_pages, note_tasks, page_task
)
from src.prompts.proofread_prompts import (
    NOTE_SYSTEM_PROMPT, PAGE_SYSTEM_PROMPT, note_schema, note_user_text, page_schema, page_user_text
)

ATTEMPTS = 3    # the first try and two retries
PHASES = {
    1: dict(step="proofread_page", max_tokens=PROOFREAD_PAGE_MAX_TOKENS, thinking=False),
    2: dict(step="proofread_note", max_tokens=PROOFREAD_NOTE_MAX_TOKENS, thinking=True),
}


def parse_args():
    parser = argparse.ArgumentParser(description="AI Proofreading Pass over a scanned book")
    parser.add_argument("--book-dir", default=os.path.join(_PROJECT_ROOT, "vsc-project"),
                        help="Folder with book.raw.md, pages.jsonl and the book's PDF (default: vsc-project/)")
    parser.add_argument("--run-dir", help="Continue this run instead of starting <book-dir>/ai-pass/<time>/")
    parser.add_argument("--phase", choices=["1", "2", "all"], default="all")
    parser.add_argument("--pages", help="Only these PDF pages, e.g. 10-40,52 (a note goes with the page it is printed on)")
    parser.add_argument("--dpi", type=int, default=200, help="Resolution the pages are sent at (default 200)")
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


def split_blocks(text):
    text = text.rstrip("\n")
    return text.split("\n\n") if text else []


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


# -- page images
class Scans:
    """The book's PDF pages as JPEG, rendered once into <book-dir>/render-<dpi>/."""

    def __init__(self, pdf_path, cache_dir, dpi):
        self.pdf_path, self.cache_dir, self.dpi = pdf_path, cache_dir, dpi
        os.makedirs(cache_dir, exist_ok=True)

    def path(self, page):
        return os.path.join(self.cache_dir, f"p{page:04d}.jpg")

    def render(self, pages):
        missing = sorted(p for p in set(pages) if not os.path.exists(self.path(p)))
        if not missing:
            return
        import fitz
        print(f"[Proofread] Rendering {len(missing)} page(s) at {self.dpi} dpi into {self.cache_dir}")
        with fitz.open(self.pdf_path) as doc:
            for p in missing:
                pix = doc[p - 1].get_pixmap(dpi=self.dpi, colorspace=fitz.csGRAY)
                with open(self.path(p), "wb") as f:
                    f.write(pix.tobytes("jpeg", jpg_quality=85))

    def data_url(self, page):
        with open(self.path(page), "rb") as f:
            return "data:image/jpeg;base64," + base64.b64encode(f.read()).decode("ascii")


def messages_for(system, images, text, scans):
    content = []
    for p in images:
        content.append({"type": "text", "text": f"Scan of PDF page {p}:"})
        content.append({"type": "image_url", "image_url": {"url": scans.data_url(p)}})
    content.append({"type": "text", "text": text})
    return [{"role": "system", "content": system}, {"role": "user", "content": content}]


# -- tasks: (key, phase, messages, schema)
def page_requests(blocks, manifest, only, scans):
    for entry in manifest:
        if not entry["own"] or (only and entry["page"] not in only):
            continue
        t = page_task(blocks, entry)
        text = page_user_text(t["page"], t["owned_text"], t["before"], t["continued"], t["after"])
        yield f"p{t['page']:04d}", t["images"], (
            lambda t=t, text=text: messages_for(PAGE_SYSTEM_PROMPT, t["images"], text, scans)
        ), page_schema(t["own"])


def note_requests(blocks, pages, only, scans):
    for t in note_tasks(blocks, pages):
        if only and t["note_page"] not in only:
            continue
        images = [t["note_page"]] if t["note_page"] else []
        text = note_user_text(t["note_id"], t["definition"], t["note_page"], t["candidates"], t["whole_story"])
        yield t["note_id"], images, (
            lambda images=images, text=text: messages_for(NOTE_SYSTEM_PROMPT, images, text, scans)
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


def main():
    args = parse_args()
    book_dir = os.path.abspath(args.book_dir)
    raw_path = os.path.join(book_dir, "book.raw.md")
    with open(raw_path, encoding="utf-8") as f:
        raw_text = f.read()
    with open(os.path.join(book_dir, "pages.jsonl"), encoding="utf-8") as f:
        manifest = [json.loads(line) for line in f if line.strip()]
    if manifest and manifest[0]["raw_sha1"] != sha1(raw_text):
        sys.exit("[Proofread] pages.jsonl was exported from a different book.raw.md: re-run export-pages and copy both")
    pdfs = glob.glob(os.path.join(book_dir, "*.pdf"))
    if len(pdfs) != 1:
        sys.exit(f"[Proofread] Expected one PDF in {book_dir}, found {len(pdfs)}")

    run_dir = os.path.abspath(args.run_dir) if args.run_dir else os.path.join(
        book_dir, "ai-pass", datetime.now().strftime("%Y%m%d-%H%M%S"))
    os.makedirs(run_dir, exist_ok=True)
    scans = Scans(pdfs[0], os.path.join(book_dir, f"render-{args.dpi}"), args.dpi)
    only = page_set(args.pages)
    phases = [1, 2] if args.phase == "all" else [int(args.phase)]
    raw_blocks = split_blocks(raw_text)
    raw_pages = block_pages(manifest)
    print(f"[Proofread] Run folder: {run_dir}")

    # Images every selected task needs, rendered once up front (PyMuPDF is not thread-safe)
    needed = {p for e in manifest if e["own"] and (not only or e["page"] in only) for o in e["own"] for p in o["pages"]}
    needed |= {t["note_page"] for t in note_tasks(raw_blocks, raw_pages)
               if t["note_page"] and (not only or t["note_page"] in only)}
    scans.render(needed)

    phase1_stamp = {"input_sha1": sha1(raw_text), "dpi": args.dpi}

    def phase1_book():
        results = load_results(os.path.join(run_dir, "phase1"), phase1_stamp)
        return apply_page_results(raw_blocks, raw_pages, {int(k[1:]): v["changes"] for k, v in results.items()})

    if args.dry_run:
        with open(os.path.join(run_dir, "dry_run_tokens.jsonl"), "w", encoding="utf-8") as out:
            if 1 in phases:
                count_tokens(list(page_requests(raw_blocks, manifest, only, scans)), 1, args.model_name, out)
            if 2 in phases:
                p1 = phase1_book()
                print("[Dry Run] Phase 2 counted on " + ("the Phase 1 output" if p1.proposals else "book.raw.md"))
                count_tokens(list(note_requests(p1.blocks, p1.pages, only, scans)), 2, args.model_name, out)
        print(f"[Dry Run] Per-task counts in {run_dir}/dry_run_tokens.jsonl")
        return

    if 1 in phases:
        run_phase(1, page_requests(raw_blocks, manifest, only, scans), args, os.path.join(run_dir, "phase1"),
                  phase1_stamp)
    p1 = phase1_book()
    p1_text = join_blocks(p1.blocks)
    with open(os.path.join(run_dir, "book.phase1.md"), "w", encoding="utf-8") as f:
        f.write(p1_text)

    # Phase 2 answers name blocks of the Phase 1 output, so they only count against that same output
    phase2_stamp = {"input_sha1": sha1(p1_text), "dpi": args.dpi}
    if 2 in phases:
        run_phase(2, note_requests(p1.blocks, p1.pages, only, scans), args, os.path.join(run_dir, "phase2"),
                  phase2_stamp)
    answers = load_results(os.path.join(run_dir, "phase2"), phase2_stamp)
    for note_id, a in answers.items():
        prefix = f"[^{note_id}]:"
        a["definition"] = a.get("definition", "").strip()
        if a["definition"].startswith(prefix):
            a["definition"] = a["definition"][len(prefix):].strip()
    p2 = apply_note_results(p1.blocks, p1.pages, answers)

    with open(os.path.join(run_dir, "book.ai.md"), "w", encoding="utf-8") as f:
        f.write(join_blocks(p2.blocks))
    now = datetime.now().isoformat(timespec="seconds")
    with open(os.path.join(run_dir, "ai_corrections.jsonl"), "w", encoding="utf-8") as f:
        for phase, applied in ((1, p1), (2, p2)):
            for p in applied.proposals:
                f.write(json.dumps({"time": now, **p, "phase": phase, "model": args.model_name},
                                   ensure_ascii=False) + "\n")
    with open(os.path.join(run_dir, "dropped.jsonl"), "w", encoding="utf-8") as f:
        for d in p1.dropped + p2.dropped:
            f.write(json.dumps(d, ensure_ascii=False) + "\n")

    for phase in (1, 2):
        rd = os.path.join(run_dir, f"phase{phase}")
        statuses = [read_json(p).get("status") for p in glob.glob(os.path.join(rd, "*.json"))]
        if statuses:
            summary = {s: statuses.count(s) for s in sorted(set(statuses))}
            print(f"[Proofread] Phase {phase} task results: {summary}")
    print(f"[Proofread] {len(p1.proposals)} Phase 1 and {len(p2.proposals)} Phase 2 AI Proposals, "
          f"{len(p1.dropped) + len(p2.dropped)} dropped")
    print(f"[Proofread] Review: diff {raw_path} {os.path.join(run_dir, 'book.ai.md')}")


if __name__ == "__main__":
    main()
