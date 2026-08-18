/**
 * ==============================================================================
 * CV Extractor Controller (Step 1: AI Layout Resume Parsing)
 * ==============================================================================
 * Description: Manages PDF file drag-and-drop, upload submission, extraction
 *              progress spinner state, and visual tab rendering for parsed JSON.
 * Line Count: ~350 lines (Strict Limit: < 500 lines)
 */

import { API } from './api.js';

export class ExtractorController {
    constructor() {
        this.selectedFile = null;
        this.extractedJsonData = null;
        this.loaderInterval = null;

        this.initDOMElements();
        this.initEvents();
    }

    /**
     * Binds DOM element references required for file upload and JSON visualization.
     */
    initDOMElements() {
        this.dropzone = document.getElementById('dropzone');
        this.fileInput = document.getElementById('file-input');
        this.browseLink = document.querySelector('.browse-link');
        this.filePreview = document.getElementById('file-preview');
        this.previewFilename = document.getElementById('preview-filename');
        this.previewFilesize = document.getElementById('preview-filesize');
        this.btnRemoveFile = document.getElementById('btn-remove-file');
        this.btnExtract = document.getElementById('btn-extract');

        this.uploadSection = document.getElementById('upload-section');
        this.resultsSection = document.getElementById('results-section');
        this.jsonOutput = document.getElementById('json-output');

        this.btnToggleView = document.getElementById('btn-toggle-view');
        this.dashboardSplit = document.querySelector('.dashboard-split');
        this.codePane = document.querySelector('.code-pane');

        this.btnCopy = document.getElementById('btn-copy');
        this.btnDownload = document.getElementById('btn-download');
        this.btnReset = document.getElementById('btn-reset');

        this.loaderOverlay = document.getElementById('loader-overlay');
        this.loaderTitle = document.getElementById('loader-title');
        this.loaderDesc = document.getElementById('loader-desc');
        this.loaderProgress = document.getElementById('loader-progress');

        this.tabButtons = document.querySelectorAll('.tab-btn');
        this.tabContents = document.querySelectorAll('.tab-content');
        this.isFullVisual = false;
    }

    /**
     * Registers event listeners for drag-and-drop file upload, extraction actions, and tab navigation.
     */
    initEvents() {
        if (this.browseLink) {
            this.browseLink.addEventListener('click', () => this.fileInput.click());
        }

        if (this.fileInput) {
            this.fileInput.addEventListener('change', (e) => {
                if (e.target.files.length > 0) this.handleFileSelect(e.target.files[0]);
            });
        }

        if (this.dropzone) {
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
        }

        if (this.btnRemoveFile) {
            this.btnRemoveFile.addEventListener('click', () => this.resetFileInput());
        }

        if (this.btnExtract) {
            this.btnExtract.addEventListener('click', () => this.runExtraction());
        }

        if (this.btnToggleView) {
            this.btnToggleView.addEventListener('click', () => this.toggleViewMode());
        }

        if (this.btnCopy) this.btnCopy.addEventListener('click', () => this.copyJson());
        if (this.btnDownload) this.btnDownload.addEventListener('click', () => this.downloadJson());
        if (this.btnReset) this.btnReset.addEventListener('click', () => this.resetView());

        // Visual Pane Tab Switching
        this.tabButtons.forEach(btn => {
            btn.addEventListener('click', () => {
                const tabId = btn.getAttribute('data-tab');
                this.tabButtons.forEach(b => b.classList.remove('active'));
                this.tabContents.forEach(c => c.classList.remove('active'));
                btn.classList.add('active');
                document.getElementById(tabId)?.classList.add('active');
            });
        });
    }

    /**
     * Toggles between Split View (Code + Visual) and Full Visual View (Visual Only 100% width).
     */
    toggleViewMode() {
        if (!this.dashboardSplit) return;
        this.isFullVisual = !this.isFullVisual;
        if (this.isFullVisual) {
            this.dashboardSplit.classList.add('full-visual-mode');
            if (this.codePane) this.codePane.style.display = 'none';
            if (this.btnToggleView) this.btnToggleView.textContent = '👁️ Show Split View';
        } else {
            this.dashboardSplit.classList.remove('full-visual-mode');
            if (this.codePane) this.codePane.style.display = 'flex';
            if (this.btnToggleView) this.btnToggleView.textContent = '👁️ Visual Only / Split';
        }
    }

    /**
     * Validates and selects candidate PDF file.
     * @param {File} file - Selected resume file.
     */
    handleFileSelect(file) {
        if (file.type !== 'application/pdf' && !file.name.toLowerCase().endsWith('.pdf')) {
            alert('Only PDF resume files are supported.');
            return;
        }
        this.selectedFile = file;
        this.previewFilename.textContent = file.name;
        this.previewFilesize.textContent = this.formatBytes(file.size);
        this.dropzone.style.display = 'none';
        this.filePreview.style.display = 'flex';
        this.btnExtract.disabled = false;
    }

    /**
     * Clears currently selected file and restores dropzone interface.
     */
    resetFileInput() {
        this.selectedFile = null;
        if (this.fileInput) this.fileInput.value = '';
        if (this.filePreview) this.filePreview.style.display = 'none';
        if (this.dropzone) this.dropzone.style.display = 'flex';
        if (this.btnExtract) this.btnExtract.disabled = true;
    }

