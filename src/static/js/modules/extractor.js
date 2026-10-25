/**
 * ==============================================================================
 * CV Extractor Controller (Step 1: Trích xuất hàng loạt)
 * ==============================================================================
 * Description: Takes a folder or several PDF resumes (drag-and-drop or pickers),
 *              checks the Batch before upload (skipped files, clashing names,
 *              re-extractions), runs it as a server Batch job behind the waiting
 *              screen, and shows a results table, one row per file, whose rows
 *              open the split view (raw JSON & visual profile tabs). A Batch of
 *              one opens the split view directly.
 */

import { API } from './api.js';
import { WaitingScreen } from './waiting-screen.js';
import { BatchStore, followBatchJob, offerRunningBatch, runningBatchFromRefusal } from './batch-job.js';
import { byId, downloadBlob } from './dom.js';
import { html } from './html.js';
import { MISSING_POSITION_LABEL, MISSING_POSITION_MESSAGE, SCANNED_RESUME_LABEL, SCANNED_RESUME_MESSAGE } from './report.js';

// As BATCH_MAX_PDF_BYTES on the server: a bigger PDF is skipped before the Batch starts
const MAX_PDF_BYTES = 20 * 1024 * 1024;

const SKIP_REASONS = { not_pdf: 'không phải PDF', too_large: 'lớn hơn 20 MB' };

// Outcome of one file of a Batch: its label and the badge class it shows with
const OUTCOMES = {
    extracted: { label: 'Đã trích xuất', badge: 'band-STRONG_MATCH' },
    fidelity_warnings: { label: 'Có cảnh báo văn bản', badge: 'band-LOW_MATCH' },
    repaired: { label: 'Đã vá – có thể thiếu trường', badge: 'band-LOW_MATCH' },
    scanned: { label: SCANNED_RESUME_LABEL, badge: 'band-REJECT' },
    failed: { label: 'Lỗi', badge: 'band-REJECT' },
    cancelled: { label: 'Đã hủy', badge: 'band-ERROR' }
};

function isPdf(file) {
    return file.type === 'application/pdf' || file.name.toLowerCase().endsWith('.pdf');
}

/** A resume's JSON file name, as Step 3 of the evaluator lists it. */
function jsonName(pdfName) {
    return pdfName.replace(/\.pdf$/i, '') + '.json';
}

/**
 * Every file dropped, walking dropped folders and their subfolders.
 * The entries are read before the first await, while the drop's data is still readable.
 * @param {DataTransfer} dataTransfer
 * @returns {Promise<Array<File>>}
 */
async function filesFromDrop(dataTransfer) {
    const entries = Array.from(dataTransfer.items || [])
        .map(item => (item.webkitGetAsEntry ? item.webkitGetAsEntry() : null))
        .filter(Boolean);
    if (entries.length === 0) return Array.from(dataTransfer.files);

    const files = [];
    const walk = async (entry) => {
        if (entry.isFile) {
            files.push(await new Promise((resolve, reject) => entry.file(resolve, reject)));
        } else if (entry.isDirectory) {
            const reader = entry.createReader();
            // readEntries gives a folder's entries a chunk at a time, then an empty chunk
            for (;;) {
                const chunk = await new Promise((resolve, reject) => reader.readEntries(resolve, reject));
                if (chunk.length === 0) break;
                for (const child of chunk) await walk(child);
            }
        }
    };
    for (const entry of entries) await walk(entry);
    return files;
}

export class ExtractorController {
    constructor() {
        // The Batch checked before upload: {pdfs, skipped, duplicates, existingCount}
        this.pending = null;
        // Rows of the Batch results table by file name; a retry's results replace their rows
        this.batchRows = new Map();
        // The latest extraction job, which holds the failed and cancelled files for a retry
        this.lastJobId = null;
        this.currentName = null;
        this.extractedJsonData = null;
        this.isFullVisual = false;
        this.waitingScreen = new WaitingScreen();

        this.initDOMElements();
        this.initEvents();
        this.reconnectToRunningBatch();
    }

