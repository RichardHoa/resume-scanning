#!/usr/bin/env python3
"""
Review server for one Kho tàng tục ngữ người Việt PDF Part's store. src/khotangtucngu/cli.py copies this file and web/
(the page: index.html, style.css, app.js), their single master copy, into the store on every run. It uses the Python
standard library only, so a store copied to any machine can be reviewed:

    python3 serve.py [--port 8000]

serves the store on http://127.0.0.1:<port>/ and opens it in a browser: each page's scan (pages/) on the left, its
verbatim Proverb Entries (entries.json) on the right with its Warnings (warnings.json). Each review record is appended
to review.jsonl here, one JSON line with its time. No run rebuilds or deletes review.jsonl, and nothing else in the
store is changed. If the store can't be written, the page is read-only and says so.

A review record names the model's Proverb Entry by `name` ("C 484"), and is one of (export.py reads the Fixes):

  {"type": "check", "name", "checked": true | false, "answer_sha1"}   the entry is (or is no longer) checked
  {"type": "fix", "name", "answer_sha1", "entry"}                      a Fix: `entry` is a full replacement Proverb
                                                                       Entry, in the shape of entries.json
  {"type": "fix", "name", "entry": null}                               the entry's Fix is dropped

`answer_sha1` is {PDF page: answer hash} of every page the entry is printed on, as entries.json had them when the
record was made. A later record of the same type and name replaces an earlier one. A check or a Fix is stale once a
page's hash in its `answer_sha1` no longer matches entries.json: it was made against an answer a rerun has since
changed, so the entry counts as unchecked, and the Fix isn't applied until it is saved again or dropped.
"""
import argparse
import json
import os
import threading
import webbrowser
from datetime import datetime
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer

HERE = os.path.dirname(os.path.abspath(__file__))
REVIEW = os.path.join(HERE, "review.jsonl")
INDEX = os.path.join(HERE, "web", "index.html")
RECORD_TYPES = ("check", "fix")
_append_lock = threading.Lock()


def writable():
    """Whether review.jsonl can be appended to (or made)."""
    return os.access(REVIEW, os.W_OK) if os.path.exists(REVIEW) else os.access(HERE, os.W_OK)


def check_record(record):
    """Raises ValueError unless `record` is a review record of the shape in this file's docstring."""
    if not isinstance(record, dict) or record.get("type") not in RECORD_TYPES:
        raise ValueError("not a check or a Fix")
    if not isinstance(record.get("name"), str):
        raise ValueError("no entry name")
    dropped = record["type"] == "fix" and record.get("entry") is None
    if not dropped and not (isinstance(record.get("answer_sha1"), dict) and record["answer_sha1"]):
        raise ValueError("no answer hashes")
    if record["type"] == "check" and not isinstance(record.get("checked"), bool):
        raise ValueError("a check is neither checked nor unchecked")
    if record["type"] == "fix" and not dropped and not isinstance(record.get("entry"), dict):
        raise ValueError("a Fix holds no Proverb Entry")


class Handler(SimpleHTTPRequestHandler):
    """Serves the review page at / (web/index.html, told whether the store can be written), the store's files, and
    POST /review."""

    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            with open(INDEX, encoding="utf-8") as f:
                page = f.read().replace("__WRITABLE__", "true" if writable() else "false")
            self._send(200, "text/html; charset=utf-8", page.encode("utf-8"))
        elif path == "/review.jsonl" and not os.path.exists(REVIEW):
            self._send(200, "application/x-ndjson", b"")
        else:
            super().do_GET()

    def do_POST(self):
        if self.path != "/review":
            return self._send(404, "text/plain; charset=utf-8", b"not found")
        if not writable():
            return self._send(403, "text/plain; charset=utf-8", b"this store is read-only")
        try:
            record = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
            check_record(record)
        except ValueError as e:
            return self._send(400, "text/plain; charset=utf-8", str(e).encode("utf-8"))
        record["time"] = datetime.now().astimezone().isoformat(timespec="seconds")
        try:
            with _append_lock, open(REVIEW, "a", encoding="utf-8") as f:
                f.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError as e:
            return self._send(403, "text/plain; charset=utf-8", str(e).encode("utf-8"))
        self._send(200, "application/json", json.dumps(record, ensure_ascii=False).encode("utf-8"))

    def end_headers(self):
        # entries.json, warnings.json and the page images are rebuilt by a rerun, and review.jsonl grows
        self.send_header("Cache-Control", "no-store")
        super().end_headers()

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
    if not os.path.exists(os.path.join(HERE, "entries.json")):
        raise SystemExit(f"No entries.json in {HERE}: run serve.py from a store the CLI has written")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), partial(Handler, directory=HERE))
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Reviewing {HERE} at {url} (Ctrl-C to stop)")
    if not writable():
        print("This store can't be written: the page is read-only, and checks and Fixes can't be saved")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