    /**
     * Triggers backend API call to run resume PDF extraction.
     */
    async runExtraction() {
        if (!this.selectedFile) return;
        this.showLoader();
        try {
            const { data, extractionTime } = await API.extractCv(this.selectedFile);
            this.extractedJsonData = data;
            this.displayResults(data, extractionTime);
        } catch (err) {
            alert('Extraction error: ' + err.message);
        } finally {
            this.hideLoader();
        }
    }

    /**
     * Displays progress loader dialog with animated step messages.
     */
    showLoader() {
        if (!this.loaderOverlay) return;
        this.loaderOverlay.style.display = 'flex';
        if (this.loaderProgress) this.loaderProgress.style.width = '10%';

        const states = [
            { title: 'Reading PDF Document...', desc: 'Parsing binary layer and extracting raw text strings.' },
            { title: 'Analyzing Structural Layout...', desc: 'Identifying bounding boxes, headers, and section breaks.' },
            { title: 'Running Local AI Model...', desc: 'Structuring CV details using local deep learning inference engine.' },
            { title: 'Formatting Output Schema...', desc: 'Mapping work history, education, skills, and certifications.' }
        ];

        let idx = 0;
        this.loaderTitle.textContent = states[0].title;
        this.loaderDesc.textContent = states[0].desc;

        this.loaderInterval = setInterval(() => {
            idx = (idx + 1) % states.length;
            this.loaderTitle.textContent = states[idx].title;
            this.loaderDesc.textContent = states[idx].desc;
        }, 8000);
    }

    /**
     * Hides extraction progress loader dialog.
     */
    hideLoader() {
        clearInterval(this.loaderInterval);
        if (this.loaderOverlay) this.loaderOverlay.style.display = 'none';
    }

    /**
     * Renders extracted JSON in split pane (raw JSON & visual profile cards).
     * @param {Object} data - Extracted resume JSON data schema.
     * @param {string|null} extractionTime - Execution time header string.
     */
    displayResults(data, extractionTime) {
        if (this.jsonOutput) {
            this.jsonOutput.textContent = JSON.stringify(data, null, 2);
        }

        this.renderParsedData(data);

        const badgeTime = document.getElementById('badge-time');
        const valTime = document.getElementById('val-time');
        if (extractionTime && badgeTime && valTime) {
            valTime.textContent = parseFloat(extractionTime).toFixed(2) + 's';
            badgeTime.style.display = 'flex';
        } else if (badgeTime) {
            badgeTime.style.display = 'none';
        }

        this.uploadSection.style.display = 'none';
        this.resultsSection.style.display = 'flex';
    }

