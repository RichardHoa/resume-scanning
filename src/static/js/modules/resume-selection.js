/**
 * ==============================================================================
 * Resume Selection (Evaluator Step 3)
 * ==============================================================================
 * Description: Lists the scanned resumes HR can evaluate, grouped by secret
 *              evaluation-order tier, with search, select-all, "select the Batch
 *              just extracted" and the order file's status. Reports the selection
 *              size so the evaluator can enable its Run button.
 */

import { API } from './api.js';
import { BatchStore } from './batch-job.js';
import { byId } from './dom.js';
import { html, raw } from './html.js';
import {
    tierLabels, tierRank, SCANNED_RESUME_LABEL, SCANNED_RESUME_MESSAGE, MISSING_POSITION_LABEL, MISSING_POSITION_MESSAGE
} from './report.js';

export class ResumeSelection {
    /**
     * @param {function(number): void} onSelectionChange - Called with the number of selected resumes.
     */
    constructor(onSelectionChange) {
        this.onSelectionChange = onSelectionChange;
        this.resumes = [];
        this.selected = new Set();
        this.searchTerm = '';
        this.techMode = false;
        this.orderActive = false;
        this.tier1Count = 0;
        this.tier2Count = 0;
        // Selected once the next load has the list, e.g. the Batch just extracted when HR came from Step 1
        this.selectAfterLoad = BatchStore.takeSelectLastExtracted() ? BatchStore.lastExtracted() : null;

        this.container = byId('scanned-resumes-container');
        this.chkSelectAll = byId('chk-select-all');
        this.countBadge = byId('selected-count-badge');
        this.searchInput = byId('eval-cand-search');
        this.btnRefresh = byId('btn-refresh-resumes');
        this.btnSelectLastBatch = byId('btn-select-last-batch');

        this.btnRefresh.addEventListener('click', () => this.load());
        this.chkSelectAll.addEventListener('change', () => {
            this.selected.clear();
            if (this.chkSelectAll.checked) {
                this.filteredResumes().forEach(r => this.selected.add(r.filename));
            }
            this.render();
            this.updateSelectedCount();
        });
        this.btnSelectLastBatch.addEventListener('click', () => this.selectFilenames(BatchStore.lastExtracted()));
        this.searchInput.addEventListener('input', () => {
            this.searchTerm = this.searchInput.value.toLowerCase().trim();
            this.render();
        });
    }

    /**
     * Selects exactly those of the named resumes that are listed, and nothing else.
     * @param {Array<string>} filenames - Resume JSON file names.
     */
    selectFilenames(filenames) {
        const listed = new Set(this.resumes.map(r => r.filename));
        this.selected = new Set(filenames.filter(name => listed.has(name)));
        this.chkSelectAll.checked = false;
        this.render();
        this.updateSelectedCount();
    }

    /** File names of the selected resumes. */
    selectedFilenames() {
        return Array.from(this.selected);
    }

    /**
     * Returns list of resumes matching search term.
     */
    filteredResumes() {
        if (!this.searchTerm) return this.resumes;
        // A Missing Position resume can have a null title
        return this.resumes.filter(r =>
            r.filename.toLowerCase().includes(this.searchTerm)
            || r.email.toLowerCase().includes(this.searchTerm)
            || (r.title || '').toLowerCase().includes(this.searchTerm));
    }

    /**
     * Fetches scanned resumes from backend, clearing the selection.
     */
    async load() {
        this.container.innerHTML = '<div class="loading-state">Đang tải danh sách CV đã quét...</div>';
        this.selected.clear();
        this.chkSelectAll.checked = false;
        this.updateSelectedCount();

        try {
            const data = await API.getScannedResumes();
            this.resumes = data.resumes;
            this.orderActive = data.evaluation_order_active;
            this.techMode = data.tech_mode === true;
            this.tier1Count = data.tier1_count;
            this.tier2Count = data.tier2_count;

            const listed = new Set(this.resumes.map(r => r.filename));
            this.btnSelectLastBatch.hidden = !BatchStore.lastExtracted().some(name => listed.has(name));

            if (this.resumes.length === 0) {
                this.container.innerHTML = '<div class="empty-state empty-state--compact">Chưa có CV nào được quét. Hãy tải CV PDF lên ở Bước 1 trước.</div>';
                return;
            }
            if (this.selectAfterLoad) {
                const names = this.selectAfterLoad;
                this.selectAfterLoad = null;
                this.selectFilenames(names);
                return;
            }
            this.render();
        } catch (err) {
            this.container.innerHTML = html`<div class="error-state">Không tải được danh sách CV: ${err.message}</div>`;
        }
    }

