/**
 * ==============================================================================
 * Candidate Pool Controller
 * ==============================================================================
 * Description: Manages candidate evaluation pool browsing, search filtering,
 *              sorting by score/date/name, summary statistics, and opening a
 *              candidate's full report in the shared report view.
 */

import { API } from './api.js';
import { CATEGORY_NAMES } from './criteria-editor.js';
import { CandidateReportView } from './candidate-report-view.js';
import { byId } from './dom.js';
import { html } from './html.js';
import {
    KIND, reportKind, isScored, isMissingPosition, mustHaveMisses, shownCategories, matchBand, recommendationLabel,
    scoreBand, overallScoreTone, tierLabels, tierRank, groupIntoSections, candidateIdentity,
    SCANNED_RESUME_MESSAGE, MISSING_POSITION_LABEL, MISSING_POSITION_MESSAGE
} from './report.js';

/**
 * Sort group when sorting by score: ranked candidates first, then Must-have Rejections (scored but out),
 * then unscored reports.
 */
function rankGroup(r) {
    switch (reportKind(r)) {
        case KIND.RANKED: return 0;
        case KIND.REJECTED: return 1;
        default: return 2;
    }
}

const byName = (a, b) => candidateIdentity(a).name.toLowerCase().localeCompare(candidateIdentity(b).name.toLowerCase());
const evaluatedTime = r => new Date(r.evaluated_at).getTime();

// Comparators for the sort menu (#cand-sort-by); each computes only the keys it needs
const SORTERS = {
    evaluation_order: (a, b) => a.tier - b.tier || a.tier_order - b.tier_order || byName(a, b),
    score_desc: (a, b) => rankGroup(a) - rankGroup(b) || b.overall_score - a.overall_score,
    score_asc: (a, b) => rankGroup(a) - rankGroup(b) || a.overall_score - b.overall_score,
    name_asc: byName,
    name_desc: (a, b) => byName(b, a),
    date_desc: (a, b) => evaluatedTime(b) - evaluatedTime(a)
};

/** Whether a report passes the status filter. A Must-have Rejection is listed under "Loại"; unscored reports only under all. */
function matchesStatusFilter(r, filter) {
    if (filter === 'ALL') return true;
    const band = matchBand(r);
    return band === filter || (filter === 'REJECT' && band === 'MUST_HAVE_REJECTED');
}

export class CandidatePoolController {
    constructor() {
        this.allCandidatesData = [];
        this.techMode = false;
        this.reportView = new CandidateReportView();

        this.initDOMElements();
        this.initEvents();
        this.loadCandidatePool();
    }

    /**
     * Binds DOM element references required for the candidate pool toolbar, stats and grid.
     */
    initDOMElements() {
        this.btnRefreshCandidates = byId('btn-refresh-candidates');
        this.candSearchInput = byId('cand-search-input');
        this.candFilterStatus = byId('cand-filter-status');
        this.candSortBy = byId('cand-sort-by');
        this.candCardsGrid = byId('cand-cards-grid');

        this.statTotal = byId('cand-stat-total');
        this.statStrong = byId('cand-stat-strong');
        this.statPotential = byId('cand-stat-potential');
        this.statLow = byId('cand-stat-low');
        this.statReject = byId('cand-stat-reject');
        this.statAvg = byId('cand-stat-avg');
    }

    /**
     * Binds event listeners for search inputs and filter dropdowns.
     */
    initEvents() {
        this.btnRefreshCandidates.addEventListener('click', () => this.loadCandidatePool());
        this.candSearchInput.addEventListener('input', () => this.applyCandidateFiltersAndSort());
        this.candFilterStatus.addEventListener('change', () => this.applyCandidateFiltersAndSort());
        this.candSortBy.addEventListener('change', () => this.applyCandidateFiltersAndSort());
    }

