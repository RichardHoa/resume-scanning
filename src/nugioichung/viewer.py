"""
The review viewer's files in a run folder: each page's image in pages/, viewer.json (the Issue's Items with the place
on a page each stretch of their text was printed, each page's Regions and Strips with their printed lines and
requests, and every Warning), and serve.py with web/ (the page's HTML, CSS and JS), copied from this package's single
master copy, which serves them as one page (`python3 serve.py`). All of it is rebuilt from the saved answers on every run; review.jsonl, which serve.py
writes, is never touched.
"""
import os
import shutil

from src.nugioichung.assembly import item_byline, item_heading, locate, pages_label
from src.nugioichung.pages import page_image
from src.nugioichung.regions import KINDS, page_key
from src.providers.vlm_requests import write_json

HERE = os.path.dirname(os.path.abspath(__file__))
SERVE = os.path.join(HERE, "serve.py")
WEB = os.path.join(HERE, "web")


def _rel(run_dir, path):
    """`path` relative to the run folder, as a URL path."""
    return os.path.relpath(path, run_dir).replace(os.sep, "/")


def request_entry(run_dir, results_dir, name, key, status):
    """A request as the viewer shows it: its pass `name`, its status, its saved result, and the folder holding what
    was sent (its image and prompts) with the files in it."""
    folder = os.path.join(results_dir, key)
    return {"pass": name, "status": status, "result": _rel(run_dir, os.path.join(results_dir, f"{key}.json")),
            "folder": _rel(run_dir, folder), "files": sorted(os.listdir(folder)) if os.path.isdir(folder) else []}


def _stretch(cuts, text, place):
    if place is None:
        return {"text": text}
    page, box = locate(cuts, place)
    return {"text": text, "cut": place[0], "line": place[1], "page": page, "box": box}


def _blocks(cuts, blocks):
    out, counts = [], {"paragraph": 0, "footnote": 0}
    for block in blocks:
        counts[block["kind"]] += 1
        out.append({"id": f"{block['kind'][0]}{counts[block['kind']]}", "kind": block["kind"], "label": block["label"],
                    "text": block["text"].text,
                    "stretches": [_stretch(cuts, t, p) for t, p in block["text"].stretches()]})
    return out


def _region(r, reads, requests):
    cuts = []
    for cut in r.cuts:
        read, _ = reads.get(cut.key, (None, None))
        cuts.append({"key": cut.key, "label": cut.label, "box": cut.box, "strip": cut.strip,
                     "lines": [line._asdict() for line in cut.lines],
                     "read_lines": len(read["lines"]) if read else None,
                     "matched": read["printed"] is not None if read else None,
                     "requests": requests.get(cut.key, [])})
    return {"key": r.key, "n": r.n, "kind": r.kind, "title": r.title, "continues": r.continues, "box": r.box,
            "layout_box": r.layout_box, "cuts": cuts}


def write_viewer(run_dir, doc, title, pages, layouts, reads, requests, items, blocks, warnings, cuts):
    """
    Writes the viewer's files into `run_dir` for `pages` (PDF page numbers). `layouts`: {pdf page: PageLayout} of the
    pages that have one; `reads`: {cut key: (checked read answer or None, why)}; `requests`: {cut key: its requests,
    from `request_entry`}; `items` and their `blocks` from assembly; `warnings`: every Warning of the run; `cuts`:
    {cut key: Cut}.
    """
    os.makedirs(os.path.join(run_dir, "pages"), exist_ok=True)
    shown = []
    for page in pages:
        image = os.path.join(run_dir, "pages", f"{page_key(page)}.png")
        with open(image, "wb") as f:
            f.write(page_image(doc, page))
        layout = layouts.get(page)
        shown.append({"page": page, "printed": layout.printed_page if layout else "", "laid_out": layout is not None,
                      "image": _rel(run_dir, image),
                      "regions": [_region(r, reads, requests) for r in (layout.regions if layout else [])]})
    write_json(os.path.join(run_dir, "viewer.json"), {
        "title": title,
        "kinds": {k: {"label": kind.label, "colour": "rgb({}, {}, {})".format(*kind.colour)}
                  for k, kind in KINDS.items()},
        "pages": shown,
        "items": [{"n": n, "kind": item["kind"], "title": item["title"], "section": item["section"],
                   "author": item["author"], "pages": pages_label(item["pages"]), "heading": item_heading(item),
                   "byline": item_byline(item), "blocks": _blocks(cuts, item_blocks)}
                  for n, (item, item_blocks) in enumerate(zip(items, blocks), 1)],
        "warnings": warnings,
    })
    shutil.copyfile(SERVE, os.path.join(run_dir, "serve.py"))
    shutil.copytree(WEB, os.path.join(run_dir, "web"), dirs_exist_ok=True)