    /**
     * Binds DOM element references required for file upload, the Batch table and JSON visualization.
     */
    initDOMElements() {
        this.dropzone = byId('dropzone');
        this.fileInput = byId('file-input');
        this.folderInput = byId('folder-input');
        this.btnBrowseFiles = byId('btn-browse-files');
        this.btnBrowseFolder = byId('btn-browse-folder');
        this.preflight = byId('batch-preflight');
        this.preflightCount = byId('preflight-count');
        this.preflightSize = byId('preflight-size');
        this.preflightNotes = byId('preflight-notes');
        this.btnRemoveFile = byId('btn-remove-file');
        this.btnExtract = byId('btn-extract');
        this.btnExtractLabel = byId('btn-extract-label');

        this.uploadSection = byId('upload-section');
        this.batchSection = byId('batch-results-section');
        this.batchSummary = byId('batch-results-summary');
        this.batchBody = byId('batch-results-body');
        this.btnRetryFailed = byId('btn-retry-failed');
        this.btnEvaluateBatch = byId('btn-evaluate-batch');
        this.btnBatchReset = byId('btn-batch-reset');

        this.resultsSection = byId('results-section');
        this.btnBackToBatch = byId('btn-back-to-batch');
        this.jsonOutput = byId('json-output');
        this.warningBanner = byId('warning-banner');
        this.warningList = byId('warning-list');
        this.badgeTime = byId('badge-time');
        this.valTime = byId('val-time');

        this.btnToggleView = byId('btn-toggle-view');
        this.dashboardSplit = this.resultsSection.querySelector('.dashboard-split');
        this.codePane = this.resultsSection.querySelector('.code-pane');

        this.btnCopy = byId('btn-copy');
        this.btnDownload = byId('btn-download');
        this.btnReset = byId('btn-reset');

        this.tabButtons = this.resultsSection.querySelectorAll('.tab-btn');
        this.tabContents = this.resultsSection.querySelectorAll('.tab-content');
    }

    /**
     * Registers event listeners for drag-and-drop upload, the pickers, the Batch table and tab navigation.
     */
    initEvents() {
        this.btnBrowseFiles.addEventListener('click', () => this.fileInput.click());
        this.btnBrowseFolder.addEventListener('click', () => this.folderInput.click());
        // The dropzone is a button too; keys on the browse links inside it are the links' own
        this.dropzone.addEventListener('keydown', (e) => {
            if (e.target !== this.dropzone || (e.key !== 'Enter' && e.key !== ' ')) return;
            e.preventDefault();
            this.fileInput.click();
        });

        [this.fileInput, this.folderInput].forEach(input => {
            input.addEventListener('change', (e) => {
                if (e.target.files.length > 0) this.handleFiles(Array.from(e.target.files));
            });
        });

        ['dragenter', 'dragover'].forEach(evt => {
            this.dropzone.addEventListener(evt, (e) => {
                e.preventDefault();
                this.dropzone.classList.add('dragover');
            });
        });
        ['dragleave', 'drop'].forEach(evt => {
            this.dropzone.addEventListener(evt, (e) => {
                e.preventDefault();
                this.dropzone.classList.remove('dragover');
            });
        });
        this.dropzone.addEventListener('drop', (e) => {
            filesFromDrop(e.dataTransfer)
                .then(files => { if (files.length > 0) this.handleFiles(files); })
                .catch(err => alert('Không đọc được các tệp đã thả: ' + err.message));
        });

        this.btnRemoveFile.addEventListener('click', () => this.resetFileInput());
        this.btnExtract.addEventListener('click', () => this.runExtraction());
        this.btnRetryFailed.addEventListener('click', () => this.retryFailed());
        this.btnEvaluateBatch.addEventListener('click', () => {
            BatchStore.requestSelectLastExtracted();
            window.location.href = '/evaluator';
        });
        this.btnBatchReset.addEventListener('click', () => this.resetView());
        this.btnBackToBatch.addEventListener('click', () => this.showBatchTable());
        this.btnToggleView.addEventListener('click', () => this.toggleViewMode());
        this.btnCopy.addEventListener('click', () => this.copyJson());
        this.btnDownload.addEventListener('click', () => this.downloadJson());
        this.btnReset.addEventListener('click', () => this.resetView());

        // Visual Pane Tab Switching
        this.tabButtons.forEach(btn => {
            btn.addEventListener('click', () => {
                this.tabButtons.forEach(b => {
                    b.classList.toggle('active', b === btn);
                    b.setAttribute('aria-selected', String(b === btn));
                });
                this.tabContents.forEach(c => c.classList.toggle('active', c.id === btn.dataset.tab));
            });
        });
    }

