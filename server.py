import os
import json
import shutil
import sys
import re
import urllib.parse
from http.server import HTTPServer, BaseHTTPRequestHandler

PORT = 8000
WORKSPACE_DIR = os.path.abspath(os.getcwd())
PDF_DIR = os.path.join(WORKSPACE_DIR, "Vietnamese-dataset", "CV")
JSON_DIR = os.path.join(WORKSPACE_DIR, "output_jsons")
APPROVED_DIR = os.path.join(WORKSPACE_DIR, "approved_jsons")

HTML_CONTENT = r"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Resume Ground Truth Validator</title>
    <!-- Outfit & JetBrains Mono Fonts -->
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

        * {
            box-sizing: border-box;
            margin: 0;
            padding: 0;
        }

        body {
            font-family: 'Outfit', sans-serif;
            background-color: var(--bg-main);
            color: var(--text-main);
            height: 100vh;
            display: flex;
            flex-direction: column;
            overflow: hidden;
        }

        /* Header Styles */
        header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 1rem 2rem;
            background-color: var(--bg-card);
            border-bottom: 1px solid var(--border);
            height: 70px;
            z-index: 10;
            box-shadow: 0 4px 6px -1px rgba(0, 0, 0, 0.1), 0 2px 4px -1px rgba(0, 0, 0, 0.06);
        }

        .logo-section {
            display: flex;
            align-items: center;
            gap: 12px;
        }

        .logo-title {
            font-size: 1.25rem;
            font-weight: 700;
            background: linear-gradient(135deg, #a5b4fc, #6366f1);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        .badge {
            background-color: var(--border);
            color: var(--text-muted);
            padding: 4px 8px;
            border-radius: 6px;
            font-size: 0.75rem;
            font-weight: 500;
        }

        .badge-success {
            background-color: rgba(16, 185, 129, 0.15);
            color: var(--success);
            border: 1px solid rgba(16, 185, 129, 0.3);
        }

        .badge-danger {
            background-color: rgba(239, 68, 68, 0.15);
            color: var(--danger);
            border: 1px solid rgba(239, 68, 68, 0.3);
        }

        .progress-section {
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 6px;
            min-width: 250px;
        }

        .progress-text {
            font-size: 0.875rem;
            font-weight: 500;
            color: var(--text-muted);
        }

        .progress-bar-container {
            width: 100%;
            height: 6px;
            background-color: var(--border);
            border-radius: 9999px;
            overflow: hidden;
        }

        .progress-bar-fill {
            height: 100%;
            width: 0%;
            background: linear-gradient(90deg, #6366f1, #10b981);
            border-radius: 9999px;
            transition: width 0.3s ease;
        }

        .controls {
            display: flex;
            gap: 12px;
            align-items: center;
        }

        .btn {
            display: flex;
            align-items: center;
            gap: 8px;
            padding: 8px 16px;
            font-family: inherit;
            font-size: 0.875rem;
            font-weight: 600;
            border-radius: 8px;
            border: 1px solid var(--border);
            background-color: var(--bg-main);
            color: var(--text-main);
            cursor: pointer;
            transition: all 0.2s ease;
        }

        .btn:hover:not(:disabled) {
            background-color: var(--border);
            transform: translateY(-1px);
        }

        .btn:active:not(:disabled) {
            transform: translateY(0);
        }

        .btn:disabled {
            opacity: 0.4;
            cursor: not-allowed;
        }

        .btn-primary {
            background-color: var(--accent);
            border-color: var(--accent);
        }

        .btn-primary:hover:not(:disabled) {
            background-color: var(--accent-hover);
            border-color: var(--accent-hover);
        }

        .btn-success {
            background-color: var(--success);
            border-color: var(--success);
        }

        .btn-success:hover:not(:disabled) {
            background-color: var(--success-hover);
            border-color: var(--success-hover);
        }

        /* Main Dashboard Split View */
        main {
            display: flex;
            flex: 1;
            height: calc(100vh - 70px);
            overflow: hidden;
        }

        .pane {
            flex: 1;
            display: flex;
            flex-direction: column;
            height: 100%;
            overflow: hidden;
        }

        .pane-left {
            border-right: 1px solid var(--border);
            background-color: #111827; /* Dark background for PDF loader */
            position: relative;
        }

        .pane-right {
            background-color: var(--bg-main);
        }

        /* PDF Viewer Container */
        .pdf-container {
            width: 100%;
            height: 100%;
            display: flex;
            justify-content: center;
            align-items: center;
        }

        iframe {
            width: 100%;
            height: 100%;
            border: none;
        }

        .unsupported-file-card {
            display: flex;
            flex-direction: column;
            align-items: center;
            gap: 20px;
            padding: 3rem;
            max-width: 450px;
            text-align: center;
            background-color: var(--bg-card);
            border-radius: 12px;
            border: 1px solid var(--border);
            box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.3);
        }

        .unsupported-title {
            font-size: 1.25rem;
            font-weight: 600;
            color: var(--warning);
        }

        /* JSON Editor Container */
        .editor-header {
            display: flex;
            justify-content: space-between;
            align-items: center;
            padding: 12px 24px;
            background-color: var(--bg-card);
            border-bottom: 1px solid var(--border);
        }

        .editor-title {
            font-size: 0.875rem;
            font-weight: 600;
            text-transform: uppercase;
            letter-spacing: 0.05em;
            color: var(--text-muted);
        }

        .editor-actions {
            display: flex;
            gap: 8px;
        }

        .editor-container {
            flex: 1;
            position: relative;
            display: flex;
            flex-direction: column;
            padding: 16px;
            background-color: var(--bg-editor);
            overflow: hidden;
        }

        textarea {
            flex: 1;
            width: 100%;
            height: 100%;
            background-color: transparent;
            color: #38bdf8; /* Sleek cyan code color */
            border: none;
            outline: none;
            font-family: 'JetBrains Mono', monospace;
            font-size: 0.875rem;
            line-height: 1.6;
            resize: none;
            tab-size: 2;
            overflow-y: auto;
        }

        /* Empty State */
        .empty-state {
            display: flex;
            flex-direction: column;
            justify-content: center;
            align-items: center;
            gap: 24px;
            height: 100%;
            width: 100%;
            text-align: center;
            padding: 3rem;
        }

        .empty-icon {
            font-size: 4rem;
            animation: bounce 2s infinite;
        }

        @keyframes bounce {
            0%, 100% { transform: translateY(0); }
            50% { transform: translateY(-10px); }
        }

        .empty-title {
            font-size: 2rem;
            font-weight: 700;
            background: linear-gradient(135deg, #34d399, #10b981);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
        }

        /* Toast notification */
        .toast {
            position: fixed;
            bottom: 24px;
            right: 24px;
            background-color: var(--bg-card);
            border-left: 4px solid var(--accent);
            padding: 16px 24px;
            border-radius: 6px;
            box-shadow: 0 10px 15px -3px rgba(0, 0, 0, 0.3);
            display: flex;
            align-items: center;
            gap: 12px;
            transform: translateY(100px);
            opacity: 0;
            transition: all 0.3s cubic-bezier(0.16, 1, 0.3, 1);
            z-index: 100;
        }

        .toast.show {
            transform: translateY(0);
            opacity: 1;
        }

        .toast.success {
            border-left-color: var(--success);
        }

        .toast.error {
            border-left-color: var(--danger);
        }

        /* Loading spinner */
        .spinner {
            border: 3px solid rgba(255,255,255,0.1);
            width: 24px;
            height: 24px;
            border-radius: 50%;
            border-left-color: var(--accent);
            animation: spin 1s linear infinite;
        }

        @keyframes spin {
            0% { transform: rotate(0deg); }
            100% { transform: rotate(360deg); }
        }

        .kbd {
            background-color: var(--border);
            border: 1px solid rgba(255,255,255,0.1);
            border-radius: 4px;
            padding: 1px 5px;
            font-size: 0.75rem;
            font-family: inherit;
            box-shadow: 0 1px 0 rgba(0,0,0,0.2);
        }
    </style>
</head>
<body>
    <header id="app-header" style="display: none;">
        <div class="logo-section">
            <span class="logo-title">Resume GT Validator</span>
            <span id="pending-badge" class="badge">0 Pending</span>
        </div>
        
        <div class="progress-section">
            <span id="progress-text" class="progress-text">Loading...</span>
            <div class="progress-bar-container">
                <div id="progress-bar" class="progress-bar-fill"></div>
            </div>
        </div>

        <div class="controls">
            <button id="btn-prev" class="btn" onclick="prevFile()" disabled>
                &larr; Backward
            </button>
            <button id="btn-next" class="btn" onclick="nextFile()" disabled>
                Next &rarr;
            </button>
            <button id="btn-approve" class="btn btn-success" onclick="approveCurrent()" disabled>
                ✓ Approve &amp; Next <span class="kbd" style="margin-left: 6px;">Ctrl+Enter</span>
            </button>
        </div>
    </header>

    <main id="app-main">
        <div class="empty-state" id="loading-state">
            <div class="spinner"></div>
            <div>Loading Ground Truth Workspace...</div>
        </div>
    </main>

    <div id="toast" class="toast">
        <span id="toast-message">Notification message</span>
    </div>

    <script>
        let files = [];
        let currentIndex = 0;
        let originalJsonContent = "";

        // Fetch remaining list of files
        async function fetchFiles() {
            try {
                const res = await fetch('/api/files');
                const data = await res.json();
                files = data.files || [];
                
                if (files.length === 0) {
                    showAllDone();
                } else {
                    // Ensure we don't go out of bounds if list shrunk
                    if (currentIndex >= files.length) {
                        currentIndex = files.length - 1;
                    }
                    if (currentIndex < 0) {
                        currentIndex = 0;
                    }
                    showApp();
                    loadCurrentItem();
                }
            } catch (err) {
                console.error(err);
                showToast("Failed to fetch pending files list", "error");
            }
        }

        function showApp() {
            // Check if app layout is already built
            if (document.getElementById('json-textarea')) return;

            document.getElementById('app-header').style.display = 'flex';
            document.getElementById('app-main').innerHTML = `
                <div class="pane pane-left">
                    <div id="pdf-view-container" class="pdf-container">
                        <div class="spinner"></div>
                    </div>
                </div>
                <div class="pane pane-right">
                    <div class="editor-header">
                        <span class="editor-title">JSON Ground Truth Data</span>
                        <div class="editor-actions">
                            <span id="validation-badge" class="badge">Checking...</span>
                            <button class="btn" style="padding: 4px 8px; font-size: 0.75rem;" onclick="formatJson()">Format</button>
                            <button class="btn" style="padding: 4px 8px; font-size: 0.75rem;" onclick="resetJson()">Reset</button>
                        </div>
                    </div>
                    <div class="editor-container">
                        <textarea id="json-textarea" spellcheck="false"></textarea>
                    </div>
                </div>
            `;
            
            // Hook up editor syntax check
            const textarea = document.getElementById('json-textarea');
            textarea.addEventListener('input', validateJson);
            
            // Enable tab support in textarea
            textarea.addEventListener('keydown', function(e) {
                if (e.key === 'Tab') {
                    e.preventDefault();
                    const start = this.selectionStart;
                    const end = this.selectionEnd;
                    this.value = this.value.substring(0, start) + "  " + this.value.substring(end);
                    this.selectionStart = this.selectionEnd = start + 2;
                    validateJson();
                }
            });
        }

        function showAllDone() {
            document.getElementById('app-header').style.display = 'none';
            document.getElementById('app-main').innerHTML = `
                <div class="empty-state">
                    <div class="empty-icon">🎉</div>
                    <div class="empty-title">All Resumes Validated!</div>
                    <p style="color: var(--text-muted); max-width: 400px; line-height: 1.6;">
                        Excellent job! All files have been approved and moved into the <code>approved_jsons/</code> directory.
                    </p>
                </div>
            `;
        }

        async function loadCurrentItem() {
            if (files.length === 0) return;
            const currentItem = files[currentIndex];
            
            // Update progress and header details
            document.getElementById('pending-badge').textContent = `${files.length} Pending`;
            document.getElementById('progress-text').textContent = `Resume ${currentIndex + 1} of ${files.length}`;
            
            const percentage = ((currentIndex + 1) / files.length) * 100;
            document.getElementById('progress-bar').style.width = `${percentage}%`;
            
            // Handle disabled states for buttons
            document.getElementById('btn-prev').disabled = currentIndex === 0;
            document.getElementById('btn-next').disabled = currentIndex === files.length - 1;
            
            // Load PDF / Word Doc
            const pdfContainer = document.getElementById('pdf-view-container');
            pdfContainer.innerHTML = '<div class="spinner"></div>';
            
            if (currentItem.pdf) {
                const ext = currentItem.pdf.split('.').pop().toLowerCase();
                if (ext === 'pdf') {
                    pdfContainer.innerHTML = `<iframe src="/pdf/${encodeURIComponent(currentItem.pdf)}"></iframe>`;
                } else {
                    // Handle DOC/DOCX
                    pdfContainer.innerHTML = `
                        <div class="unsupported-file-card">
                            <div class="unsupported-title">Word Document Format (${ext.toUpperCase()})</div>
                            <p style="color: var(--text-muted); font-size: 0.875rem; line-height: 1.5;">
                                Browsers cannot render Word files inline. Download the file or view it locally, then validate the JSON mapping here.
                            </p>
                            <a href="/pdf/${encodeURIComponent(currentItem.pdf)}" download class="btn btn-primary" style="text-decoration: none;">
                                📥 Download ${currentItem.pdf}
                            </a>
                        </div>
                    `;
                }
            } else {
                pdfContainer.innerHTML = `
                    <div class="unsupported-file-card">
                        <div class="unsupported-title" style="color: var(--danger);">No Matching Document Found</div>
                        <p style="color: var(--text-muted); font-size: 0.875rem;">
                            Could not find a matching resume file in CV directory for <code>${currentItem.json}</code>.
                        </p>
                    </div>
                `;
            }

            // Load JSON content
            const textarea = document.getElementById('json-textarea');
            textarea.value = "Loading JSON content...";
            textarea.disabled = true;
            
            try {
                const res = await fetch(`/api/json/${encodeURIComponent(currentItem.json)}`);
                if (!res.ok) throw new Error("Failed to load JSON file");
                const jsonText = await res.text();
                
                // Prettify on load
                try {
                    const parsed = JSON.parse(jsonText);
                    const formatted = JSON.stringify(parsed, null, 2);
                    textarea.value = formatted;
                    originalJsonContent = formatted;
                } catch {
                    textarea.value = jsonText;
                    originalJsonContent = jsonText;
                }
                
                textarea.disabled = false;
                validateJson();
            } catch (err) {
                textarea.value = "Error: Could not load JSON content.";
                console.error(err);
                showToast("Failed to load JSON details", "error");
            }
        }

        function validateJson() {
            const textarea = document.getElementById('json-textarea');
            const badge = document.getElementById('validation-badge');
            const approveBtn = document.getElementById('btn-approve');
            
            if (!textarea || textarea.disabled) return;

            try {
                JSON.parse(textarea.value);
                badge.textContent = "Valid JSON";
                badge.className = "badge badge-success";
                approveBtn.disabled = false;
            } catch (err) {
                badge.textContent = "Syntax Error";
                badge.className = "badge badge-danger";
                approveBtn.disabled = true;
            }
        }

        function formatJson() {
            const textarea = document.getElementById('json-textarea');
            try {
                const val = JSON.parse(textarea.value);
                textarea.value = JSON.stringify(val, null, 2);
                validateJson();
            } catch (err) {
                showToast("Cannot format invalid JSON", "error");
            }
        }

        function resetJson() {
            const textarea = document.getElementById('json-textarea');
            textarea.value = originalJsonContent;
            validateJson();
        }

        // Navigation
        function prevFile() {
            if (currentIndex > 0) {
                currentIndex--;
                loadCurrentItem();
            }
        }

        function nextFile() {
            if (currentIndex < files.length - 1) {
                currentIndex++;
                loadCurrentItem();
            }
        }

        async function approveCurrent() {
            if (files.length === 0) return;
            const currentItem = files[currentIndex];
            const textarea = document.getElementById('json-textarea');
            const approveBtn = document.getElementById('btn-approve');
            
            // Double check validation before submit
            try {
                JSON.parse(textarea.value);
            } catch {
                showToast("Please correct JSON syntax errors first", "error");
                return;
            }

            approveBtn.disabled = true;
            
            try {
                const res = await fetch(`/api/approve/${encodeURIComponent(currentItem.json)}`, {
                    method: 'POST',
                    headers: { 'Content-Type': 'application/json' },
                    body: textarea.value
                });
                
                if (!res.ok) {
                    const errorData = await res.json();
                    throw new Error(errorData.message || "Approval failed");
                }
                
                showToast(`Approved and saved ${currentItem.json}`, "success");
                
                // Refresh list from server to ensure accurate state
                await fetchFiles();
            } catch (err) {
                console.error(err);
                showToast(`Error: ${err.message}`, "error");
                approveBtn.disabled = false;
            }
        }

        // Keyboard Shortcuts
        document.addEventListener('keydown', function(e) {
            // Check for Ctrl+Enter or Cmd+Enter
            if ((e.ctrlKey || e.metaKey) && e.key === 'Enter') {
                e.preventDefault();
                const approveBtn = document.getElementById('btn-approve');
                if (approveBtn && !approveBtn.disabled) {
                    approveCurrent();
                }
            }
            
            // Check for Cmd+S or Ctrl+S
            if ((e.ctrlKey || e.metaKey) && e.key === 's') {
                e.preventDefault();
                formatJson();
                showToast("Formatted JSON", "success");
            }

            // Arrow keys for navigation (when not focused on text area)
            if (document.activeElement.tagName !== 'TEXTAREA' && document.activeElement.tagName !== 'INPUT') {
                if (e.key === 'ArrowLeft') {
                    prevFile();
                } else if (e.key === 'ArrowRight') {
                    nextFile();
                }
            }
        });

        // Toast helper
        let toastTimeout;
        function showToast(message, type = "success") {
            const toast = document.getElementById('toast');
            const toastMsg = document.getElementById('toast-message');
            
            toastMsg.textContent = message;
            toast.className = `toast ${type} show`;
            
            clearTimeout(toastTimeout);
            toastTimeout = setTimeout(() => {
                toast.className = 'toast';
            }, 3000);
        }

        // Start
        fetchFiles();
    </script>
</body>
</html>
"""

class GroundTruthHandler(BaseHTTPRequestHandler):
    def send_json(self, data, status=200):
        self.send_response(status)
        self.send_header('Content-Type', 'application/json; charset=utf-8')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()
        self.wfile.write(json.dumps(data).encode('utf-8'))

    def do_GET(self):
        # Decode path
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
            filename = path[len("/api/json/"):]
            filename = os.path.basename(filename)
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
            filename = path[len("/pdf/"):]
            filename = os.path.basename(filename)
            filepath = os.path.join(PDF_DIR, filename)
            
            if os.path.exists(filepath):
                ext = os.path.splitext(filename)[1].lower()
                content_type = 'application/octet-stream'
                if ext == '.pdf':
                    content_type = 'application/pdf'
                elif ext == '.docx':
                    content_type = 'application/vnd.openxmlformats-officedocument.wordprocessingml.document'
                elif ext == '.doc':
                    content_type = 'application/msword'
                
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
            filename = path[len("/api/approve/"):]
            filename = os.path.basename(filename)
            
            # Read request body
            content_length = int(self.headers.get('Content-Length', 0))
            body = self.rfile.read(content_length).decode('utf-8')
            
            try:
                # Validate JSON structure
                parsed_json = json.loads(body)
                
                # Write to approved directory
                os.makedirs(APPROVED_DIR, exist_ok=True)
                approved_path = os.path.join(APPROVED_DIR, filename)
                
                with open(approved_path, 'w', encoding='utf-8') as f:
                    json.dump(parsed_json, f, ensure_ascii=False, indent=2)
                
                # Delete original JSON
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

def natural_sort_key(s):
    return [int(text) if text.isdigit() else text.lower() for text in re.split(r'(\d+)', s)]

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

if __name__ == '__main__':
    run()
