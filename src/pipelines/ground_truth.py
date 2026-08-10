"""
Ground Truth Benchmark & HTTP Validation Server Pipeline
"""
import os
import json
import shutil
import sys

# Ensure repository root is in sys.path for 'src' package imports
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import re
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler
from src.core.config import PDF_DIR, OUTPUT_DIR as JSON_DIR, APPROVED_DIR, ROOT_DIR as WORKSPACE_DIR

PORT = 8000

HTML_CONTENT = r"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Resume Ground Truth Validator</title>
    <link rel="preconnect" href="https://fonts.googleapis.com">
    <link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
    <link href="https://fonts.googleapis.com/css2?family=JetBrains+Mono:wght@400;500&family=Outfit:wght@400;500;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --bg-main: #0f172a;
            --bg-card: #1e293b;
            --bg-editor: #090d16;
            --text-main: #f8fafc;
            --text-muted: #94a3b8;
            --accent: #6366f1;
            --accent-hover: #4f46e5;
            --success: #10b981;
            --success-hover: #059669;
            --warning: #f59e0b;
            --danger: #ef4444;
            --border: #334155;
        }

        * { box-sizing: border-box; margin: 0; padding: 0; }
        body {
            font-family: 'Outfit', sans-serif;
            background-color: var(--bg-main);
            color: var(--text-main);
            height: 100vh;
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }
        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 1rem 2rem;
            background-color: var(--bg-card);
            border-bottom: 1px solid var(--border);
            height: 70px;
            z-index: 10;
        }
        .logo-title {
            font-size: 1.25rem;
            font-weight: 700;
            background: linear-gradient(135deg, #a5b4fc, #6366f1);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }
        main { display: flex; flex: 1; height: calc(100vh - 70px); overflow: hidden; }
        .pane { flex: 1; display: flex; flex-direction: column; height: 100%; overflow: hidden; }
        .pane-left { border-right: 1px solid var(--border); background-color: #111827; }
        iframe { width: 100%; height: 100%; border: none; }
    </style>
</head>
<body>
    <header>
        <div class="logo-title">Resume Ground Truth Validator</div>
    </header>
    <main>
        <div class="pane pane-left">
            <iframe id="pdfFrame" src="about:blank"></iframe>
        </div>
        <div class="pane">
            <pre id="jsonPreview" style="padding:1rem; color:#fff; overflow:auto;"></pre>
        </div>
    </main>
</body>
</html>
"""


def natural_sort_key(s: str) -> list:
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]


class GroundTruthHandler(BaseHTTPRequestHandler):
    def send_json(self, data: dict, status: int = 200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.end_headers()
        self.wfile.write(json.dumps(data, ensure_ascii=False).encode('utf-8'))

    def do_GET(self):
        path = urllib.parse.unquote(self.path)

        if path == "/" or path == "/index.html":
            self.send_response(200)
            self.send_header('Content-Type', 'text/html; charset=utf-8')
            self.end_headers()
            self.wfile.write(HTML_CONTENT.encode('utf-8'))
            return

        elif path == "/api/files":
            if not os.path.exists(JSON_DIR):
                self.send_json({"files": []})
                return
            
            json_files = sorted([f for f in os.listdir(JSON_DIR) if f.endswith('.json')], key=natural_sort_key)
            files_list = []
            
            for jf in json_files:
                base_name = os.path.splitext(jf)[0]
                pdf_file = None
                if os.path.exists(PDF_DIR):
                    for f in os.listdir(PDF_DIR):
                        if os.path.splitext(f)[0] == base_name:
                            pdf_file = f
                            break
                files_list.append({
                    "json": jf,
                    "pdf": pdf_file or ""
                })
            self.send_json({"files": files_list})
            return

        elif path.startswith("/api/json/"):
            filename = os.path.basename(path[len("/api/json/"):])
            filepath = os.path.join(JSON_DIR, filename)
            
            if os.path.exists(filepath):
                self.send_response(200)
                self.send_header('Content-Type', 'application/json; charset=utf-8')
                self.end_headers()
                with open(filepath, 'rb') as f:
                    self.wfile.write(f.read())
            else:
                self.send_error(404, "JSON file not found")
            return

        elif path.startswith("/pdf/"):
            filename = os.path.basename(path[len("/pdf/"):])
            filepath = os.path.join(PDF_DIR, filename)
            
            if os.path.exists(filepath):
                ext = os.path.splitext(filename)[1].lower()
                content_type = 'application/pdf' if ext == '.pdf' else 'application/octet-stream'
                self.send_response(200)
                self.send_header('Content-Type', content_type)
                self.send_header('Content-Length', str(os.path.getsize(filepath)))
                self.end_headers()
                with open(filepath, 'rb') as f:
                    shutil.copyfileobj(f, self.wfile)
            else:
                self.send_error(404, "PDF file not found")
            return

        else:
            self.send_error(404, "Not Found")

    def do_POST(self):
        path = urllib.parse.unquote(self.path)

        if path.startswith("/api/approve/"):
            filename = os.path.basename(path[len("/api/approve/"):])
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length).decode('utf-8')
            
            try:
                parsed_json = json.loads(body)
                os.makedirs(APPROVED_DIR, exist_ok=True)
                approved_path = os.path.join(APPROVED_DIR, filename)
                
                with open(approved_path, 'w', encoding='utf-8') as f:
                    json.dump(parsed_json, f, ensure_ascii=False, indent=2)
                
                original_path = os.path.join(JSON_DIR, filename)
                if os.path.exists(original_path):
                    os.remove(original_path)
                
                self.send_json({"status": "success", "message": f"Approved and moved {filename}"})
            except json.JSONDecodeError as e:
                self.send_json({"status": "error", "message": f"Invalid JSON syntax: {str(e)}"}, 400)
            except Exception as e:
                self.send_json({"status": "error", "message": str(e)}, 500)
            return

        else:
            self.send_error(404, "Not Found")


def run():
    print(f"Starting Ground Truth Validator Server on port {PORT}...")
    print(f"Workspace Directory: {WORKSPACE_DIR}")
    print(f"PDF Source Directory: {PDF_DIR}")
    print(f"JSON Source Directory: {JSON_DIR}")
    print(f"Approved JSON Target: {APPROVED_DIR}")
    print(f"Open your browser and navigate to: http://localhost:{PORT}")
    
    server_address = ('', PORT)
    httpd = HTTPServer(server_address, GroundTruthHandler)
    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\nShutting down server.")
        sys.exit(0)