    /**
     * Toggles between Split View (Code + Visual) and Full Visual View (Visual Only 100% width).
     */
    toggleViewMode() {
        this.isFullVisual = !this.isFullVisual;
        this.dashboardSplit.classList.toggle('full-visual-mode', this.isFullVisual);
        this.codePane.hidden = this.isFullVisual;
        this.btnToggleView.textContent = this.isFullVisual ? '👁️ Hiện chia đôi màn hình' : '👁️ Chỉ trực quan / Chia đôi';
    }

    /**
     * Checks the chosen files as a Batch: non-PDF and oversized files are skipped, clashing names block it, and
     * names already extracted are counted, since extracting them again deletes their evaluations.
     * @param {Array<File>} files - Every file chosen or dropped, from every subfolder.
     */
    async handleFiles(files) {
        const pdfs = [];
        const skipped = [];
        files.forEach(file => {
            if (!isPdf(file)) skipped.push({ name: file.name, reason: 'not_pdf' });
            else if (file.size > MAX_PDF_BYTES) skipped.push({ name: file.name, reason: 'too_large' });
            else pdfs.push(file);
        });
        const nameCounts = new Map();
        pdfs.forEach(f => nameCounts.set(f.name, (nameCounts.get(f.name) || 0) + 1));
        const duplicates = [...nameCounts].filter(([, count]) => count > 1).map(([name]) => name);

        let existingCount = null;
        try {
            const data = await API.getScannedResumes();
            const stored = new Set(data.resumes.map(r => r.filename));
            existingCount = pdfs.filter(f => stored.has(jsonName(f.name))).length;
        } catch (err) {
            console.warn('Could not check which resumes are already extracted:', err);
        }

        this.pending = { pdfs, skipped, duplicates, existingCount };
        this.renderPreflight();
    }

    /** The check of the chosen Batch, before HR confirms the upload. */
    renderPreflight() {
        const { pdfs, skipped, duplicates, existingCount } = this.pending;
        const totalBytes = pdfs.reduce((sum, f) => sum + f.size, 0);
        this.preflightCount.textContent = `${pdfs.length} CV PDF sẽ được trích xuất`;
        this.preflightSize.textContent = pdfs.length > 0 ? `(${this.formatBytes(totalBytes)})` : '';

        const notes = [];
        if (duplicates.length > 0) {
            notes.push(html`<li class="preflight-note preflight-note--blocking">⛔ Có tệp trùng tên trong lô (${duplicates.join(', ')}). Mỗi CV được lưu theo tên tệp, nên hãy đổi tên rồi chọn lại.</li>`);
        }
        if (existingCount > 0) {
            notes.push(html`<li class="preflight-note preflight-note--warning">⚠️ ${existingCount} CV đã được trích xuất trước đây và sẽ được trích xuất lại; kết quả đánh giá cũ của chúng sẽ bị xóa.</li>`);
        }
        if (skipped.length > 0) {
            notes.push(html`<li class="preflight-note">Bỏ qua ${skipped.length} tệp: ${skipped.map(s => `${s.name} (${SKIP_REASONS[s.reason]})`).join(', ')}</li>`);
        }
        if (pdfs.length === 0) {
            notes.push(html`<li class="preflight-note preflight-note--blocking">Không có tệp PDF nào để trích xuất.</li>`);
        }
        this.preflightNotes.innerHTML = html`${notes}`;

        this.dropzone.hidden = true;
        this.preflight.hidden = false;
        this.btnExtract.disabled = pdfs.length === 0 || duplicates.length > 0;
        this.btnExtractLabel.textContent = pdfs.length > 1
            ? `Bắt đầu trích xuất hàng loạt ${pdfs.length} CV`
            : 'Bắt đầu trích xuất CV';
    }

