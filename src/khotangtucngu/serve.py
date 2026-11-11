"""
Review server for one Kho tàng tục ngữ người Việt PDF Part's store. src/khotangtucngu/cli.py copies this file, web/
(the page: index.html, style.css, app.js) and khotangtucngu/ (assembly.py, citations.py, diacritics.py, review.py),
their single master copies, into the store on every run. It uses the Python standard library only, so a store copied to any machine
can be reviewed:

    python3 serve.py [--port 8000]

serves the store on http://127.0.0.1:<port>/ and opens it in a browser: each page's scan (pages/) on the left with its
Entry Spans drawn on it, or the page as the layout request saw it with its Line Numbers (layout/), and its Proverb
Entries on the right with their Warnings and their Citations matched to the 63 Sources (sources.json). The developer
edits or confirms an Entry Span where they choose to; nobody checks every entry. Either way it becomes a Confirmed Span,
its full detail appended to review.jsonl here with its time (see review.py for its lines). No run rebuilds or deletes
review.jsonl, and nothing else in the store is changed. This server can't tell whether a Confirmed Span was made from
another PDF, as it has no PDF: a run stops on that. If the store can't be written, the page is read-only and says so.

Besides the store's files:

  GET  /assembled     the Proverb Entries, Warnings and pages rebuilt from answers.json with the review log (their Blocks
                      checked against the OCR Readings in readings.json and the reads flagged in agreed.json), each
                      page's Blocks and spans, and every Confirmed Span
  POST /preview       {"page", "band", "blocks"}: the entries and Warnings of that page were that span's Blocks those, the
                      Warnings raised whether or not the span is already confirmed
  POST /review        one of:
                      {"type": "confirmed", "page", "band", "blocks"}: the span confirmed, with those Blocks (null keeps
                      the ones it has); "page_complete" is appended too if it was the page's last
                      {"type": "unconfirmed", "page", "band"}: the Confirmed Span undone
                      {"type": "printed_page", "page", "printed_page"}: the page's number set or confirmed (null undoes it)
"""
import argparse
import json
import os
import threading
import webbrowser
from datetime import datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from khotangtucngu.assembly import INK_OUTSIDE, PAGE_MISSING, priority_first
from khotangtucngu.citations import Abbreviations
from khotangtucngu.review import (
    REVIEW_LOG, band_problem, blocks_differ, blocks_problem, lay_confirmed, read_log, rebuild
)

HERE = os.path.dirname(os.path.abspath(__file__))
REVIEW = os.path.join(HERE, REVIEW_LOG)
INDEX = os.path.join(HERE, "web", "index.html")
_append_lock = threading.Lock()
_cache, _cache_lock = {}, threading.Lock()


def writable():
    """Whether review.jsonl can be appended to (or made)."""
    return os.access(REVIEW, os.W_OK) if os.path.exists(REVIEW) else os.access(HERE, os.W_OK)


def _read(name, parse=json.load):
    """A store file parsed, read again only once a rerun has rewritten it. Callers never change what it returns."""
    path = os.path.join(HERE, name)
    mtime = os.stat(path).st_mtime_ns
    with _cache_lock:
        if name in _cache and _cache[name][0] == mtime:
            return _cache[name][1]
    with open(path, encoding="utf-8") as f:
        data = parse(f)
    with _cache_lock:
        _cache[name] = (mtime, data)
    return data


def _answers():
    """The page answers by PDF page, a new dict each time (the answers in it are shared, never changed)."""
    return {int(page): answer for page, answer in _read("answers.json").items()}


def _readings():
    """Each page's OCR Readings joined, by PDF page, which its Blocks are checked against for Diacritic
    Disagreements."""
    return {int(page): reading for page, reading in _read("readings.json").items()}


def _flagged():
    """Each page's two reads with their Agreed Syllables flagged, by PDF page, which its Blocks are checked against for
    Model Edits."""
    return {int(page): flagged for page, flagged in _read("agreed.json").items()}


def _page_of(request):
    """The PDF page with an answer that `request` names."""
    page = request.get("page") if isinstance(request, dict) else None
    if not isinstance(page, int) or page not in _answers():
        raise ValueError(f"PDF page {page} has no answer")
    return page


def _span_line(page, answer, records, request):
    """
    The "confirmed" line of the span of `request`, on `page` with its `answer` and `records` (its Confirmed Spans' lines),
    with the Blocks `request` gives, or the ones it has. Confirming a span again carries its model's Blocks forward. A
    span cut across a band can't be confirmed: its lines are partly the Confirmed Span's.
    """
    why = band_problem(request.get("band"))
    if why:
        raise ValueError(why)
    laid = lay_confirmed(answer, records)
    span = next((s for s in laid["spans"] if s["band"] == request["band"]), None)
    if span is None:
        raise ValueError(f"PDF page {page} has no Entry Span at pixel rows {request['band']}")
    if span["overlap"]:
        raise ValueError(f"the Entry Span of Line Numbers {span['first']}-{span['last']} overlaps a Confirmed Span: "
                         f"run the page with the latest review log first")
    blocks = request.get("blocks")
    if blocks is None:
        blocks = laid["blocks"][span["blocks"][0]:span["blocks"][1]]
    why = blocks_problem(blocks)
    if why:
        raise ValueError(why)
    return {"type": "confirmed", "page": page, "pdf_sha1": answer["pdf_sha1"], "band": span["band"],
            "first": span["first"], "last": span["last"], "leading": span["leading"], "crop": span["box"],
            "readings": span["readings"], "crop_reads": span["crop_reads"], "blocks": blocks,
            "model_blocks": span["model_blocks"], "edited": blocks_differ(blocks, span["model_blocks"])}