    /**
     * Fetches candidate evaluation reports from eval_results/ and renders pool grid.
     */
    async loadCandidatePool() {
        this.candCardsGrid.innerHTML = '<div class="loading-state">Đang tải kết quả đánh giá ứng viên...</div>';

        try {
            const data = await API.getEvalResults();
            this.allCandidatesData = data.evaluations;
            this.techMode = data.tech_mode === true;
            this.updateSummaryStats(this.allCandidatesData);
            this.applyCandidateFiltersAndSort();
        } catch (err) {
            this.candCardsGrid.innerHTML = html`<div class="error-state">Không tải được danh sách ứng viên: ${err.message}</div>`;
        }
    }

    /**
     * Calculates candidate pool summary metrics (Total, Strong, Potential, Low, Reject, Avg Score).
     * A Must-have Rejection counts as "Loại" and stays out of the average; unscored reports count only in the total.
     * @param {Array<Object>} candidates - List of candidate evaluation reports.
     */
    updateSummaryStats(candidates) {
        const counts = { STRONG_MATCH: 0, POTENTIAL_MATCH: 0, LOW_MATCH: 0, REJECT: 0, MUST_HAVE_REJECTED: 0, ERROR: 0 };
        candidates.forEach(c => { counts[matchBand(c)]++; });
        const ranked = candidates.filter(c => reportKind(c) === KIND.RANKED);
        const avgScore = ranked.length > 0
            ? (ranked.reduce((acc, c) => acc + c.overall_score, 0) / ranked.length).toFixed(1)
            : '0.0';

        this.statTotal.textContent = candidates.length;
        this.statStrong.textContent = counts.STRONG_MATCH;
        this.statPotential.textContent = counts.POTENTIAL_MATCH;
        this.statLow.textContent = counts.LOW_MATCH;
        this.statReject.textContent = counts.REJECT + counts.MUST_HAVE_REJECTED;
        this.statAvg.textContent = avgScore;
    }

    /**
     * Applies search query, status filtering, and sorting transforms on candidate list.
     */
    applyCandidateFiltersAndSort() {
        const query = this.candSearchInput.value.toLowerCase().trim();
        const statusFilter = this.candFilterStatus.value;

        const filtered = this.allCandidatesData.filter(cand => {
            if (!matchesStatusFilter(cand, statusFilter)) return false;
            if (!query) return true;
            const { name, contactEmail } = candidateIdentity(cand);
            return name.toLowerCase().includes(query) || contactEmail.toLowerCase().includes(query);
        });
        filtered.sort(SORTERS[this.candSortBy.value]);

        this.renderCandidateCards(filtered);
    }

    /**
     * Renders filtered candidate cards into grid container: in evaluation-order sections when sorted that way,
     * else as one flat grid.
     * @param {Array<Object>} candidates - Filtered, sorted candidate objects.
     */
    renderCandidateCards(candidates) {
        this.candCardsGrid.innerHTML = '';
        if (candidates.length === 0) {
            this.candCardsGrid.innerHTML = `
                <div class="empty-state empty-state--grid">
                    <div class="empty-icon">🔍</div>
                    <h3>Không có ứng viên phù hợp</h3>
                    <p>Hãy thử đổi từ khóa tìm kiếm hoặc bộ lọc trạng thái.</p>
                </div>
            `;
            return;
        }

        if (this.candSortBy.value !== 'evaluation_order') {
            candidates.forEach(cand => this.candCardsGrid.appendChild(this.buildCandidateCard(cand)));
            return;
        }

        groupIntoSections(candidates, this.techMode).forEach(section => {
            const tierBlock = document.createElement('div');
            tierBlock.className = `cand-tier-block tier-${section.tone}-block`;
            tierBlock.innerHTML = html`
                <div class="cand-tier-header">
                    <div class="cand-tier-title-group">
                        <h3>${section.title}</h3>
                        <span class="tier-badge tier-badge-${section.tone}">${section.badge}</span>
                    </div>
                    <span class="cand-tier-count">${section.items.length} ứng viên</span>
                </div>
                <div class="tier-grid cand-cards-grid"></div>
            `;
            const tierGrid = tierBlock.querySelector('.tier-grid');
            section.items.forEach(cand => tierGrid.appendChild(this.buildCandidateCard(cand)));
            this.candCardsGrid.appendChild(tierBlock);
        });
    }

