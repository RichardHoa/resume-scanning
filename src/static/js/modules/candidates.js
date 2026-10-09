/**
 * ==============================================================================
 * Candidate Pool Controller (Harmonious Executive Light Theme)
 * ==============================================================================
 * Description: Manages candidate evaluation pool browsing, search filtering,
 *              sorting by score/date/name, summary statistics, and candidate
 *              detail modal overlay.
 */

import { API } from './api.js';
import { CATEGORY_NAMES } from './criteria-editor.js';

const FAILED_EVALUATION_LABEL = 'Lỗi – cần chạy lại';
const FEEDBACK_TITLE = 'Nhận xét của hội đồng đánh giá';
const FEEDBACK_FAILED_LABEL = 'Không thể tạo nhận xét';

// Review Panel Panelists, in display order (keys match candidate_feedback.panelist_views)
const PANELIST_NAMES = {
    leadership: 'Lãnh đạo',
    domain_expertise: 'Chuyên môn',
    people_culture: 'Con người & Văn hóa'
};

/**
 * A Failed Evaluation (any Category failed) keeps its partial score in the report, but is
 * never ranked or shown as a result. HR reruns it by selecting it and clicking Evaluate again.
 */
function isFailedEvaluation(cand) {
    return cand.status === 'error';
}

const MISSING_POSITION_LABEL = 'Thiếu vị trí ứng tuyển';
const MISSING_POSITION_MESSAGE = 'CV không ghi vị trí ứng tuyển; hệ thống mặc định ứng viên ứng tuyển vị trí này và vẫn đánh giá, xếp hạng như bình thường.';

/**
 * A Missing Position resume states no applied-for position. It is still evaluated and ranked as if
 * applying for this job; the flag only tells HR the position was missing.
 */
function isMissingPosition(cand) {
    return cand.missing_position === true;
}

/**
 * A Not Applicable Category got no Criterion from HR's requirements. It is never judged, so it is never shown.
 */
function isNotApplicableCategory(d) {
    return !!(d && d.not_applicable);
}

/**
 * The label shown instead of a score for an unscored report (a Failed Evaluation).
 * @returns {string} The label, or '' for a scored report.
 */
function unscoredLabel(cand) {
    if (isFailedEvaluation(cand)) return FAILED_EVALUATION_LABEL;
    return '';
}

/**
 * The name and email to show once per candidate. Without an extracted name the email is the heading,
 * and is not repeated under it.
 * @returns {{name: string, email: string, contactEmail: string}} contactEmail is the email whether or not it is the heading.
 */
function candidateIdentity(cand) {
    const identifier = cand.candidate_identifier || '';
    const rawEmail = cand.candidate_email || cand.email || (identifier.includes('@') ? identifier : '');
    const contactEmail = rawEmail === 'N/A' ? '' : rawEmail;
    const extractedName = (cand.candidate_name || '').trim();
    return {
        name: extractedName || contactEmail || identifier || cand.resume_name || 'Ứng viên',
        email: extractedName ? contactEmail : '',
        contactEmail
    };
}

export class CandidatePoolController {
    constructor() {
        this.allCandidatesData = [];
        this.currentModalCandidate = null;
        this.modalEvaluationHtml = '';
        this.modalShowingResume = false;

        this.initDOMElements();
        this.initEvents();
    }

    /**
     * Binds DOM element references required for candidate pool toolbar and detail modal.
     */
    initDOMElements() {
        this.btnRefreshCandidates = document.getElementById('btn-refresh-candidates');
        this.candSearchInput = document.getElementById('cand-search-input');
        this.candFilterStatus = document.getElementById('cand-filter-status');
        this.candSortBy = document.getElementById('cand-sort-by');
        this.candCardsGrid = document.getElementById('cand-cards-grid');

        this.candModal = document.getElementById('cand-detail-modal');
        this.modalCandName = document.getElementById('modal-cand-name');
        this.modalCandRole = document.getElementById('modal-cand-role');
        this.modalCandScore = document.getElementById('modal-cand-score');
        this.modalCandBody = document.getElementById('modal-cand-body');
        this.modalCloseBtn = document.getElementById('modal-close-btn');
        this.modalBtnDownload = document.getElementById('modal-btn-download');
        this.modalBtnResume = document.getElementById('modal-btn-resume');
    }

