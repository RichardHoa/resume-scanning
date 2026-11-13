"""
The Mac's step of transcribing a Kho tàng tục ngữ người Việt PDF Part: Apple Vision reads its pages, and the cluster's
job (cli.py) uses the reads.

    python3 -m src.khotangtucngu.vision_ocr --part-1 [--pages 36-45,420-424]
    python3 -m src.khotangtucngu.vision_ocr --part-4-final-section [--pages 547-556]

With no --pages, every proverb page of the Part, as in cli.py; a page the Part skips (settings.Part) never. A key of
settings.SECTIONS is read the same way, every page of the section, into its own store. Run it in your own terminal:
Vision's default compute device can fail under the Claude Code sandbox (docs/adr/0004-apple-vision-reads-each-page.md
beside the GLOSSARY). Its dependencies are requirements-macos.txt.

Each page's printed lines are found on the scan, and each is read twice (docs/adr/0005-two-reads-and-model-edits.md):
on its own from its crop at PAGE_DPI on white padding, and with the whole page at VISION_PAGE_DPI, each observation of
which goes to the line whose band holds the centre of its box. An observation matching no line, or spanning two, is
saved as unmatched and otherwise unused. Each line is also read from the VISION_STABILITY_CROPS, which only tell how
stable its Agreed Syllables are. Writes to the Part's store, vsc-project/khoTangTucNguoiNguoiViet/store/<part>/:

  lines/pNNN.json     the page's printed lines found on the scan, and ink outside them
  vision/pNNN.json    the page's Vision record: the PDF's hash, the stamp of how it was read, its status and error, each
                      Line Number's box, two reads and crop reads, and the unmatched observations

A page whose record is current is skipped, so runs over different pages add up and an interrupted run carries on; a
page Vision fails on is saved as failed and read again next time. The run ends by printing the `rsync` line that copies
these two folders to the cluster, and transfers nothing itself.
"""
import argparse
import json
import os
import platform
import select
import subprocess
import sys
import tempfile
import time
from io import BytesIO

from PIL import Image

from src.khotangtucngu.diacritics import flagged_reads, syllables
from src.khotangtucngu.pages import find_lines, line_box, open_pdf, page_key, part_pdf, span_image
from src.khotangtucngu.settings import (
    PAGE_DPI, PARTS, SECTIONS, STORE_DIR, VISION_LANGUAGE, VISION_LANGUAGE_CORRECTION, VISION_LINE_PAD_PX,
    VISION_PAGE_DPI, VISION_READ_TIMEOUT, VISION_REVISION, VISION_STABILITY_CROPS
)
from src.providers.page_images import whole_page_at_dpi
from src.providers.vlm_requests import file_sha1, page_set, read_json, read_result, write_json

READER_SOURCE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "vision_reader.swift")


def parse_args():
    parser = argparse.ArgumentParser(description="Read the pages of one Kho tàng tục ngữ PDF Part with Apple Vision")
    which = parser.add_mutually_exclusive_group(required=True)
    for key, part in PARTS.items():
        which.add_argument(f"--{key}", dest="part", action="store_const", const=key,
                           help=f"{part.pdf}, proverb pages {part.proverb_pages[0]}-{part.proverb_pages[1]}")
    for key, section in SECTIONS.items():
        which.add_argument(f"--{key}", dest="part", action="store_const", const=key,
                           help=f"{section.pdf}, PDF pages {section.proverb_pages[0]}-{section.proverb_pages[1]}")
    parser.add_argument("--pages", help="Only these PDF pages, e.g. 36-45,420-424 (default: the Part's proverb pages, "
                                        "or the section's pages)")
    return parser.parse_args()


def saved_lines(lines_dir, page, pdf_sha1, turned):
    """A page's printed lines as saved in `lines_dir` from this PDF (pages.find_lines) turned by `turned` degrees (its
    Part's turned_pages), or None."""
    path = os.path.join(lines_dir, f"{page_key(page)}.json")
    if not os.path.exists(path):
        return None
    saved = read_json(path)
    if saved.get("pdf_sha1") != pdf_sha1 or saved.get("turned", 0) != turned:
        return None
    return {k: saved[k] for k in ("size", "lines", "ocr_tops", "missed")}


def vision_problem(record, found, pdf_sha1):
    """Why a page's Vision `record` can't be used with its printed lines `found`, or None."""
    if record is None:
        return "never ran"
    if record.get("status") != "ok":
        return f"failed: {(record.get('error') or '')[:150]}"
    if record.get("pdf_sha1") != pdf_sha1:
        return "made from another PDF"
    boxes = [line_box(found, n) for n in range(1, len(found["lines"]) + 1)]
    if [line["box"] for line in record["lines"]] != boxes:
        return "made from other printed lines"
    return None