    /**
     * One candidate's card: name, email, score, match and tier badges, Category bars; opens the full report.
     * @param {Object} cand - Candidate evaluation report.
     * @returns {HTMLElement}
     */
    buildCandidateCard(cand) {
        const card = document.createElement('div');
        card.className = 'cand-card';
        card.tabIndex = 0;
        card.setAttribute('role', 'button');

        const { name, email, contactEmail } = candidateIdentity(cand);
        const scored = isScored(cand);
        const score = Number(cand.overall_score).toFixed(1);
        const recText = recommendationLabel(cand);
        const scanned = reportKind(cand) === KIND.SCANNED;
        const rank = scanned ? 0 : tierRank(cand);
        const missing = mustHaveMisses(cand);

        card.setAttribute('aria-label', scored
            ? `Ứng viên: ${name}, Email: ${contactEmail || 'Không có'}, Điểm: ${score}/100, ${recText}`
            : `Ứng viên: ${name}, Email: ${contactEmail || 'Không có'}, ${recText}`);

        // Vital Info: Breakdown of Match Score Progress Bars, in Category order
        const shown = scored ? shownCategories(cand) : {};
        const dimBars = Object.keys(CATEGORY_NAMES).filter(k => shown[k]).map(k => {
            const dScore = Math.round(shown[k].score);
            return html`
                <div class="dim-bar-item">
                    <div class="dim-bar-header">
                        <span class="dim-bar-name">${CATEGORY_NAMES[k]}</span>
                        <span class="dim-bar-val">${dScore}/100</span>
                    </div>
                    <div class="dim-progress-track">
                        <div class="dim-progress-fill bar-fill--${scoreBand(dScore)}" style="width: ${Math.min(100, Math.max(5, dScore))}%;"></div>
                    </div>
                </div>
            `;
        });

        card.innerHTML = html`
            <div class="cand-card-header">
                <div class="cand-info-group">
                    <h3>${name}</h3>
                    ${email && html`<a href="mailto:${email}" class="cand-email" title="Gửi email tới ${email}">${email}</a>`}
                </div>
                <div class="cand-score-badge">
                    <span class="cand-score-val score--${overallScoreTone(cand)}">${scored ? score : '—'}</span>
                    <span class="cand-score-lbl">Điểm</span>
                </div>
            </div>

            <div class="cand-badges-row">
                <span class="match-pill band-${matchBand(cand)}">${recText}</span>
                ${rank > 0 && html`<span class="tier-rank-badge" title="Thứ hạng trong danh sách đánh giá">#${rank}</span>`}
                <span class="tier-badge tier-badge-${cand.tier}">${tierLabels(cand.tier, this.techMode).badge}</span>
                ${scanned && html`<span class="badge-warning" title="${SCANNED_RESUME_MESSAGE}">⚠️ Cần ứng viên gửi PDF có chữ</span>`}
                ${isMissingPosition(cand) && html`<span class="badge-warning" title="${MISSING_POSITION_MESSAGE}">⚠️ ${MISSING_POSITION_LABEL}</span>`}
            </div>

            ${missing.length > 0 && html`<div class="cand-must-have-rejection"><strong>Thiếu tiêu chí bắt buộc:</strong> ${missing.map(m => m.criterion).join('; ')}</div>`}

            ${dimBars.length > 0 && html`<div class="cand-dimensions-breakdown">${dimBars}</div>`}

            <div class="cand-card-footer">
                <button class="btn btn-sm btn-secondary cand-inspect-btn" type="button" tabindex="-1">Xem hồ sơ →</button>
            </div>
        `;

        // The email link opens the mail app, not the report
        card.querySelector('.cand-email')?.addEventListener('click', (e) => e.stopPropagation());
        card.addEventListener('click', () => this.reportView.open(cand, card));
        card.addEventListener('keydown', (e) => {
            if (e.key === 'Enter' || e.key === ' ') {
                e.preventDefault();
                this.reportView.open(cand, card);
            }
        });
        return card;
    }
}
