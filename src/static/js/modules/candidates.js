/**
 * ==============================================================================
 * Candidate Pool Controller (Harmonious Executive Light Theme)
 * ==============================================================================
 * Description: Manages candidate evaluation pool browsing, search filtering,
 *              sorting by score/date/name, summary statistics, and candidate
 *              detail modal overlay.
 */

import { API } from './api.js';

export class CandidatePoolController {
    constructor() {
        this.allCandidatesData = [];
        this.currentModalCandidate = null;

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
        this.modalCandRole = document.getElementById('modal-cand-role') || document.getElementById('modal-cand-file');
        this.modalCandBody = document.getElementById('modal-cand-body');
        this.modalCloseBtn = document.getElementById('modal-close-btn');
        this.modalBtnDownload = document.getElementById('modal-btn-download');
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
            this.modalBtnDownload.addEventListener('click', () => this.downloadModalCandidate());
        }
    }

    /**
     * Fetches candidate evaluation reports from eval_results/ and renders pool grid.
     */
    async loadCandidatePool() {
        if (!this.candCardsGrid) return;
        this.candCardsGrid.innerHTML = '<div class="loading-state">Loading candidate evaluations...</div>';

        try {
            const data = await API.getEvalResults();
            this.allCandidatesData = data.evaluations || [];
            this.updateSummaryStats(this.allCandidatesData);
            this.applyCandidateFiltersAndSort();
        } catch (err) {
            this.candCardsGrid.innerHTML = `<div class="error-state">Failed to load candidates: ${err.message}</div>`;
        }
    }

    /**
     * Calculates candidate pool summary metrics (Total, Strong, Potential, Low, Reject, Avg Score).
     * @param {Array<Object>} candidates - List of candidate evaluation reports.
     */
    updateSummaryStats(candidates) {
        const total = candidates.length;
        let strong = 0, potential = 0, low = 0, reject = 0;
        let scoreSum = 0;

        candidates.forEach(c => {
            const score = c.overall_score || 0;
            scoreSum += score;
            const rec = c.match_recommendation || '';
            if (rec === 'STRONG_MATCH' || score >= 85) strong++;
            else if (rec === 'POTENTIAL_MATCH' || score >= 70) potential++;
            else if (rec === 'LOW_MATCH' || score >= 55) low++;
            else reject++;
        });

        const avgScore = total > 0 ? (scoreSum / total).toFixed(1) : '0.0';

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
                const rec = cand.match_recommendation || '';
                const score = cand.overall_score || 0;
                if (statusFilter === 'STRONG_MATCH' && rec !== 'STRONG_MATCH' && score < 85) return false;
                if (statusFilter === 'POTENTIAL_MATCH' && rec !== 'POTENTIAL_MATCH' && (score < 70 || score >= 85)) return false;
                if (statusFilter === 'LOW_MATCH' && rec !== 'LOW_MATCH' && (score < 55 || score >= 70)) return false;
                if (statusFilter === 'REJECT' && rec !== 'REJECT' && score >= 55) return false;
            }

            if (query) {
                const name = (cand.candidate_identifier || cand.candidate_name || '').toLowerCase();
                const title = (cand.title || '').toLowerCase();
                const email = (cand.candidate_email || cand.email || '').toLowerCase();
                if (!name.includes(query) && !title.includes(query) && !email.includes(query)) {
                    return false;
                }
            }
            return true;
        });

        filtered.sort((a, b) => {
            const scoreA = a.overall_score || 0;
            const scoreB = b.overall_score || 0;
            const nameA = (a.candidate_identifier || a.candidate_name || '').toLowerCase();
            const nameB = (b.candidate_identifier || b.candidate_name || '').toLowerCase();
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
                    <h3 style="color: #0F172A; font-weight: 800;">No Candidates Match Search</h3>
                    <p style="color: #334155;">Try adjusting your search criteria or status filter.</p>
                </div>
            `;
            return;
        }

        const sortBy = this.candSortBy ? this.candSortBy.value : 'evaluation_order';

        if (sortBy === 'evaluation_order') {
            const tiers = {
                1: { title: 'Resume Tier 1 (Priority Candidates)', badgeClass: 'tier-badge-1', blockClass: 'tier-1-block', items: [] },
                2: { title: 'Resume Tier 2 (Secondary Candidates)', badgeClass: 'tier-badge-2', blockClass: 'tier-2-block', items: [] },
                3: { title: 'Resume Tier 3 (General Pool)', badgeClass: 'tier-badge-3', blockClass: 'tier-3-block', items: [] }
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
                            <span class="tier-badge ${group.badgeClass}">Tier ${tNum}</span>
                        </div>
                        <span style="font-size: 0.88rem; font-weight: 700; color: #334155;">${group.items.length} Candidate(s)</span>
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

        const name = cand.candidate_identifier || cand.candidate_name || cand.resume_name || 'Candidate';
        const title = cand.title || 'Candidate Dossier';
        const email = cand.candidate_email || cand.email || (cand.candidate_identifier && cand.candidate_identifier.includes('@') ? cand.candidate_identifier : '');
        const numScore = parseFloat(cand.overall_score !== undefined ? cand.overall_score : 0) || 0;
        const score = numScore.toFixed(1);
        const rec = cand.match_recommendation || (numScore >= 85 ? 'STRONG_MATCH' : (numScore >= 70 ? 'POTENTIAL_MATCH' : (numScore >= 55 ? 'LOW_MATCH' : 'REJECT')));

        let recClass = 'match-potential';
        let recText = 'POTENTIAL MATCH';
        if (rec === 'STRONG_MATCH' || numScore >= 85) { recClass = 'match-strong'; recText = 'STRONG MATCH'; }
        else if (rec === 'POTENTIAL_MATCH' || numScore >= 70) { recClass = 'match-potential'; recText = 'POTENTIAL MATCH'; }
        else if (rec === 'LOW_MATCH' || numScore >= 55) { recClass = 'match-low'; recText = 'LOW MATCH'; }
        else { recClass = 'match-reject'; recText = 'REJECT'; }

        const tierBadgeClass = cand.tier === 1 ? 'tier-badge-1' : (cand.tier === 2 ? 'tier-badge-2' : 'tier-badge-3');
        const tierLabel = cand.tier ? `Tier ${cand.tier}` : 'Tier 3';

        card.setAttribute('aria-label', `Candidate: ${name}, Role: ${title}, Email: ${email || 'N/A'}, Score: ${score}/100, ${recText}`);

        // Vital Info: Breakdown of Match Score Progress Bars
        const dims = cand.dimension_scores || {};
        let dimsBreakdownHtml = '';
        const dimKeys = ['technical_skills', 'work_experience', 'seniority_title', 'education_certifications', 'hidden_culture'];
        const dimShortNames = {
            'technical_skills': 'Tech Skills',
            'work_experience': 'Work Experience',
            'seniority_title': 'Seniority Level',
            'education_certifications': 'Education & Certs',
            'hidden_culture': 'Culture & Soft Skills'
        };

        dimKeys.forEach(k => {
            if (dims[k]) {
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
        const ocrPillHtml = isOcrReview ? `<span class="badge-ocr-review" title="No text layer found in PDF. OCR was used for text extraction. High-level manual HR review required.">⚠️ INTENSIVE HR REVIEW (OCR)</span>` : '';

        const emailChipHtml = email ? `
            <a href="mailto:${this.escapeHtml(email)}" class="cand-email-chip" onclick="event.stopPropagation()" title="Send email to ${this.escapeHtml(email)}">
                <svg viewBox="0 0 24 24"><path d="M20 4H4c-1.1 0-1.99.9-1.99 2L2 18c0 1.1.9 2 2 2h16c1.1 0 2-.9 2-2V6c0-1.1-.9-2-2-2zm0 4l-8 5-8-5V6l8 5 8-5v2z"/></svg>
                ${this.escapeHtml(email)}
            </a>
        ` : '';

        card.innerHTML = `
            <div class="cand-card-header">
                <div class="cand-info-group">
                    <h3>${this.escapeHtml(name)}</h3>
                    <span class="cand-role">${this.escapeHtml(title)}</span>
                    ${emailChipHtml}
                </div>
                <div class="cand-score-badge">
                    <span class="cand-score-val" style="color: ${numScore >= 85 ? '#059669' : numScore >= 70 ? '#0284C7' : numScore >= 55 ? '#D97706' : '#DC2626'};">${score}</span>
                    <span class="cand-score-lbl">Score</span>
                </div>
            </div>

            <div class="cand-badges-row">
                <span class="match-pill ${recClass}">${recText}</span>
                <span class="tier-badge ${tierBadgeClass}">${tierLabel}</span>
                ${ocrPillHtml}
            </div>

            ${dimsBreakdownHtml ? `<div class="cand-dimensions-breakdown">${dimsBreakdownHtml}</div>` : ''}

            <div class="cand-card-footer">
                <div class="summary-badges">
                    <span class="badge-strength-cnt">✓ ${cand.summary?.total_strengths || 0} Strengths</span>
                    <span class="badge-gap-cnt">⚠ ${cand.summary?.total_gaps || 0} Gaps</span>
                </div>
                <button class="btn btn-sm btn-secondary cand-inspect-btn" type="button" tabindex="-1">Inspect Dossier →</button>
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

        const name = cand.candidate_identifier || cand.candidate_name || cand.resume_name || 'Candidate';
        const title = cand.title || 'Candidate Dossier';
        const email = cand.candidate_email || cand.email || (cand.candidate_identifier && cand.candidate_identifier.includes('@') ? cand.candidate_identifier : '');
        const numScore = parseFloat(cand.overall_score || 0);
        const score = numScore.toFixed(1);
        const rec = cand.match_recommendation || 'POTENTIAL_MATCH';

        if (this.modalCandName) this.modalCandName.textContent = name;
        if (this.modalCandRole) this.modalCandRole.textContent = email ? `${title} • ${email}` : title;

        let recClass = 'match-potential';
        let recText = 'POTENTIAL MATCH';
        if (rec === 'STRONG_MATCH' || numScore >= 85) { recClass = 'match-strong'; recText = 'STRONG MATCH'; }
        else if (rec === 'POTENTIAL_MATCH' || numScore >= 70) { recClass = 'match-potential'; recText = 'POTENTIAL MATCH'; }
        else if (rec === 'LOW_MATCH' || numScore >= 55) { recClass = 'match-low'; recText = 'LOW MATCH'; }
        else { recClass = 'match-reject'; recText = 'REJECT'; }

        const dims = cand.dimension_scores || {};
        let dimCardsHtml = '';

        Object.keys(dims).forEach(catKey => {
            const d = dims[catKey];
            const catName = d.category_name || catKey;
            const catWeight = ((d.weight || 0.2) * 100).toFixed(0);
            const dScore = (d.score || 0).toFixed(1);

            let fillClass = 'fill-mid';
            if (d.score >= 85) fillClass = 'fill-high';
            else if (d.score >= 70) fillClass = 'fill-mid';
            else if (d.score >= 55) fillClass = 'fill-low';
            else fillClass = 'fill-reject';

            const strengthsList = (d.strengths || []).map(s => `<li>${this.escapeHtml(s)}</li>`).join('');
            const gapsList = (d.gaps || []).map(g => `<li>${this.escapeHtml(g)}</li>`).join('');
            const quotesList = (d.evidence_quotes || []).map(q => `<div class="modal-quote-box">"${this.escapeHtml(q)}"</div>`).join('');
            const reasoningText = d.reasoning_summary ? this.escapeHtml(d.reasoning_summary) : '';

            dimCardsHtml += `
                <div class="modal-dim-card">
                    <div class="modal-dim-header">
                        <div class="modal-dim-title">
                            ${this.escapeHtml(catName)}
                            <span class="modal-dim-weight">Weight: ${catWeight}%</span>
                        </div>
                        <div>
                            <span class="dim-score-pill">${dScore} / 100</span>
                        </div>
                    </div>
                    <div class="modal-dim-progress">
                        <div class="modal-dim-progress-fill ${fillClass}" style="width: ${Math.min(100, Math.max(5, d.score))}%;"></div>
                    </div>
                    ${reasoningText ? `<div class="modal-reasoning-title">🧠 AI Reasoning (Lập luận đánh giá):</div><div class="modal-reasoning-box">${reasoningText}</div>` : ''}
                    ${strengthsList ? `<div class="modal-section-title">Key Strengths:</div><ul class="modal-bullets strengths">${strengthsList}</ul>` : ''}
                    ${gapsList ? `<div class="modal-section-title">Identified Gaps:</div><ul class="modal-bullets gaps">${gapsList}</ul>` : ''}
                    ${quotesList ? `<div class="modal-section-title">Evidence Quotes:</div>${quotesList}` : ''}
                </div>
            `;
        });

        const isOcrReview = cand.ocr_applied || cand.intensive_hr_review_required || (Array.isArray(cand.warning) && cand.warning.some(w => typeof w === 'string' && w.includes('OCR')));
        const ocrAlertBanner = isOcrReview ? `
            <div class="modal-ocr-alert-banner">
                <div class="modal-ocr-alert-icon">⚠️</div>
                <div class="modal-ocr-alert-content">
                    <strong>INTENSIVE HR REVIEW REQUIRED (OCR APPLIED)</strong>
                    <p>This resume contained no native text layer (scanned or image PDF). Optical Character Recognition (OCR) was used to extract candidate information. Please perform thorough manual HR verification of extracted details.</p>
                </div>
            </div>
        ` : '';

        const emailLink = email ? `<a href="mailto:${this.escapeHtml(email)}" style="color: var(--color-secondary); font-weight: 700; text-decoration: underline;">${this.escapeHtml(email)}</a>` : '';

        this.modalCandBody.innerHTML = `
            ${ocrAlertBanner}
            <div class="modal-hero-banner">
                <div>
                    <h2>${this.escapeHtml(name)} <span class="match-pill ${recClass}">${recText}</span></h2>
                    <p>${this.escapeHtml(title)} ${emailLink ? `• ${emailLink}` : ''} • Evaluated on ${cand.evaluated_at ? new Date(cand.evaluated_at).toLocaleString() : 'N/A'}</p>
                </div>
                <div class="modal-score-box">
                    <span class="modal-score-number" style="color: ${numScore >= 85 ? '#059669' : numScore >= 70 ? '#0284C7' : numScore >= 55 ? '#D97706' : '#DC2626'};">${score}</span>
                    <span style="font-size:0.82rem; color:#334155; font-weight:800; text-transform:uppercase; font-family:var(--font-mono);">Overall Score</span>
                </div>
            </div>
            <div class="modal-dim-grid">${dimCardsHtml}</div>
        `;

        this.candModal.style.display = 'flex';
        document.body.style.overflow = 'hidden';

        if (this.modalCloseBtn) {
            this.modalCloseBtn.focus();
        }
    }

    /**
     * Closes candidate detail modal dialog and restores keyboard focus.
     */
    closeCandidateModal() {
        if (!this.candModal) return;
        this.candModal.style.display = 'none';
        document.body.style.overflow = '';
        this.currentModalCandidate = null;

        if (this.lastFocusedElement && typeof this.lastFocusedElement.focus === 'function') {
            this.lastFocusedElement.focus();
        }
    }

    /**
     * Downloads candidate evaluation JSON report file.
     */
    downloadModalCandidate() {
        if (!this.currentModalCandidate) return;
        const candidateName = (this.currentModalCandidate.candidate_identifier || this.currentModalCandidate.candidate_name || 'candidate').replace(/\s+/g, '_');
        const dataStr = "data:text/json;charset=utf-8," + encodeURIComponent(JSON.stringify(this.currentModalCandidate, null, 2));
        const anchor = document.createElement('a');
        anchor.setAttribute("href", dataStr);
        anchor.setAttribute("download", `${candidateName}_evaluation.json`);
        document.body.appendChild(anchor);
        anchor.click();
        anchor.remove();
    }

    escapeHtml(str) {
        if (!str) return '';
        return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }
}
