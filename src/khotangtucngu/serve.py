"""
Review server for one Kho tàng tục ngữ người Việt PDF Part's store. src/khotangtucngu/cli.py copies this file, web/
(the page: index.html, style.css, app.js) and khotangtucngu/ (assembly.py, citations.py, review.py), their single
master copies, into the store on every run. It uses the Python standard library only, so a store copied to any machine
can be reviewed:

    python3 serve.py [--port 8000]

serves the store on http://127.0.0.1:<port>/ and opens it in a browser: each page's scan (pages/) on the left, its
Proverb Entries on the right with their Warnings and their Citations matched to the 63 Sources (sources.json). The
developer edits whatever they see is wrong; nobody checks every entry. Each edit saves a Fix of the page, the corrected
Blocks of its answer, appended to review.jsonl here with its time (see review.py for its lines). No run rebuilds or
deletes review.jsonl, and nothing else in the store is changed. If the store can't be written, the page is read-only
and says so.

Besides the store's files:

  GET  /assembled     the Proverb Entries, Warnings and pages rebuilt from answers.json with the Fixes that are not
                      stale, the Fixes by PDF page, and the pages whose Fix is applied and stale
  POST /preview       {"page", "printed_page", "blocks"}: the entries and Warnings of that page were it so
  POST /review        a Fix line, appended to review.jsonl with its time and the hash of its page's current answer

entries.json and warnings.json stay the model's, for the page's "as transcribed" view.
"""
import argparse
import json
import os
import threading
import webbrowser
from datetime import datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

from khotangtucngu.assembly import PAGE_MISSING, answer_sha1
from khotangtucngu.citations import Abbreviations
from khotangtucngu.review import REVIEW_LOG, fix_problem, read_fixes, rebuild

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
    """The model's page answers by PDF page, a new dict each time (the answers in it are shared, never changed)."""
    return {int(page): answer for page, answer in _read("answers.json").items()}


def assembled(page=None, printed_page=None, blocks=None):
    """The store rebuilt with its Fixes; with `page`, as if that page's printed number and Blocks were `printed_page`
    and `blocks`."""
    answers, fixes = _answers(), read_fixes(HERE)
    abbreviations = Abbreviations(list(_read("sources.json")))
    if page is not None:
        answers[page] = {**answers.get(page, {}), "printed_page": printed_page, "blocks": blocks}
        fixes.pop(page, None)
    offset = _read("entries.json", lambda f: json.load(f)["book_page_offset"])
    entries, warnings, pages, applied, stale = rebuild(answers, fixes, abbreviations, offset)
    # A failed or missing page has no answer, so no Fix can change its Warning
    missing = [w for w in _read("warnings.json") if w["kind"] == PAGE_MISSING]
    warnings = sorted(missing + warnings, key=lambda w: w["page"])
    return {"entries": entries, "warnings": warnings, "pages": pages, "applied": applied, "stale": stale,
            "fixes": {str(p): f for p, f in fixes.items()}}


def preview(request):
    """The entries and Warnings of a page were its printed number and Blocks those of `request`."""
    page = request.get("page") if isinstance(request, dict) else None
    why = fix_problem({**request, "type": "fix", "answer_sha1": "preview"}) if page is not None else "no PDF page"
    if why or request.get("blocks") is None:
        raise ValueError(why or "no Blocks")
    view = assembled(page, request["printed_page"], request["blocks"])
    return {"entries": [e for e in view["entries"] if page in e["pdf_pages"]],
            "warnings": [w for w in view["warnings"] if w["page"] == page]}


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
            record = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
            if self.path == "/preview":
                return self._send_json(preview(record))
            if isinstance(record, dict) and record.get("blocks") is not None:
                # Made against the page's answer now, whatever the page loaded before a rerun
                answer = _answers().get(record.get("page"))
                if answer is None:
                    raise ValueError(f"PDF page {record.get('page')} has no answer to fix")
                record["answer_sha1"] = answer_sha1(answer)
            why = fix_problem(record)
            if why:
                raise ValueError(why)
        except ValueError as e:
            return self._send(400, "text/plain; charset=utf-8", str(e).encode("utf-8"))
        if not writable():
            return self._send(403, "text/plain; charset=utf-8", b"this store is read-only")
        record["time"] = datetime.now().astimezone().isoformat(timespec="seconds")
        try:
            with _append_lock, open(REVIEW, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as e:
            return self._send(403, "text/plain; charset=utf-8", str(e).encode("utf-8"))
        self._send_json(record)

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
        print("This store can't be written: the page is read-only, and Fixes can't be saved")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