def assembled(preview=None):
    """The store rebuilt with its review log; with `preview` ({"page", "band", "blocks"}), as if that span's Blocks were
    those, and raising their Warnings."""
    answers, log = _answers(), read_log(HERE)
    if preview:
        page = preview["page"]
        records = log["confirmed"].get(page, [])
        line = _span_line(page, answers[page], records, preview)
        log["confirmed"][page] = [r for r in records if r["band"] != line["band"]] + [{**line, "preview": True}]
    abbreviations = Abbreviations(list(_read("sources.json")))
    part = _read("entries.json", json.load)
    entries, warnings, pages, laid = rebuild(answers, log, abbreviations, part["book_page_offset"], _readings(),
                                             _flagged(), part["skipped_pages"])
    for p in pages:
        p["blocks"] = laid[p["pdf"]]["blocks"]
    # A failed or missing page has no answer, and ink outside the found lines is no Block's, so no Confirmed Span can
    # change their Warnings
    missing = [w for w in _read("warnings.json") if w["kind"] in (PAGE_MISSING, INK_OUTSIDE)]
    warnings = priority_first(missing + warnings)
    confirmed = [{k: r.get(k) for k in ("page", "band", "first", "last", "edited", "time")}
                 for records in log["confirmed"].values() for r in records]
    return {"entries": entries, "warnings": warnings, "pages": pages, "confirmed": confirmed}


def preview(request):
    """The entries and Warnings of a page were one span's Blocks those of `request`."""
    page = _page_of(request)
    if request.get("blocks") is None:
        raise ValueError("no Blocks")
    view = assembled(request)
    return {"entries": [e for e in view["entries"] if page in e["pdf_pages"]],
            "warnings": [w for w in view["warnings"] if w["page"] == page]}


def review_lines(request):
    """The lines of the review log that `request`, a POST /review, appends, without their time."""
    page, kind = _page_of(request), request.get("type")
    if kind == "printed_page":
        number = request.get("printed_page")
        if number is not None and not isinstance(number, str):
            raise ValueError("the printed page number is not text")
        return [{"type": kind, "page": page, "printed_page": number}]
    records = read_log(HERE)["confirmed"].get(page, [])
    if kind == "unconfirmed":
        if not any(r["band"] == request.get("band") for r in records):
            raise ValueError(f"PDF page {page} has no Confirmed Span at pixel rows {request.get('band')}")
        return [{"type": kind, "page": page, "band": request["band"]}]
    if kind != "confirmed":
        raise ValueError(f"no line of the review log has type {kind!r}")
    answer = _answers()[page]
    line = _span_line(page, answer, records, request)
    lines = [line]
    after = lay_confirmed(answer, [r for r in records if r["band"] != line["band"]] + [line])
    if all(span["confirmed"] for span in after["spans"]):
        lines.append({"type": "page_complete", "page": page, "printed_page": answer["printed_page"],
                      "body_start": answer["body_start"]})
    return lines


class Handler(SimpleHTTPRequestHandler):
    """Serves the review page at / (web/index.html, told whether the store can be written), the store's files,
    /assembled, POST /preview and POST /review."""

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            with open(INDEX, encoding="utf-8") as f:
                page = f.read().replace("__WRITABLE__", "true" if writable() else "false")
            self._send(200, "text/html; charset=utf-8", page.encode("utf-8"))
        elif path == "/assembled":
            self._send_json(assembled())
        else:
            super().do_GET()

    def do_POST(self):
        if self.path not in ("/review", "/preview"):
            return self._send(404, "text/plain; charset=utf-8", b"not found")
        try:
            request = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
            if self.path == "/preview":
                return self._send_json(preview(request))
            lines = review_lines(request)
        except ValueError as e:
            return self._send(400, "text/plain; charset=utf-8", str(e).encode("utf-8"))
        if not writable():
            return self._send(403, "text/plain; charset=utf-8", b"this store is read-only")
        time = datetime.now().astimezone().isoformat(timespec="seconds")
        for line in lines:
            line["time"] = time
        try:
            with _append_lock, open(REVIEW, "a", encoding="utf-8") as f:
                f.write("".join(json.dumps(line, ensure_ascii=False) + "\n" for line in lines))
        except OSError as e:
            return self._send(403, "text/plain; charset=utf-8", str(e).encode("utf-8"))
        self._send_json(lines[0])

    def end_headers(self):
        # answers.json, entries.json, warnings.json and the page images are rebuilt by a rerun
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

    def _send_json(self, data):
        self._send(200, "application/json", json.dumps(data, ensure_ascii=False).encode("utf-8"))

    def _send(self, code, content_type, body):
        self.send_response(code)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, format, *args):
        if not str(args[1] if len(args) > 1 else "").startswith(("2", "3")):
            super().log_message(format, *args)


def main():
    parser = argparse.ArgumentParser(description="Review this Kho tàng tục ngữ store in a browser")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if not os.path.exists(os.path.join(HERE, "answers.json")):
        raise SystemExit(f"No answers.json in {HERE}: run serve.py from a store the CLI has written")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), partial(Handler, directory=HERE))
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Reviewing {HERE} at {url} (Ctrl-C to stop)")
    if not writable():
        print("This store can't be written: the page is read-only, and nothing can be confirmed")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
