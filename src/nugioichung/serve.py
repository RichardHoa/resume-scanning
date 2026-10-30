#!/usr/bin/env python3
"""
Review viewer for one Nữ Giới Chung run folder. src/nugioichung/viewer.py copies this file and web/ (the page:
index.html, style.css, app.js), their single master copy, into every run folder. It uses the Python standard library
only, so a run folder copied to any machine can be reviewed:

    python3 serve.py [--port 8000]

serves this folder on http://127.0.0.1:<port>/ and opens it in a browser: the Issue's text on the left (viewer.json),
its pages on the right (pages/), each stretch of text highlighted where it is printed and every Warning boxed. Each
Resolution of a Warning and each Correction of the text is appended to review.jsonl here, one JSON line with its
time; when the page opens, a later line on the same Warning or block replaces an earlier one. Nothing else in the
folder is ever changed. If the folder can't be written, the viewer is read-only and says so.
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
ENTRY_TYPES = ("resolution", "correction")
_append_lock = threading.Lock()


def writable():
    """Whether review.jsonl can be appended to (or made)."""
    return os.access(REVIEW, os.W_OK) if os.path.exists(REVIEW) else os.access(HERE, os.W_OK)


class Handler(SimpleHTTPRequestHandler):
    """Serves the viewer page at / (web/index.html, told whether the folder can be written), the folder's files, and
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
            return self._send(403, "text/plain; charset=utf-8", b"this folder is read-only")
        try:
            entry = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)))
            if not isinstance(entry, dict) or entry.get("type") not in ENTRY_TYPES:
                raise ValueError("not a Resolution or Correction")
        except ValueError as e:
            return self._send(400, "text/plain; charset=utf-8", str(e).encode("utf-8"))
        entry["time"] = datetime.now().astimezone().isoformat(timespec="seconds")
        try:
            with _append_lock, open(REVIEW, "a", encoding="utf-8") as f:
                f.write(json.dumps(entry, ensure_ascii=False) + "\n")
        except OSError as e:
            return self._send(403, "text/plain; charset=utf-8", str(e).encode("utf-8"))
        self._send(200, "application/json", json.dumps(entry, ensure_ascii=False).encode("utf-8"))

    def end_headers(self):
        # viewer.json and the page images are rebuilt by a continued run, and review.jsonl grows
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
    parser = argparse.ArgumentParser(description="Review this Nữ Giới Chung run folder in a browser")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    if not os.path.exists(os.path.join(HERE, "viewer.json")):
        raise SystemExit(f"No viewer.json in {HERE}: run serve.py from a run folder the CLI has written")
    server = ThreadingHTTPServer(("127.0.0.1", args.port), partial(Handler, directory=HERE))
    url = f"http://127.0.0.1:{args.port}/"
    print(f"Reviewing {HERE} at {url} (Ctrl-C to stop)")
    if not writable():
        print("This folder can't be written: the viewer is read-only, and Resolutions and Corrections can't be saved")
    webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