    /**
     * Binds event listeners for search inputs, filter dropdowns, and modal dialog toggles.
     */
    initEvents() {
        if (this.btnRefreshCandidates) {
            this.btnRefreshCandidates.addEventListener('click', () => this.loadCandidatePool());
        }
        if (this.candSearchInput) {
            this.candSearchInput.addEventListener('input', () => this.applyCandidateFiltersAndSort());
        }
        if (this.candFilterStatus) {
            this.candFilterStatus.addEventListener('change', () => this.applyCandidateFiltersAndSort());
        }
        if (this.candSortBy) {
            this.candSortBy.addEventListener('change', () => this.applyCandidateFiltersAndSort());
        }
        if (this.modalCloseBtn) {
            this.modalCloseBtn.addEventListener('click', () => this.closeCandidateModal());
        }
        if (this.candModal) {
            this.candModal.addEventListener('click', (e) => {
                if (e.target === this.candModal) this.closeCandidateModal();
            });
        }
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && this.candModal && this.candModal.style.display !== 'none') {
                this.closeCandidateModal();
            }
        });

        if (this.modalBtnDownload) {
            this.modalBtnDownload.addEventListener('click', () => this.downloadModalReportPdf());
        }
        if (this.modalBtnResume) {
            this.modalBtnResume.addEventListener('click', () => this.toggleModalResumeView());
        }
    }

    /**
     * Fetches candidate evaluation reports from eval_results/ and renders pool grid.
     */
    async loadCandidatePool() {
        if (!this.candCardsGrid) return;
        this.candCardsGrid.innerHTML = '<div class="loading-state">Đang tải kết quả đánh giá ứng viên...</div>';

        try {
            const data = await API.getEvalResults();
            this.allCandidatesData = data.evaluations || [];
            this.updateSummaryStats(this.allCandidatesData);
            this.applyCandidateFiltersAndSort();
        } catch (err) {
            this.candCardsGrid.innerHTML = `<div class="error-state">Không tải được danh sách ứng viên: ${this.escapeHtml(err.message)}</div>`;
        }
    }

    /**
     * Calculates candidate pool summary metrics (Total, Strong, Potential, Low, Reject, Avg Score).
     * @param {Array<Object>} candidates - List of candidate evaluation reports.
     */
    updateSummaryStats(candidates) {
        const total = candidates.length;
        const scored = candidates.filter(c => !unscoredLabel(c));
        let strong = 0, potential = 0, low = 0, reject = 0;
        let scoreSum = 0;

        scored.forEach(c => {
            const score = c.overall_score || 0;
            scoreSum += score;
            const rec = c.match_recommendation || '';
            if (rec === 'STRONG_MATCH' || score >= 85) strong++;
            else if (rec === 'POTENTIAL_MATCH' || score >= 70) potential++;
            else if (rec === 'LOW_MATCH' || score >= 55) low++;
            else reject++;
        });

        const avgScore = scored.length > 0 ? (scoreSum / scored.length).toFixed(1) : '0.0';

        if (document.getElementById('cand-stat-total')) document.getElementById('cand-stat-total').textContent = total;
        if (document.getElementById('cand-stat-strong')) document.getElementById('cand-stat-strong').textContent = strong;
        if (document.getElementById('cand-stat-potential')) document.getElementById('cand-stat-potential').textContent = potential;
        if (document.getElementById('cand-stat-low')) document.getElementById('cand-stat-low').textContent = low;
        if (document.getElementById('cand-stat-reject')) document.getElementById('cand-stat-reject').textContent = reject;
        if (document.getElementById('cand-stat-avg')) document.getElementById('cand-stat-avg').textContent = avgScore;
    }

    /**
     * Applies search query, status filtering, and sorting transforms on candidate list.
     */
    applyCandidateFiltersAndSort() {
        if (!this.candCardsGrid) return;

        const query = (this.candSearchInput ? this.candSearchInput.value : '').toLowerCase().trim();
        const statusFilter = this.candFilterStatus ? this.candFilterStatus.value : 'ALL';
        const sortBy = this.candSortBy ? this.candSortBy.value : 'score_desc';

        let filtered = this.allCandidatesData.filter(cand => {
            if (statusFilter !== 'ALL') {
                if (unscoredLabel(cand)) return false;
                const rec = cand.match_recommendation || '';
                const score = cand.overall_score || 0;
                if (statusFilter === 'STRONG_MATCH' && rec !== 'STRONG_MATCH' && score < 85) return false;
                if (statusFilter === 'POTENTIAL_MATCH' && rec !== 'POTENTIAL_MATCH' && (score < 70 || score >= 85)) return false;
                if (statusFilter === 'LOW_MATCH' && rec !== 'LOW_MATCH' && (score < 55 || score >= 70)) return false;
                if (statusFilter === 'REJECT' && rec !== 'REJECT' && score >= 55) return false;
            }

            if (query) {
                const { name, contactEmail } = candidateIdentity(cand);
                if (!name.toLowerCase().includes(query) && !contactEmail.toLowerCase().includes(query)) {
                    return false;
                }
            }
            return true;
        });

        filtered.sort((a, b) => {
            // Unscored reports are unranked: they always sort after scored candidates by score
            if (sortBy === 'score_desc' || sortBy === 'score_asc') {
                const unscoredDiff = !!unscoredLabel(a) - !!unscoredLabel(b);
                if (unscoredDiff !== 0) return unscoredDiff;
            }
            const scoreA = a.overall_score || 0;
            const scoreB = b.overall_score || 0;
            const nameA = candidateIdentity(a).name.toLowerCase();
            const nameB = candidateIdentity(b).name.toLowerCase();
            const dateA = new Date(a.evaluated_at || 0).getTime();
            const dateB = new Date(b.evaluated_at || 0).getTime();
            const tierA = a.tier || 3;
            const tierB = b.tier || 3;
            const orderA = a.tier_order !== undefined ? a.tier_order : 9999;
            const orderB = b.tier_order !== undefined ? b.tier_order : 9999;

            switch (sortBy) {
                case 'evaluation_order':
                    if (tierA !== tierB) return tierA - tierB;
                    if (orderA !== orderB) return orderA - orderB;
                    return nameA.localeCompare(nameB);
                case 'score_asc': return scoreA - scoreB;
                case 'name_asc': return nameA.localeCompare(nameB);
                case 'name_desc': return nameB.localeCompare(nameA);
                case 'date_desc': return dateB - dateA;
                case 'date_asc': return dateA - dateB;
                case 'score_desc':
                default: return scoreB - scoreA;
            }
        });

        this.renderCandidateCards(filtered);
    }

    /**
     * Renders filtered candidate cards into grid container.
     * @param {Array<Object>} candidates - Filtered candidate objects.
     */
    renderCandidateCards(candidates) {
        this.candCardsGrid.innerHTML = '';
        if (candidates.length === 0) {
            this.candCardsGrid.innerHTML = `
                <div class="empty-state" style="grid-column: 1 / -1; padding: 3rem 1rem; text-align: center;">
                    <div class="empty-icon" style="font-size: 2.5rem; margin-bottom: 1rem;">🔍</div>
                    <h3 style="color: #0F172A; font-weight: 800;">Không có ứng viên phù hợp</h3>
                    <p style="color: #334155;">Hãy thử đổi từ khóa tìm kiếm hoặc bộ lọc trạng thái.</p>
                </div>
            `;
            return;
        }

        const sortBy = this.candSortBy ? this.candSortBy.value : 'evaluation_order';

        if (sortBy === 'evaluation_order') {
            const tiers = {
                1: { title: 'Nhóm CV 1 (Ứng viên ưu tiên)', badgeClass: 'tier-badge-1', blockClass: 'tier-1-block', items: [] },
                2: { title: 'Nhóm CV 2 (Ứng viên thứ cấp)', badgeClass: 'tier-badge-2', blockClass: 'tier-2-block', items: [] },
                3: { title: 'Nhóm CV 3 (Ứng viên ngoài danh sách)', badgeClass: 'tier-badge-3', blockClass: 'tier-3-block', items: [] }
            };

            candidates.forEach(c => {
                const t = c.tier || 3;
                if (!tiers[t]) tiers[t] = tiers[3];
                tiers[t].items.push(c);
            });

            [1, 2, 3].forEach(tNum => {
                const group = tiers[tNum];
                if (group.items.length === 0) return;

                const tierBlock = document.createElement('div');
                tierBlock.className = `cand-tier-block ${group.blockClass}`;
                tierBlock.style.gridColumn = '1 / -1';

                tierBlock.innerHTML = `
                    <div class="cand-tier-header">
                        <div class="cand-tier-title-group">
                            <h3>${group.title}</h3>
                            <span class="tier-badge ${group.badgeClass}">Nhóm ${tNum}</span>
                        </div>
                        <span style="font-size: 0.88rem; font-weight: 700; color: #334155;">${group.items.length} ứng viên</span>
                    </div>
                    <div class="tier-grid cand-cards-grid"></div>
                `;

                const tierGrid = tierBlock.querySelector('.tier-grid');
                group.items.forEach(cand => this.appendCandidateCardToContainer(cand, tierGrid));
                this.candCardsGrid.appendChild(tierBlock);
            });
        } else {
            candidates.forEach(cand => this.appendCandidateCardToContainer(cand, this.candCardsGrid));
        }
    }

    appendCandidateCardToContainer(cand, container) {
        const card = document.createElement('div');
        card.className = 'cand-card';
        card.setAttribute('tabindex', '0');
        card.setAttribute('role', 'button');

        const { name, email, contactEmail } = candidateIdentity(cand);
        const numScore = parseFloat(cand.overall_score !== undefined ? cand.overall_score : 0) || 0;
        const score = numScore.toFixed(1);
        const rec = cand.match_recommendation || (numScore >= 85 ? 'STRONG_MATCH' : (numScore >= 70 ? 'POTENTIAL_MATCH' : (numScore >= 55 ? 'LOW_MATCH' : 'REJECT')));

        let recClass = 'match-potential';
        let recText = 'CÓ TIỀM NĂNG';
        if (rec === 'STRONG_MATCH' || numScore >= 85) { recClass = 'match-strong'; recText = 'PHÙ HỢP CAO'; }
        else if (rec === 'POTENTIAL_MATCH' || numScore >= 70) { recClass = 'match-potential'; recText = 'CÓ TIỀM NĂNG'; }
        else if (rec === 'LOW_MATCH' || numScore >= 55) { recClass = 'match-low'; recText = 'PHÙ HỢP THẤP'; }
        else { recClass = 'match-reject'; recText = 'LOẠI'; }

        const unscored = unscoredLabel(cand);
        if (unscored) { recClass = 'match-error'; recText = unscored; }

        const tierBadgeClass = cand.tier === 1 ? 'tier-badge-1' : (cand.tier === 2 ? 'tier-badge-2' : 'tier-badge-3');
        const tierLabel = cand.tier ? `Nhóm ${cand.tier}` : 'Nhóm 3';

        card.setAttribute('aria-label', unscored
            ? `Ứng viên: ${name}, Email: ${contactEmail || 'Không có'}, ${recText}`
            : `Ứng viên: ${name}, Email: ${contactEmail || 'Không có'}, Điểm: ${score}/100, ${recText}`);

        // Vital Info: Breakdown of Match Score Progress Bars
        const dims = cand.dimension_scores || {};
        let dimsBreakdownHtml = '';
        const dimKeys = ['technical_skills', 'work_experience', 'seniority_title', 'education_certifications', 'hidden_culture'];
        const dimShortNames = {
            'technical_skills': 'Kỹ năng chuyên môn',
            'work_experience': 'Kinh nghiệm làm việc',
            'seniority_title': 'Cấp bậc',
            'education_certifications': 'Học vấn & Chứng chỉ',
            'hidden_culture': 'Văn hóa & Kỹ năng mềm'
        };

        dimKeys.forEach(k => {
            if (dims[k] && !unscored && !isNotApplicableCategory(dims[k])) {
                const dScore = Math.round(dims[k].score || 0);
                let fillClass = 'fill-cyan';
                if (dScore >= 85) fillClass = 'fill-emerald';
                else if (dScore >= 70) fillClass = 'fill-cyan';
                else if (dScore >= 55) fillClass = 'fill-amber';
                else fillClass = 'fill-crimson';

                dimsBreakdownHtml += `
                    <div class="dim-bar-item">
                        <div class="dim-bar-header">
                            <span class="dim-bar-name">${dimShortNames[k]}</span>
                            <span class="dim-bar-val">${dScore}/100</span>
                        </div>
                        <div class="dim-progress-track">
                            <div class="dim-progress-fill ${fillClass}" style="width: ${Math.min(100, Math.max(5, dScore))}%;"></div>
                        </div>
                    </div>
                `;
            }
        });

        const isOcrReview = cand.ocr_applied || cand.intensive_hr_review_required || (Array.isArray(cand.warning) && cand.warning.some(w => typeof w === 'string' && w.includes('OCR')));
        const ocrPillHtml = isOcrReview ? `<span class="badge-ocr-review" title="PDF không có lớp văn bản. Đã dùng OCR để trích xuất văn bản. Cần HR kiểm tra thủ công kỹ lưỡng.">⚠️ CẦN HR KIỂM TRA KỸ (OCR)</span>` : '';
        const missingPositionPillHtml = isMissingPosition(cand) ? `<span class="badge-ocr-review" title="${MISSING_POSITION_MESSAGE}">⚠️ ${MISSING_POSITION_LABEL}</span>` : '';

        const emailHtml = email ? `
            <a href="mailto:${this.escapeHtml(email)}" class="cand-email" onclick="event.stopPropagation()" title="Gửi email tới ${this.escapeHtml(email)}">${this.escapeHtml(email)}</a>
        ` : '';

        card.innerHTML = `
            <div class="cand-card-header">
                <div class="cand-info-group">
                    <h3>${this.escapeHtml(name)}</h3>
                    ${emailHtml}
                </div>
                <div class="cand-score-badge">
                    ${unscored
                        ? `<span class="cand-score-val" style="color: #64748B;">—</span>`
                        : `<span class="cand-score-val" style="color: ${numScore >= 85 ? '#059669' : numScore >= 70 ? '#0284C7' : numScore >= 55 ? '#D97706' : '#DC2626'};">${score}</span>`}
                    <span class="cand-score-lbl">Điểm</span>
                </div>
            </div>

            <div class="cand-badges-row">
                <span class="match-pill ${recClass}">${recText}</span>
                <span class="tier-badge ${tierBadgeClass}">${tierLabel}</span>
                ${ocrPillHtml}
                ${missingPositionPillHtml}
            </div>

            ${dimsBreakdownHtml ? `<div class="cand-dimensions-breakdown">${dimsBreakdownHtml}</div>` : ''}

            <div class="cand-card-footer">
                <button class="btn btn-sm btn-secondary cand-inspect-btn" type="button" tabindex="-1">Xem hồ sơ →</button>
            </div>
        `;

        const openHandler = () => this.openCandidateModal(cand, card);
        card.addEventListener('click', openHandler);
        card.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                openHandler();
            }
        });

        container.appendChild(card);
    }

    /**
     * Opens modal dialog showing full candidate evaluation report with keyboard focus trap.
     * @param {Object} cand - Candidate evaluation data object.
     * @param {HTMLElement} triggerEl - Optional element that triggered the modal.
     */
    openCandidateModal(cand, triggerEl = null) {
        this.lastFocusedElement = triggerEl || document.activeElement;
        this.currentModalCandidate = cand;
        if (!this.candModal || !this.modalCandBody) return;

        const { name, email } = candidateIdentity(cand);
        const numScore = parseFloat(cand.overall_score || 0);
        const score = numScore.toFixed(1);
        const rec = cand.match_recommendation || 'POTENTIAL_MATCH';

        let recClass = 'match-potential';
        let recText = 'CÓ TIỀM NĂNG';
        if (rec === 'STRONG_MATCH' || numScore >= 85) { recClass = 'match-strong'; recText = 'PHÙ HỢP CAO'; }
        else if (rec === 'POTENTIAL_MATCH' || numScore >= 70) { recClass = 'match-potential'; recText = 'CÓ TIỀM NĂNG'; }
        else if (rec === 'LOW_MATCH' || numScore >= 55) { recClass = 'match-low'; recText = 'PHÙ HỢP THẤP'; }
        else { recClass = 'match-reject'; recText = 'LOẠI'; }

        const unscored = unscoredLabel(cand);
        if (unscored) { recClass = 'match-error'; recText = unscored; }
        const failed = isFailedEvaluation(cand);

        // Name, email, match, score and evaluation time appear once, in the modal header
        const evaluatedAt = cand.evaluated_at ? new Date(cand.evaluated_at).toLocaleString('vi-VN') : 'Không có';
        if (this.modalCandName) {
            this.modalCandName.innerHTML = `${this.escapeHtml(name)} <span class="match-pill ${recClass}">${recText}</span>`;
        }
        if (this.modalCandRole) {
            const emailLink = email ? `<a href="mailto:${this.escapeHtml(email)}" class="modal-email-link">${this.escapeHtml(email)}</a> • ` : '';
            this.modalCandRole.innerHTML = `${emailLink}Đánh giá lúc ${this.escapeHtml(evaluatedAt)}`;
        }
        if (this.modalCandScore) {
            this.modalCandScore.innerHTML = `
                ${unscored
                    ? `<span class="modal-score-number" style="color: #64748B;">—</span>`
                    : `<span class="modal-score-number" style="color: ${numScore >= 85 ? '#059669' : numScore >= 70 ? '#0284C7' : numScore >= 55 ? '#D97706' : '#DC2626'};">${score}</span>`}
                <span class="modal-score-label">Tổng điểm</span>
            `;
        }

        // An unscored report has no Category scores to show; a Failed Evaluation's partial ones are hidden
        const dims = unscored ? {} : (cand.dimension_scores || {});
        let dimCardsHtml = '';

        Object.keys(dims).forEach(catKey => {
            const d = dims[catKey];
            if (isNotApplicableCategory(d)) return;
            const catName = CATEGORY_NAMES[catKey] || d.category_name || catKey;
            const catWeight = ((d.weight || 0.2) * 100).toFixed(0);
            const dScore = (d.score || 0).toFixed(1);

            let fillClass = 'fill-mid';
            if (d.score >= 85) fillClass = 'fill-high';
            else if (d.score >= 70) fillClass = 'fill-mid';
            else if (d.score >= 55) fillClass = 'fill-low';
            else fillClass = 'fill-reject';

            const gapsList = (d.gaps || []).map(g => `<li>${this.escapeHtml(g)}</li>`).join('');

            dimCardsHtml += `
                <div class="modal-dim-card">
                    <div class="modal-dim-header">
                        <div class="modal-dim-title">
                            ${this.escapeHtml(catName)}
                            <span class="modal-dim-weight">Trọng số: ${catWeight}%</span>
                        </div>
                        <div>
                            <span class="dim-score-pill">${dScore} / 100</span>
                        </div>
                    </div>
                    <div class="modal-dim-progress">
                        <div class="modal-dim-progress-fill ${fillClass}" style="width: ${Math.min(100, Math.max(5, d.score))}%;"></div>
                    </div>
                    ${this.renderCategoryStrengths(d)}
                    ${this.renderCategoryMetCriteria(d)}
                    ${this.renderCategoryNoEvidence(d)}
                    ${gapsList ? `<div class="modal-section-title">Thiếu sót đã xác định:</div><ul class="modal-bullets gaps">${gapsList}</ul>` : ''}
                </div>
            `;
        });

        const isOcrReview = cand.ocr_applied || cand.intensive_hr_review_required || (Array.isArray(cand.warning) && cand.warning.some(w => typeof w === 'string' && w.includes('OCR')));
        const ocrAlertBanner = isOcrReview ? `
            <div class="modal-ocr-alert-banner">
                <div class="modal-ocr-alert-icon">⚠️</div>
                <div class="modal-ocr-alert-content">
                    <strong>CẦN HR KIỂM TRA KỸ (ĐÃ DÙNG OCR)</strong>
                    <p>CV này không có lớp văn bản gốc (PDF scan hoặc ảnh). Hệ thống đã dùng nhận dạng ký tự quang học (OCR) để trích xuất thông tin ứng viên. Vui lòng kiểm tra thủ công kỹ các thông tin đã trích xuất.</p>
                </div>
            </div>
        ` : '';

        const failedCategoryNames = (cand.failed_categories || []).map(k => CATEGORY_NAMES[k] || k);
        const failedEvaluationBanner = failed ? `
            <div class="modal-ocr-alert-banner">
                <div class="modal-ocr-alert-icon">⛔</div>
                <div class="modal-ocr-alert-content">
                    <strong>${FAILED_EVALUATION_LABEL.toUpperCase()}</strong>
                    <p>Không thể chấm điểm ${failedCategoryNames.length > 0 ? `các mục: ${this.escapeHtml(failedCategoryNames.join(', '))}` : 'một số mục đánh giá'}. Kết quả này không được xếp hạng. Hãy chọn lại ứng viên này và bấm Đánh giá để chạy lại.</p>
                </div>
            </div>
        ` : '';

        const missingPositionBanner = isMissingPosition(cand) ? `
            <div class="modal-ocr-alert-banner">
                <div class="modal-ocr-alert-icon">⚠️</div>
                <div class="modal-ocr-alert-content">
                    <strong>${MISSING_POSITION_LABEL.toUpperCase()}</strong>
                    <p>${MISSING_POSITION_MESSAGE}</p>
                </div>
            </div>
        ` : '';

        const feedbackHtml = unscored ? '' : this.renderCandidateFeedback(cand.candidate_feedback);

        this.modalEvaluationHtml = `
            ${missingPositionBanner}
            ${failedEvaluationBanner}
            ${ocrAlertBanner}
            ${feedbackHtml}
            <div class="modal-dim-grid">${dimCardsHtml}</div>
        `;
        this.showModalEvaluation();

        this.candModal.style.display = 'flex';
        document.body.style.overflow = 'hidden';

        if (this.modalCloseBtn) {
            this.modalCloseBtn.focus();
        }
    }

    /**
     * Renders a Category's strengths, shown whenever the evaluator wrote any, whatever the Verdicts.
     * @param {Object} d - One entry of the report's dimension_scores.
     * @returns {string} HTML for the section, or '' when there are no strengths.
     */
    renderCategoryStrengths(d) {
        const list = (d.strengths || []).map(s => `<li>${this.escapeHtml(s)}</li>`).join('');
        return list ? `<div class="modal-section-title">Điểm mạnh chính:</div><ul class="modal-bullets strengths">${list}</ul>` : '';
    }

    /**
     * Renders a Category's criteria judged STRONG or PARTIAL, each followed by the resume quotes that support it.
     * Reports saved before per-criterion results were kept render nothing.
     * @param {Object} d - One entry of the report's dimension_scores.
     * @returns {string} HTML for the section, or '' when no criterion has evidence.
     */
    renderCategoryMetCriteria(d) {
        const list = (d.criteria_evaluations || [])
            .filter(c => c.verdict === 'STRONG_EVIDENCE' || c.verdict === 'PARTIAL_EVIDENCE')
            .map(c => `
                <li>
                    ${this.escapeHtml(c.criterion)}${c.verdict === 'PARTIAL_EVIDENCE' ? '<span class="modal-partial-tag">Đáp ứng một phần</span>' : ''}
                    ${(c.evidence_quotes || []).map(q => `<div class="modal-quote-box">"${this.escapeHtml(q)}"</div>`).join('')}
                </li>
            `).join('');
        return list ? `<div class="modal-section-title">Tiêu chí đáp ứng:</div><ul class="modal-bullets strengths">${list}</ul>` : '';
    }

    /**
     * Renders a Category's criteria judged NO_EVIDENCE: requirements the resume shows nothing for.
     * Reports saved before per-criterion results were kept render nothing.
     * @param {Object} d - One entry of the report's dimension_scores.
     * @returns {string} HTML for the section, or '' when no criterion lacks evidence.
     */
    renderCategoryNoEvidence(d) {
        const list = (d.criteria_evaluations || [])
            .filter(c => c.verdict === 'NO_EVIDENCE')
            .map(c => `<li>${this.escapeHtml(c.criterion)}</li>`)
            .join('');
        return list ? `<div class="modal-section-title">Tiêu chí chưa có bằng chứng:</div><ul class="modal-bullets gaps">${list}</ul>` : '';
    }

    /**
     * Shows the evaluation in the modal body (the default view).
     */
    showModalEvaluation() {
        this.modalShowingResume = false;
        this.modalCandBody.classList.remove('modal-body-resume');
        this.modalCandBody.innerHTML = this.modalEvaluationHtml || '';
        this.modalCandBody.scrollTop = 0;
        if (this.modalBtnResume) this.modalBtnResume.textContent = 'Xem CV';
    }

    /**
     * Replaces the evaluation in the modal body with the candidate's original resume PDF.
     */
    showModalResume() {
        const cand = this.currentModalCandidate;
        if (!cand) return;
        this.modalShowingResume = true;
        this.modalCandBody.classList.add('modal-body-resume');
        if (this.modalBtnResume) this.modalBtnResume.textContent = '← Quay lại đánh giá';

        if (!cand.has_resume_pdf || !cand.filename) {
            this.modalCandBody.innerHTML = '<div class="modal-resume-missing">Chưa lưu PDF cho ứng viên này — hãy tải lên lại.</div>';
            return;
        }
        const url = API.resumePdfUrl(cand.filename);
        this.modalCandBody.innerHTML = `
            <div class="modal-resume-toolbar">
                <a class="btn btn-secondary btn-sm" href="${url}" target="_blank" rel="noopener">Mở trong tab mới ↗</a>
            </div>
            <iframe class="modal-resume-frame" src="${url}" title="CV của ${this.escapeHtml(candidateIdentity(cand).name)}"></iframe>
        `;
    }

    /**
     * Switches the modal body between the evaluation and the resume PDF.
     */
    toggleModalResumeView() {
        if (this.modalShowingResume) this.showModalEvaluation();
        else this.showModalResume();
    }

    /**
     * Renders the Review Panel's Candidate Feedback card, with each Panelist's final view collapsed.
     * Skipped or absent feedback (scoring-only runs, older reports) renders nothing.
     * @param {Object} feedback - The report's candidate_feedback object.
     * @returns {string} HTML for the card, or '' when there is nothing to show.
     */
    renderCandidateFeedback(feedback) {
        if (!feedback) return '';
        if (feedback.status === 'failed') {
            return `
                <div class="modal-feedback-card">
                    <div class="modal-dim-title">${FEEDBACK_TITLE}</div>
                    <div class="modal-feedback-failed">${FEEDBACK_FAILED_LABEL}</div>
                </div>
            `;
        }
        if (feedback.status !== 'ok') return '';

        // A titled bullet list, or nothing when the list is empty
        const section = (title, items, cls) => {
            const list = (items || []).map(i => `<li>${this.escapeHtml(i)}</li>`).join('');
            return list ? `<div class="modal-section-title">${title}</div><ul class="modal-bullets ${cls}">${list}</ul>` : '';
        };
        const views = feedback.panelist_views || {};
        const panelistViewsHtml = Object.keys(PANELIST_NAMES)
            .filter(key => views[key])
            .map(key => `
                <details class="modal-panelist-view">
                    <summary>${PANELIST_NAMES[key]}</summary>
                    <div class="modal-panelist-view-text">${this.escapeHtml(views[key])}</div>
                </details>
            `).join('');

        return `
            <div class="modal-feedback-card">
                <div class="modal-dim-title">${FEEDBACK_TITLE}</div>
                ${feedback.summary ? `<div class="modal-reasoning-box">${this.escapeHtml(feedback.summary)}</div>` : ''}
                ${section('Điểm mạnh:', feedback.strengths, 'strengths')}
                ${section('Điểm yếu và kỹ năng còn thiếu:', feedback.weaknesses, 'gaps')}
                ${panelistViewsHtml ? `<div class="modal-section-title">Ý kiến từng thành viên hội đồng:</div>${panelistViewsHtml}` : ''}
            </div>
        `;
    }

    /**
     * Closes candidate detail modal dialog and restores keyboard focus.
     */
    closeCandidateModal() {
        if (!this.candModal) return;
        this.candModal.style.display = 'none';
        document.body.style.overflow = '';
        this.currentModalCandidate = null;
        // Drops the resume iframe, so the next candidate opens on the evaluation view
        this.modalEvaluationHtml = '';
        this.showModalEvaluation();

        if (this.lastFocusedElement && typeof this.lastFocusedElement.focus === 'function') {
            this.lastFocusedElement.focus();
        }
    }

    /**
     * Downloads the candidate's evaluation report as a PDF, with the resume PDF appended when stored.
     */
    async downloadModalReportPdf() {
        const cand = this.currentModalCandidate;
        const btn = this.modalBtnDownload;
        if (!cand || !cand.filename || !btn) return;

        const originalHtml = btn.innerHTML;
        btn.disabled = true;
        btn.textContent = 'Đang tạo PDF…';
        try {
            const blob = await API.getReportPdf(cand.filename);
            const url = URL.createObjectURL(blob);
            const anchor = document.createElement('a');
            anchor.href = url;
            anchor.download = `${cand.filename.replace(/\.json$/i, '')}_danh_gia.pdf`;
            document.body.appendChild(anchor);
            anchor.click();
            anchor.remove();
            setTimeout(() => URL.revokeObjectURL(url), 1000);
        } catch (err) {
            alert(err.message);
        } finally {
            btn.disabled = false;
            btn.innerHTML = originalHtml;
        }
    }

    escapeHtml(str) {
        if (!str) return '';
        return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }
}