    /**
     * Clears the chosen files and restores the dropzone.
     */
    resetFileInput() {
        this.pending = null;
        this.fileInput.value = '';
        this.folderInput.value = '';
        this.preflight.hidden = true;
        this.dropzone.hidden = false;
        this.btnExtract.disabled = true;
        this.btnExtractLabel.textContent = 'Bắt đầu trích xuất hàng loạt';
    }

    /**
     * Uploads the checked Batch and follows its extraction job.
     */
    async runExtraction() {
        if (!this.pending || this.btnExtract.disabled) return;
        const { pdfs } = this.pending;
        let started;
        this.waitingScreen.startSingle('upload', `Đang tải lên ${pdfs.length} CV...`, 'Đang gửi các tệp PDF lên máy chủ.');
        try {
            started = await API.startExtractionJob(pdfs);
        } catch (err) {
            this.waitingScreen.finish();
            const running = runningBatchFromRefusal(err);
            if (running) offerRunningBatch(running, r => this.followJob(r.jobId, false), 'extract');
            else alert('Lỗi trích xuất: ' + err.message);
            return;
        }
        this.waitingScreen.finish();
        this.batchRows.clear();
        BatchStore.rememberRunning(started.job_id, 'extract');
        await this.followJob(started.job_id, false, pdfs.length);
    }

    /**
     * Reruns the latest job's failed and cancelled files from the PDFs the server still holds.
     */
    async retryFailed() {
        let started;
        try {
            started = await API.retryExtractionJob(this.lastJobId);
        } catch (err) {
            const running = runningBatchFromRefusal(err);
            if (running) offerRunningBatch(running, r => this.followJob(r.jobId, false), 'extract');
            else alert('Lỗi thử lại: ' + err.message);
            return;
        }
        BatchStore.rememberRunning(started.job_id, 'extract');
        await this.followJob(started.job_id, true);
    }

    /** After a reload, follows the extraction Batch this browser started, if the server still has it. */
    reconnectToRunningBatch() {
        const running = BatchStore.running();
        if (running && running.kind === 'extract') this.followJob(running.jobId, false);
    }

    /**
     * Follows an extraction job on the waiting screen, then shows its results.
     * @param {string} jobId
     * @param {boolean} isRetry - A retry's rows replace their rows in the table instead of starting a new one.
     * @param {number} [total=0] - Files in the Batch, until the first status says.
     */
    async followJob(jobId, isRetry, total = 0) {
        this.waitingScreen.startBatch(
            'extract',
            'Đang trích xuất hàng loạt CV...',
            'Các CV được AI trích xuất song song. Có thể dừng lô: CV đang xử lý vẫn được hoàn tất.',
            total,
            () => API.cancelBatchJob(jobId)
        );
        let job;
        try {
            job = await followBatchJob(jobId, this.waitingScreen);
        } catch (err) {
            this.waitingScreen.finish();
            // The server no longer has it (expired or restarted): nothing left to reconnect to
            if (err.status === 404) BatchStore.forgetRunning();
            else alert('Lỗi trích xuất: ' + err.message);
            return;
        }
        this.waitingScreen.finish();
        BatchStore.forgetRunning();
        this.showFinishedJob(job, isRetry);
    }

