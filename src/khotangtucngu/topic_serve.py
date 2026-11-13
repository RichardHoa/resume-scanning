"""
Review server for the Topic Index's store (store/part-4-final-section/; vocabulary: the book's GLOSSARY).
src/khotangtucngu/topic_index.py copies this file into the store as serve.py, topic_web/ (the page: index.html,
style.css, app.js) as web/, and khotangtucngu/ (topics.py, with assembly.py, citations.py and diacritics.py), their
single master copies, on every run. It sits beside the Parts' serve.py, not inside it, and follows its conventions. It
uses the Python standard library only, so a store copied to any machine can be reviewed, with no PDF:

    python3 serve.py [--port 8000]

serves the store on http://127.0.0.1:<port>/ and opens it in a browser: each page's scan (pages/) with its Index Lines
tinted agreed, warned or confirmed, beside the index as assembled on that page, every Warning grouped by kind, and a
line panel with the line's crop and its three reads. The developer confirms or corrects the lines that need it; nobody
checks every line. Either way it becomes a Confirmed Line, appended whole to review.jsonl here with its time (see
topics.py for its lines). review.jsonl is never rewritten, and nothing else in the store is written. If the store can't
be written, the page is read-only and says so.

Besides the store's files:

  GET  /assembled     {"section", "topics", "warnings", "pages"}: the Topic Index rebuilt from answers.json with the
                      review log, checked against entry_names.json (topics.rebuild): each page's Index Lines with their
                      final values, state and Warnings, the assembled topics, and every Warning
  POST /preview       {"page", "band", "values"}: {"warnings"}, those of that page and the pages either side of it were
                      that line's values {"kind", "letter", "numbers", "text"}, whether or not it is already confirmed
  POST /review        one of:
                      {"type": "confirmed_line", "page", "band", "values"}: the line confirmed with those values (null
                      keeps the ones it has)
                      {"type": "unconfirmed_line", "page", "band"}: the Confirmed Line undone
"""
import argparse
import json
import os
import sys
import threading
import webbrowser
from datetime import datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

# Nothing in the store but review.jsonl is written: no __pycache__/ beside the copied code
sys.dont_write_bytecode = True
from khotangtucngu.topics import (  # noqa: E402
    REVIEW_LOG, VALUE_KEYS, band_problem, lay_confirmed, normal_values, preview, read_log, rebuild, values_problem
)

HERE = os.path.dirname(os.path.abspath(__file__))
REVIEW = os.path.join(HERE, REVIEW_LOG)
INDEX = os.path.join(HERE, "web", "index.html")
_append_lock = threading.Lock()
_cache, _cache_lock = {}, threading.Lock()


def writable():
    """Whether review.jsonl can be appended to (or made)."""
    return os.access(REVIEW, os.W_OK) if os.path.exists(REVIEW) else os.access(HERE, os.W_OK)


def _read(name):
    """A store file parsed, read again only once a rerun has rewritten it. Callers never change what it returns."""
    path = os.path.join(HERE, name)
    mtime = os.stat(path).st_mtime_ns
    with _cache_lock:
        if name in _cache and _cache[name][0] == mtime:
            return _cache[name][1]
    with open(path, encoding="utf-8") as f:
        data = json.load(f)
    with _cache_lock:
        _cache[name] = (mtime, data)
    return data


def _page_of(request):
    """The PDF page with an answer that `request` names, and its answer."""
    page = request.get("page") if isinstance(request, dict) else None
    answer = _read("answers.json")["pages"].get(str(page)) if isinstance(page, int) else None
    if answer is None:
        raise ValueError(f"PDF page {page} has no answer")
    return page, answer


def _line_at(page, answer, records, band):
    """The Index Line of `page` (its `answer`, with its Confirmed Lines' `records` laid over) at `band`."""
    why = band_problem(band)
    if why:
        raise ValueError(why)
    line = next((l for l in lay_confirmed(answer, records) if l["band"] == band), None)
    if line is None:
        raise ValueError(f"PDF page {page} has no Index Line at pixel rows {band}")
    return line


def _values_of(request, line):
    """The values `request` gives, checked, or the line's own if it gives none."""
    values = request.get("values")
    if values is None:
        values = {k: line[k] for k in VALUE_KEYS}
    why = values_problem(values)
    if why:
        raise ValueError(why)
    return normal_values(values)


def assembled():
    """The store rebuilt with its review log."""
    answers = _read("answers.json")
    return {"section": answers["section"], **rebuild(answers, read_log(HERE), _read("entry_names.json"))}


def preview_warnings(request):
    """The Warnings of a page and the pages either side were one line's values those of `request`."""
    page, answer = _page_of(request)
    log = read_log(HERE)
    line = _line_at(page, answer, log.get(page, []), request.get("band"))
    if request.get("values") is None:
        raise ValueError("no values")
    values = _values_of(request, line)
    return {"warnings": preview(_read("answers.json"), log, _read("entry_names.json"), page, line["band"], values)}


def review_line(request):
    """The line of the review log that `request`, a POST /review, appends, without its time."""
    page, answer = _page_of(request)
    kind, records = request.get("type"), read_log(HERE).get(page, [])
    if kind == "unconfirmed_line":
        if not any(r["band"] == request.get("band") for r in records):
            raise ValueError(f"PDF page {page} has no Confirmed Line at pixel rows {request.get('band')}")
        return {"type": kind, "page": page, "band": request["band"]}
    if kind != "confirmed_line":
        raise ValueError(f"no line of the review log has type {kind!r}")
    line = _line_at(page, answer, records, request.get("band"))
    values, model = _values_of(request, line), line["model"]
    # Confirming a line again carries its model's values forward, and its reads, shown should it fall on no Index Line
    # of a later run
    return {"type": kind, "page": page, "pdf_sha1": answer["pdf_sha1"], "band": line["band"], **values,
            "model": model, "edited": model is None or values != normal_values(model), "crop": line["crop"],
            "line_read": line["line_read"], "page_read": line["page_read"]}


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
                return self._send_json(preview_warnings(request))
            line = review_line(request)
        except ValueError as e:
            return self._send(400, "text/plain; charset=utf-8", str(e).encode("utf-8"))
        if not writable():
            return self._send(403, "text/plain; charset=utf-8", b"this store is read-only")
        line["time"] = datetime.now().astimezone().isoformat(timespec="seconds")
        try:
            with _append_lock, open(REVIEW, "a", encoding="utf-8") as f:
                f.write(json.dumps(line, ensure_ascii=False) + "\n")
        except OSError as e:
            return self._send(403, "text/plain; charset=utf-8", str(e).encode("utf-8"))
        self._send_json(line)

    def end_headers(self):
        # answers.json, entry_names.json and the page images are rebuilt by a rerun
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
    parser = argparse.ArgumentParser(description="Review this Kho tàng tục ngữ Topic Index store in a browser")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    for name in ("answers.json", "entry_names.json"):
        if not os.path.exists(os.path.join(HERE, name)):
            raise SystemExit(f"No {name} in {HERE}: run serve.py from a Topic Index store the CLI has written")
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