class VisionReader:
    """vision_reader.swift compiled into `folder`, one process for the whole run. If it stops, its read fails and the
    next read starts it again."""

    def __init__(self, folder):
        self.binary, self.process = os.path.join(folder, "vision_reader"), None
        print("[Kho tàng tục ngữ] Compiling the Vision reader")
        try:
            built = subprocess.run(["swiftc", "-O", READER_SOURCE, "-o", self.binary], capture_output=True, text=True)
        except FileNotFoundError:
            sys.exit("[Kho tàng tục ngữ] No swiftc: install Apple's Command Line Tools (xcode-select --install)")
        if built.returncode:
            sys.exit(f"[Kho tàng tục ngữ] The Vision reader did not compile:\n{built.stderr}")

    def read(self, image):
        """The observations Vision reads on the image at path `image`. Raises RuntimeError if it can't."""
        if self.process is None or self.process.poll() is not None:
            self.process = subprocess.Popen(
                [self.binary, str(VISION_REVISION), VISION_LANGUAGE, "1" if VISION_LANGUAGE_CORRECTION else "0"],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True, encoding="utf-8")
        try:
            self.process.stdin.write(image + "\n")
            self.process.stdin.flush()
            if not select.select([self.process.stdout], [], [], VISION_READ_TIMEOUT)[0]:
                raise TimeoutError(f"no answer in {VISION_READ_TIMEOUT} s")
            answer = json.loads(self.process.stdout.readline())
        except (OSError, ValueError) as e:
            # Anything but its answer on its stdout: a later answer could be taken for the wrong image's
            self.close()
            raise RuntimeError(f"the Vision reader stopped: {type(e).__name__}: {e}") from e
        if "error" in answer:
            raise RuntimeError(answer["error"])
        return answer["observations"]

    def close(self):
        if self.process is not None:
            self.process.kill()
            self.process.wait()
            self.process = None


def vision_stamp():
    """How every Vision record of a run is read: a record stamped otherwise is read again."""
    return {"macos": platform.mac_ver()[0], "vision_revision": VISION_REVISION, "language": VISION_LANGUAGE,
            "language_correction": VISION_LANGUAGE_CORRECTION, "line_dpi": PAGE_DPI, "page_dpi": VISION_PAGE_DPI,
            "line_pad_px": VISION_LINE_PAD_PX, "stability_crops": [list(crop) for crop in VISION_STABILITY_CROPS]}


def joined(observations):
    """The text of `observations` joined left to right."""
    return " ".join(o["text"].strip() for o in sorted(observations, key=lambda o: o["box"][0]) if o["text"].strip())


def page_reads(observations, found):
    """
    (each printed line's page read, by Line Number; the unmatched observations) of `observations`, a whole page's:
    each goes to the line whose band holds the centre of its box, unless the box reaches over the middles of two
    lines. An unmatched one's box is saved in px of the 300 dpi scan.
    """
    (w, h), lines = found["size"], found["lines"]
    on_line, unmatched = {}, []
    for o in observations:
        left, top, right, bottom = o["box"][0] * w, o["box"][1] * h, o["box"][2] * w, o["box"][3] * h
        centre = (top + bottom) / 2
        holding = [n for n, line in enumerate(lines, 1) if line[0] <= centre < line[1]]
        spanned = sum(top <= (line[0] + line[1]) / 2 <= bottom for line in lines)
        if holding and spanned < 2:
            on_line.setdefault(holding[0], []).append(o)
        else:
            unmatched.append({**o, "box": [round(left), round(top), round(right), round(bottom)]})
    return {n: joined(found_here) for n, found_here in on_line.items()}, unmatched


def padded(png, zoom=1):
    """A line's crop (png) `zoom` times larger, as an image on white, VISION_LINE_PAD_PX (as large) wider on every side."""
    crop = Image.open(BytesIO(png))
    if zoom != 1:
        crop = crop.resize((crop.width * zoom, crop.height * zoom), Image.Resampling.LANCZOS)
    pad = VISION_LINE_PAD_PX * zoom
    image = Image.new("L", (crop.width + 2 * pad, crop.height + 2 * pad), 255)
    image.paste(crop, (pad, pad))
    return image


def read_page(reader, doc, page, found, folder):
    """A page's "lines" and "unmatched" for its Vision record: every line read on its own and from each of
    VISION_STABILITY_CROPS, and the page read whole, using image files in `folder`."""
    path = os.path.join(folder, "image.png")
    with open(path, "wb") as f:
        f.write(whole_page_at_dpi(doc, page, VISION_PAGE_DPI))
    on_line, unmatched = page_reads(reader.read(path), found)

    def read_crop(box, zoom=1):
        padded(span_image(doc, page, box), zoom).save(path)
        return joined(reader.read(path))

    lines = []
    for n in range(1, len(found["lines"]) + 1):
        box = line_box(found, n)
        lines.append({"n": n, "box": box, "line_read": read_crop(box), "page_read": on_line.get(n, ""),
                      "crop_reads": [read_crop(line_box(found, n, below_px), zoom)
                                     for below_px, zoom in VISION_STABILITY_CROPS]})
    return {"lines": lines, "unmatched": unmatched}