    /**
     * Renders the order-file banner and the candidate checkbox list grouped by tier.
     */
    render() {
        const resumes = this.filteredResumes();
        if (resumes.length === 0) {
            this.container.innerHTML = '<div class="empty-state empty-state--compact">Không có ứng viên nào khớp với từ khóa tìm kiếm.</div>';
            return;
        }

        const orderFile = this.techMode ? 'evaluation_order_tech.txt' : 'evaluation_order.txt';
        const orderDetail = this.techMode ? `Top ${this.tier1Count}` : `Nhóm 1: ${this.tier1Count} • Nhóm 2: ${this.tier2Count}`;
        this.container.innerHTML = this.orderActive
            ? html`<div class="order-banner order-banner--active"><span>🔒 Thứ tự bí mật: Đang áp dụng</span><span class="order-banner-detail">${orderDetail}</span></div>`
            : html`<div class="order-banner order-banner--missing"><span>⚠️ Thứ tự bí mật: Không tìm thấy tệp</span><span class="order-banner-detail">${orderFile}</span></div>`;

        [1, 2, 3].forEach(tier => {
            const items = resumes.filter(r => r.tier === tier);
            if (items.length === 0) return;

            const block = document.createElement('div');
            block.className = `scanned-tier-block tier-${tier}-block`;
            block.innerHTML = html`
                <div class="panel-header-split scanned-tier-header">
                    <span class="scanned-tier-title">${tierLabels(tier, this.techMode).title}</span>
                    <span class="tier-badge tier-badge-${tier}">${items.length} ứng viên</span>
                </div>
                <div class="tier-items-list"></div>
            `;
            const list = block.querySelector('.tier-items-list');
            items.forEach(r => list.appendChild(this.buildResumeCard(r)));
            this.container.appendChild(block);
        });
    }

    /**
     * One selectable resume row: checkbox, rank, file name, email and position (or why it has none).
     * @param {Object} r - One entry of /api/scanned_resumes.
     * @returns {HTMLElement}
     */
    buildResumeCard(r) {
        const isSel = this.selected.has(r.filename);
        const rank = tierRank(r);
        const card = document.createElement('div');
        card.className = `resume-card-item ${isSel ? 'selected' : ''}`;
        let meta = r.title;
        if (r.scanned_resume) meta = html`<span class="badge-warning" title="${SCANNED_RESUME_MESSAGE}">⛔ ${SCANNED_RESUME_LABEL}</span>`;
        else if (r.missing_position) meta = html`<span class="badge-warning" title="${MISSING_POSITION_MESSAGE}">⚠️ ${MISSING_POSITION_LABEL}</span>`;
        card.innerHTML = html`
            <input type="checkbox" class="chk-resume" ${isSel && raw('checked')}>
            <div class="resume-info">
                <span class="resume-title">${rank > 0 && html`<span class="tier-rank-badge" title="Thứ hạng trong danh sách đánh giá">#${rank}</span> `}${r.filename}</span>
                <span class="resume-meta">✉ ${r.email} • ${meta}</span>
            </div>
        `;

        const chk = card.querySelector('.chk-resume');
        card.addEventListener('click', (e) => {
            if (e.target !== chk) chk.checked = !chk.checked;
            if (chk.checked) this.selected.add(r.filename);
            else this.selected.delete(r.filename);
            card.classList.toggle('selected', chk.checked);
            this.updateSelectedCount();
        });
        return card;
    }

    updateSelectedCount() {
        const count = this.selected.size;
        this.countBadge.textContent = count > 1
            ? `Đã chọn ${count} CV — sẽ đánh giá song song`
            : `Đã chọn ${count} CV`;
        this.onSelectionChange(this.selected.size);
    }
}