    /**
     * Shows a finished extraction job: the split view for a Batch of one, else the results table.
     */
    async showFinishedJob(job, isRetry) {
        if (job.state === 'failed') {
            alert('Lỗi trích xuất: ' + (job.error || 'Trích xuất hàng loạt thất bại.'));
            return;
        }
        this.lastJobId = job.job_id;
        if (!isRetry) this.batchRows.clear();
        job.items.forEach(item => this.batchRows.set(item.name, item));
        const extracted = [...this.batchRows.values()].filter(row => row.state === 'done').map(row => jsonName(row.name));
        BatchStore.rememberLastExtracted(extracted);
        this.resetFileInput();

        if (this.batchRows.size === 1) {
            await this.showSingleResult([...this.batchRows.values()][0]);
            return;
        }
        this.renderBatchTable();
        this.showBatchTable();
    }

    /** A Batch of one, as a single upload always looked: its split view, or why there is none. */
    async showSingleResult(row) {
        if (row.state === 'failed') {
            alert('Lỗi trích xuất: ' + row.error);
        } else if (row.state === 'done' && row.result && row.result.outcome === 'scanned') {
            alert(SCANNED_RESUME_MESSAGE);
        } else if (row.state === 'done') {
            await this.openExtraction(row);
        }
    }

    /** One row per file of the Batch: outcome, Missing Position and time; an extracted row opens its split view. */
    renderBatchTable() {
        const rows = [...this.batchRows.values()];
        const count = state => rows.filter(row => row.state === state).length;
        const failed = count('failed');
        const cancelled = count('cancelled');
        this.batchSummary.textContent = `${count('done')}/${rows.length} CV xong`
            + (failed > 0 ? ` · ${failed} lỗi` : '')
            + (cancelled > 0 ? ` · ${cancelled} đã hủy` : '');
        this.btnRetryFailed.hidden = failed + cancelled === 0;
        this.btnRetryFailed.textContent = `Thử lại các CV lỗi (${failed + cancelled})`;
        this.btnEvaluateBatch.disabled = count('done') === 0;

        this.batchBody.innerHTML = '';
        rows.forEach(row => {
            const outcomeKey = row.state === 'done' ? (row.result && row.result.outcome) || 'extracted' : row.state;
            const outcome = OUTCOMES[outcomeKey] || OUTCOMES.failed;
            const openable = row.state === 'done' && outcomeKey !== 'scanned';
            let position = '—';
            if (row.state === 'done' && outcomeKey !== 'scanned') {
                position = row.result && row.result.missing_position
                    ? html`<span class="badge-warning" title="${MISSING_POSITION_MESSAGE}">⚠️ ${MISSING_POSITION_LABEL}</span>`
                    : 'Có ghi';
            }
            const tr = document.createElement('tr');
            tr.className = openable ? 'batch-row batch-row--openable' : 'batch-row';
            tr.innerHTML = html`
                <td class="batch-cell-name">
                    ${openable ? html`<button type="button" class="browse-link batch-open">${row.name}</button>` : row.name}
                    ${row.error && html`<div class="batch-cell-error">${row.error}</div>`}
                    ${outcomeKey === 'scanned' && html`<div class="batch-cell-error">${SCANNED_RESUME_MESSAGE}</div>`}
                </td>
                <td><span class="match-pill ${outcome.badge}">${outcome.label}</span></td>
                <td>${position}</td>
                <td class="batch-cell-time">${row.seconds != null ? `${row.seconds.toFixed(1)}s` : '—'}</td>
            `;
            if (openable) tr.querySelector('.batch-open').addEventListener('click', () => this.openExtraction(row));
            this.batchBody.appendChild(tr);
        });
    }

    showBatchTable() {
        this.uploadSection.hidden = true;
        this.resultsSection.hidden = true;
        this.batchSection.hidden = false;
    }