def disputed_share(records):
    """(Disputed Syllables, all syllables) of the line reads of `records`' lines with both reads."""
    disputed, total = 0, 0
    for record in records:
        for line in record["lines"]:
            if syllables(line["line_read"]) and syllables(line["page_read"]):
                marked = flagged_reads([(line["line_read"], line["page_read"])])["syllables"]
                disputed += sum(not agreed for _, agreed, _ in marked)
                total += len(marked)
    return disputed, total


def main():
    args = parse_args()
    if sys.platform != "darwin":
        sys.exit(f"[Kho tàng tục ngữ] Apple Vision runs only on macOS, and this is {sys.platform}: run this on the Mac")
    part = PARTS.get(args.part) or SECTIONS[args.part]
    pdf = part_pdf(part.pdf)
    if pdf is None:
        sys.exit(f"[Kho tàng tục ngữ] No PDF '{part.pdf}' for --{args.part}: copy it into the book's folder first")
    doc, turned = open_pdf(pdf, part), dict(part.turned_pages)
    n_pages = len(doc)
    first, last = part.proverb_pages
    only = page_set(args.pages, n_pages) if args.pages else list(range(first, min(last, n_pages) + 1))
    only = [page for page in only if page not in part.skipped_pages]

    store = os.path.join(STORE_DIR, args.part)
    lines_dir, vision_dir =os.path.join(store, "lines"), os.path.join(store, "vision")
    os.makedirs(lines_dir, exist_ok=True)
    os.makedirs(vision_dir, exist_ok=True)
    pdf_sha1, stamp = file_sha1(pdf), vision_stamp()
    print(f"[Kho tàng tục ngữ] {args.part} ({part.pdf}): {len(only)} page(s) "
          f"({'--pages ' + args.pages if args.pages else f'proverb pages {first}-{last}'}); store {store}")

    def is_current(page):
        found = saved_lines(lines_dir, page, pdf_sha1, turned.get(page, 0))
        record = read_result(vision_dir, page_key(page))
        return (found is not None and vision_problem(record, found, pdf_sha1) is None
                and record.get("stamp") == stamp)

    todo = [page for page in only if not is_current(page)]
    print(f"[Kho tàng tục ngữ] {len(todo)} page(s) to read with Vision, {len(only) - len(todo)} already current")
    if todo:
        with tempfile.TemporaryDirectory() as folder:
            reader = VisionReader(folder)
            started = time.monotonic()
            try:
                for count, page in enumerate(todo, 1):
                    key = page_key(page)
                    began = time.monotonic()
                    result = {"task": key, "phase": "vision", "pdf_sha1": pdf_sha1, "stamp": stamp}
                    try:
                        found = find_lines(doc, page)
                        write_json(os.path.join(lines_dir, f"{key}.json"),
                                   {"pdf_sha1": pdf_sha1, "turned": turned.get(page, 0), **found})
                        result.update(status="ok", error=None, **read_page(reader, doc, page, found, folder))
                    except Exception as e:
                        result.update(status="failed", error=f"{type(e).__name__}: {e}", lines=[], unmatched=[])
                        print(f"  [{count}/{len(todo)}] {key}: failed: {result['error'][:200]}")
                    result["elapsed_s"] = round(time.monotonic() - began, 2)
                    write_json(os.path.join(vision_dir, f"{key}.json"), result)
                    if count % 10 == 0 or count == len(todo):
                        print(f"  [{count}/{len(todo)}] {time.monotonic() - started:.0f}s")
            finally:
                reader.close()

    records = {page: read_result(vision_dir, page_key(page)) for page in only}
    failed = [page for page in only if records[page]["status"] != "ok"]
    read_ok = sum(1 for page in todo if page not in failed)
    disputed, total = disputed_share(records[page] for page in only if page not in failed)
    share = f"{100 * disputed / total:.1f}%" if total else "none"
    print(f"[Kho tàng tục ngữ] {read_ok} page(s) read, {len(failed)} failed"
          f"{': ' + ', '.join(page_key(page) for page in failed) if failed else ''}")
    print(f"[Kho tàng tục ngữ] Disputed Syllables: {share} ({disputed} of {total}, in lines with both reads)")
    relative = os.path.relpath(store)
    print("[Kho tàng tục ngữ] To copy the reads to the cluster:")
    print(f"rsync -a {relative}/lines {relative}/vision <user>@<login node>:<repo>/{relative}/")


if __name__ == "__main__":
    main()
