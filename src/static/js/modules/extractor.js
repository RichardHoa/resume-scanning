/**
 * ==============================================================================
 * CV Extractor Controller (Step 1: AI Layout Resume Parsing)
 * ==============================================================================
 * Description: Manages PDF file drag-and-drop, upload submission, extraction
 *              progress spinner state, and visual tab rendering for parsed JSON.
 */

import { API } from './api.js';
import { WaitingScreen } from './waiting-screen.js';
import { byId, downloadBlob } from './dom.js';
import { html } from './html.js';
import { MISSING_POSITION_MESSAGE } from './report.js';

export class ExtractorController {
    constructor() {
        this.selectedFile = null;
        this.extractedJsonData = null;
        this.isFullVisual = false;
        this.waitingScreen = new WaitingScreen();

        this.initDOMElements();
        this.initEvents();
    }

    /**
     * Binds DOM element references required for file upload and JSON visualization.
     */
    initDOMElements() {
        this.dropzone = byId('dropzone');
        this.fileInput = byId('file-input');
        this.browseLink = this.dropzone.querySelector('.browse-link');
        this.filePreview = byId('file-preview');
        this.previewFilename = byId('preview-filename');
        this.previewFilesize = byId('preview-filesize');
        this.btnRemoveFile = byId('btn-remove-file');
        this.btnExtract = byId('btn-extract');

        this.uploadSection = byId('upload-section');
        this.resultsSection = byId('results-section');
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
     * Registers event listeners for drag-and-drop file upload, extraction actions, and tab navigation.
     */
    initEvents() {
        this.browseLink.addEventListener('click', () => this.fileInput.click());
        // The dropzone is a button too; keys on the browse link inside it are the link's own
        this.dropzone.addEventListener('keydown', (e) => {
            if (e.target !== this.dropzone || (e.key !== 'Enter' && e.key !== ' ')) return;
            e.preventDefault();
            this.fileInput.click();
        });

        this.fileInput.addEventListener('change', (e) => {
            if (e.target.files.length > 0) this.handleFileSelect(e.target.files[0]);
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
            const files = e.dataTransfer.files;
            if (files.length > 0) this.handleFileSelect(files[0]);
        });

        this.btnRemoveFile.addEventListener('click', () => this.resetFileInput());
        this.btnExtract.addEventListener('click', () => this.runExtraction());
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
     * Validates and selects candidate PDF file.
     * @param {File} file - Selected resume file.
     */
    handleFileSelect(file) {
        if (file.type !== 'application/pdf' && !file.name.toLowerCase().endsWith('.pdf')) {
            alert('Chỉ hỗ trợ tệp CV định dạng PDF.');
            return;
        }
        this.selectedFile = file;
        this.previewFilename.textContent = file.name;
        this.previewFilesize.textContent = this.formatBytes(file.size);
        this.dropzone.hidden = true;
        this.filePreview.hidden = false;
        this.btnExtract.disabled = false;
    }

    /**
     * Clears currently selected file and restores dropzone interface.
     */
    resetFileInput() {
        this.selectedFile = null;
        this.fileInput.value = '';
        this.filePreview.hidden = true;
        this.dropzone.hidden = false;
        this.btnExtract.disabled = true;
    }

    /**
     * Triggers backend API call to run resume PDF extraction.
     */
    async runExtraction() {
        if (!this.selectedFile) return;
        try {
            const { data, extractionTime } = await this.waitingScreen.run(
                'extract',
                'Đang trích xuất CV PDF...',
                'Đang đọc tệp PDF và cấu trúc hóa thông tin CV bằng mô hình AI cục bộ.',
                () => API.extractCv(this.selectedFile)
            );
            this.extractedJsonData = data;
            this.displayResults(data, extractionTime);
        } catch (err) {
            alert('Lỗi trích xuất: ' + err.message);
        }
    }

    /**
     * Renders extracted JSON in split pane (raw JSON & visual profile cards).
     * @param {Object} data - Extracted resume JSON data schema.
     * @param {string|null} extractionTime - Execution time header string.
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

        if (extractionTime) this.valTime.textContent = parseFloat(extractionTime).toFixed(2) + 's';
        this.badgeTime.hidden = !extractionTime;

        this.uploadSection.hidden = true;
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
        const filename = this.selectedFile ? `${this.selectedFile.name.replace(/\.[^/.]+$/, '')}_extracted.json` : 'extracted_resume.json';
        downloadBlob(blob, filename);
    }

    /**
     * Resets extraction view to allow uploading another CV.
     */
    resetView() {
        this.resetFileInput();
        this.extractedJsonData = null;
        this.resultsSection.hidden = true;
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