    /** Opens one extracted file of the Batch in the split view. */
    async openExtraction(row) {
        let data;
        try {
            data = await API.getExtraction(row.name);
        } catch (err) {
            alert('Lỗi tải kết quả trích xuất: ' + err.message);
            return;
        }
        this.currentName = row.name;
        this.extractedJsonData = data;
        this.btnBackToBatch.hidden = this.batchRows.size <= 1;
        this.displayResults(data, row.seconds);
    }

    /**
     * Renders extracted JSON in split pane (raw JSON & visual profile cards).
     * @param {Object} data - Extracted resume JSON data schema.
     * @param {?number} extractionTime - Seconds the extraction took.
     */
    displayResults(data, extractionTime) {
        this.jsonOutput.textContent = JSON.stringify(data, null, 2);

        this.renderProfile(data);
        this.renderExperience(data.work_experience || []);
        this.renderEducation(data.education_background || []);
        this.renderCertifications(data.certifications || [], data.languages || []);
        this.renderSkills(data.skills || []);
        this.renderProjects(data.projects || []);

        const warnings = data.warning || [];
        this.warningList.innerHTML = html`${warnings.map(msg => html`<li>${msg}</li>`)}`;
        this.warningBanner.hidden = warnings.length === 0;

        if (extractionTime) this.valTime.textContent = Number(extractionTime).toFixed(2) + 's';
        this.badgeTime.hidden = !extractionTime;

        this.uploadSection.hidden = true;
        this.batchSection.hidden = true;
        this.resultsSection.hidden = false;
    }

    /**
     * Fills a list from items, or shows a note when there are none.
     * @param {HTMLElement} el - The list container.
     * @param {Array} items
     * @param {string} emptyText - Shown when items is empty.
     * @param {function(*): SafeHtml} renderItem - Markup for one item.
     */
    renderList(el, items, emptyText, renderItem) {
        el.innerHTML = items.length > 0
            ? html`${items.map(renderItem)}`
            : html`<p class="summary-text">${emptyText}</p>`;
    }

    /** Profile tab: applied position, contact details and self-evaluation. */
    renderProfile(data) {
        const applied = data.position_applied || {};
        // A Missing Position is still evaluated, as if applying for the job HR evaluates against; HR sees it here, right after upload
        const positionEl = byId('profile-position');
        const missingPosition = !(typeof applied.title === 'string' && applied.title.trim());
        positionEl.textContent = missingPosition ? `⚠️ ${MISSING_POSITION_MESSAGE}` : applied.title;
        positionEl.classList.toggle('profile-position--missing', missingPosition);
        byId('profile-level').textContent = applied.level || 'Chưa rõ';

        const basic = data.basic_information || {};
        byId('profile-email').textContent = basic.email || 'Không có';
        byId('profile-phone').textContent = basic.phone || 'Không có';
        byId('profile-location').textContent = basic.location || 'Không có';
        byId('profile-links').textContent = basic.other_info || 'Không có';
        byId('profile-summary').textContent = data.self_evaluation || 'Không có phần tự đánh giá.';
    }

    /** Work Experience tab: one timeline card per job. */
    renderExperience(jobs) {
        this.renderList(byId('experience-timeline'), jobs, 'Không tìm thấy kinh nghiệm làm việc.', job => {
            const resp = job.responsibilities;
            const respHtml = resp && html`<div class="job-responsibilities">${Array.isArray(resp)
                ? html`<ul>${resp.map(r => html`<li>${r}</li>`)}</ul>`
                : resp}</div>`;
            return html`
                <div class="timeline-card">
                    <div class="timeline-card-header">
                        <div>
                            <div class="job-title">${job.position || 'Vị trí'}</div>
                            <div class="company-name">${job.company_name || 'Không có'}</div>
                        </div>
                        <span class="job-duration">${job.duration || 'Không có'}</span>
                    </div>
                    ${job.company_description && html`<div class="company-desc">${job.company_description}</div>`}
                    ${respHtml}
                </div>
            `;
        });
    }