    /**
     * Renders parsed data across profile, experience, education, and skills tabs.
     * @param {Object} data - Structured resume JSON.
     */
    renderParsedData(data) {
        // 1. Profile Tab
        const applied = data.position_applied || {};
        document.getElementById('profile-position').textContent = applied.title || 'Position Not Specified';
        document.getElementById('profile-level').textContent = applied.level || 'Unknown';

        const basic = data.basic_information || {};
        document.getElementById('profile-email').textContent = basic.email || 'N/A';
        document.getElementById('profile-phone').textContent = basic.phone || 'N/A';
        document.getElementById('profile-location').textContent = basic.location || 'N/A';
        document.getElementById('profile-links').textContent = basic.other_info || 'N/A';
        document.getElementById('profile-summary').textContent = data.self_evaluation || 'No self evaluation provided.';

        // 2. Work Experience Tab
        const expTimeline = document.getElementById('experience-timeline');
        expTimeline.innerHTML = '';
        const jobs = data.work_experience || [];
        if (jobs.length === 0) {
            expTimeline.innerHTML = '<p class="summary-text" style="text-align: center; padding: 2rem 0;">No work experience detected.</p>';
        } else {
            jobs.forEach(job => {
                const card = document.createElement('div');
                card.className = 'timeline-card';
                let respHtml = '';
                if (job.responsibilities) {
                    if (Array.isArray(job.responsibilities)) {
                        respHtml = `<div class="job-responsibilities"><ul>${job.responsibilities.map(r => `<li>${this.escapeHtml(r)}</li>`).join('')}</ul></div>`;
                    } else {
                        respHtml = `<div class="job-responsibilities">${this.escapeHtml(job.responsibilities)}</div>`;
                    }
                }
                card.innerHTML = `
                    <div class="timeline-card-header">
                        <div>
                            <div class="job-title">${this.escapeHtml(job.position || 'Position')}</div>
                            <div class="company-name">${this.escapeHtml(job.company_name || 'N/A')}</div>
                        </div>
                        <span class="job-duration">${this.escapeHtml(job.duration || 'N/A')}</span>
                    </div>
                    ${job.company_description ? `<div class="company-desc">${this.escapeHtml(job.company_description)}</div>` : ''}
                    ${respHtml}
                `;
                expTimeline.appendChild(card);
            });
        }

        // 3. Education & Certifications Tab
        const eduList = document.getElementById('education-list');
        eduList.innerHTML = '';
        const schools = data.education_background || [];
        if (schools.length === 0) {
            eduList.innerHTML = '<p class="summary-text">No education background detected.</p>';
        } else {
            schools.forEach(school => {
                const item = document.createElement('div');
                item.className = 'education-item';
                const meta = [];
                if (school.field_of_study) meta.push(`Major: ${school.field_of_study}`);
                if (school.gpa) meta.push(`GPA: ${school.gpa}`);
                item.innerHTML = `
                    <div class="univ-name">${this.escapeHtml(school.university_name || 'N/A')}</div>
                    <div class="edu-degree">${this.escapeHtml(school.degree || 'Degree N/A')} (${school.graduation_year || 'N/A'})</div>
                    ${meta.length > 0 ? `<div class="edu-meta">${this.escapeHtml(meta.join(' | '))}</div>` : ''}
                `;
                eduList.appendChild(item);
            });
        }

        const certsList = document.getElementById('certifications-list');
        certsList.innerHTML = '';
        const certs = data.certifications || [];
        const languages = data.languages || [];
        const certItems = [];
        certs.forEach(c => certItems.push({ name: c.name, org: c.issuing_organization, dur: c.duration }));
        languages.forEach(l => {
            if (l.certificates && l.certificates.length > 0) {
                l.certificates.forEach(lc => certItems.push({ name: `${l.language}: ${lc.name}`, org: lc.issuing_organization || 'Board', dur: lc.duration }));
            } else if (l.proficiency) {
                certItems.push({ name: `Language: ${l.language}`, org: l.proficiency, dur: '' });
            }
        });
        if (certItems.length === 0) {
            certsList.innerHTML = '<p class="summary-text">No certifications detected.</p>';
        } else {
            certItems.forEach(cert => {
                const card = document.createElement('div');
                card.className = 'cert-card';
                card.innerHTML = `
                    <div class="cert-title">${this.escapeHtml(cert.name)}</div>
                    <div class="cert-org">${this.escapeHtml(cert.org || 'N/A')} ${cert.dur ? `• ${this.escapeHtml(cert.dur)}` : ''}</div>
                `;
                certsList.appendChild(card);
            });
        }

        // 4. Skills & Projects Tab
        const skillsList = document.getElementById('skills-list');
        skillsList.innerHTML = '';
        const skills = data.skills_and_specialties || [];
        if (skills.length === 0) {
            skillsList.innerHTML = '<p class="summary-text">No skills detected.</p>';
        } else {
            skills.forEach(sk => {
                const pill = document.createElement('span');
                pill.className = 'skill-pill';
                pill.textContent = sk;
                skillsList.appendChild(pill);
            });
        }

        const projectsList = document.getElementById('projects-list');
        projectsList.innerHTML = '';
        const projects = data.projects || [];
        if (projects.length === 0) {
            projectsList.innerHTML = '<p class="summary-text">No projects detected.</p>';
        } else {
            projects.forEach(p => {
                const card = document.createElement('div');
                card.className = 'project-card';
                card.innerHTML = `
                    <div class="proj-name">${this.escapeHtml(p.project_name || 'Project')} <span style="font-size:0.8rem; font-weight:normal; float:right;">${this.escapeHtml(p.duration || '')}</span></div>
                    <div class="proj-desc" style="font-size:0.85rem; margin-top:4px;">${this.escapeHtml(p.description || 'N/A')}</div>
                `;
                projectsList.appendChild(card);
            });
        }
    }

    /**
     * Copies raw JSON output string to clipboard.
     */
    copyJson() {
        if (!this.extractedJsonData) return;
        navigator.clipboard.writeText(JSON.stringify(this.extractedJsonData, null, 2))
            .then(() => alert('Raw JSON copied to clipboard!'))
            .catch(err => alert('Failed to copy JSON: ' + err));
    }

    /**
     * Triggers client-side browser download of extracted JSON file.
     */
    downloadJson() {
        if (!this.extractedJsonData) return;
        const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(this.extractedJsonData, null, 2));
        const anchor = document.createElement('a');
        const filename = this.selectedFile ? `${this.selectedFile.name.replace(/\.[^/.]+$/, "")}_extracted.json` : 'extracted_resume.json';
        anchor.setAttribute("href", dataStr);
        anchor.setAttribute("download", filename);
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
    }

    /**
     * Resets extraction view to allow uploading another CV.
     */
    resetView() {
        this.resetFileInput();
        this.extractedJsonData = null;
        this.resultsSection.style.display = 'none';
        this.uploadSection.style.display = 'flex';
    }

    formatBytes(bytes, decimals = 2) {
        if (bytes === 0) return '0 Bytes';
        const k = 1024;
        const dm = decimals < 0 ? 0 : decimals;
        const sizes = ['Bytes', 'KB', 'MB', 'GB'];
        const i = Math.floor(Math.log(bytes) / Math.log(k));
        return parseFloat((bytes / Math.pow(k, i)).toFixed(dm)) + ' ' + sizes[i];
    }

    escapeHtml(str) {
        if (!str) return '';
        return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }
}