    /** Education tab: one card per school. */
    renderEducation(schools) {
        this.renderList(byId('education-list'), schools, 'Không tìm thấy thông tin học vấn.', school => {
            const meta = [];
            if (school.field_of_study) meta.push(`Chuyên ngành: ${school.field_of_study}`);
            if (school.gpa) meta.push(`GPA: ${school.gpa}`);
            return html`
                <div class="education-item">
                    <div class="univ-name">${school.university_name || 'Không có'}</div>
                    <div class="edu-degree">${school.degree || 'Không rõ bằng cấp'} (${school.graduation_year || 'Không có'})</div>
                    ${meta.length > 0 && html`<div class="edu-meta">${meta.join(' | ')}</div>`}
                </div>
            `;
        });
    }

    /** Certifications list: certificates, then language certificates or, without one, the stated proficiency. */
    renderCertifications(certs, languages) {
        const certItems = certs.map(c => ({ name: c.name, org: c.issuing_organization, dur: c.duration }));
        languages.forEach(l => {
            if (l.certificates && l.certificates.length > 0) {
                l.certificates.forEach(lc => certItems.push({ name: `${l.language}: ${lc.name}`, org: lc.issuing_organization || 'Tổ chức cấp', dur: lc.duration }));
            } else if (l.proficiency) {
                certItems.push({ name: `Ngoại ngữ: ${l.language}`, org: l.proficiency, dur: '' });
            }
        });
        this.renderList(byId('certifications-list'), certItems, 'Không tìm thấy chứng chỉ.', cert => html`
            <div class="cert-card">
                <div class="cert-title">${cert.name}</div>
                <div class="cert-org">${cert.org || 'Không có'} ${cert.dur && `• ${cert.dur}`}</div>
            </div>
        `);
    }

    /** Skills list: one pill per skill. */
    renderSkills(skills) {
        this.renderList(byId('skills-list'), skills, 'Không tìm thấy kỹ năng.', skill => html`<span class="skill-pill">${skill}</span>`);
    }

    /** Projects list: one card per project. */
    renderProjects(projects) {
        this.renderList(byId('projects-list'), projects, 'Không tìm thấy dự án.', p => html`
            <div class="project-card">
                <div class="proj-name">${p.project_name || 'Dự án'} <span class="proj-duration">${p.duration || ''}</span></div>
                <div class="proj-desc">${p.description || 'Không có'}</div>
            </div>
        `);
    }

    /**
     * Copies raw JSON output string to clipboard.
     */
    copyJson() {
        if (!this.extractedJsonData) return;
        navigator.clipboard.writeText(JSON.stringify(this.extractedJsonData, null, 2))
            .then(() => alert('Đã sao chép JSON vào bộ nhớ tạm!'))
            .catch(err => alert('Không sao chép được JSON: ' + err));
    }

    /**
     * Triggers client-side browser download of extracted JSON file.
     */
    downloadJson() {
        if (!this.extractedJsonData) return;
        const blob = new Blob([JSON.stringify(this.extractedJsonData, null, 2)], { type: 'application/json;charset=utf-8' });
        const filename = this.currentName ? `${this.currentName.replace(/\.[^/.]+$/, '')}_extracted.json` : 'extracted_resume.json';
        downloadBlob(blob, filename);
    }

    /**
     * Resets the page to upload another Batch.
     */
    resetView() {
        this.resetFileInput();
        this.batchRows.clear();
        this.currentName = null;
        this.extractedJsonData = null;
        this.resultsSection.hidden = true;
        this.batchSection.hidden = true;
        this.uploadSection.hidden = false;
    }

    formatBytes(bytes, decimals = 2) {
        if (bytes === 0) return '0 byte';
        const k = 1024;
        const dm = decimals < 0 ? 0 : decimals;
        const sizes = ['byte', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
    }
}
