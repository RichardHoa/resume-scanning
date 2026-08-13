/**
 * ==============================================================================
 * Step 2: HR Evaluator Controller
 * ==============================================================================
 * Description: Manages standard & hidden job criteria input, candidate selection,
 *              batch evaluation execution, leaderboard generation, and 5-dimension
 *              score breakdown rendering.
 * Line Count: ~240 lines (Strict Limit: < 500 lines)
 */

import { API } from './api.js';

export class EvaluatorController {
    constructor() {
        this.scannedResumes = [];
        this.selectedResumesSet = new Set();
        this.lastResults = [];

        this.initDOMElements();
        this.initEvents();
    }

    /**
     * Binds DOM element references required for batch resume evaluation.
     */
    initDOMElements() {
        this.scannedContainer = document.getElementById('scanned-resumes-container');
        this.chkSelectAll = document.getElementById('chk-select-all');
        this.selectedCountBadge = document.getElementById('selected-count-badge');
        this.btnRunEval = document.getElementById('btn-run-eval');
        this.btnRefreshResumes = document.getElementById('btn-refresh-resumes');

        this.placeholderPanel = document.getElementById('eval-placeholder-panel');
        this.resultsPanel = document.getElementById('eval-results-panel');
        this.tierBlocksContainer = document.getElementById('tier-blocks-container');
        this.evalTotalBadge = document.getElementById('eval-total-badge');
        this.detailView = document.getElementById('candidate-detail-view');

        this.loaderOverlay = document.getElementById('loader-overlay');
        this.loaderTitle = document.getElementById('loader-title');
        this.loaderDesc = document.getElementById('loader-desc');
    }

    /**
     * Binds event listeners for checkbox selection, refresh buttons, and evaluation triggers.
     */
    initEvents() {
        if (this.btnRefreshResumes) {
            this.btnRefreshResumes.addEventListener('click', () => this.loadScannedResumes());
        }

        if (this.chkSelectAll) {
            this.chkSelectAll.addEventListener('change', () => {
                this.selectedResumesSet.clear();
                if (this.chkSelectAll.checked) {
                    this.scannedResumes.forEach(r => this.selectedResumesSet.add(r.filename));
                }
                this.renderScannedList();
                this.updateSelectedCount();
            });
        }

        if (this.btnRunEval) {
            this.btnRunEval.addEventListener('click', () => this.runEvaluation());
        }
    }

    /**
     * Fetches scanned resumes from backend and updates selection state.
     */
    async loadScannedResumes() {
        if (!this.scannedContainer) return;
        this.scannedContainer.innerHTML = '<div class="loading-state">Loading scanned resumes...</div>';
        this.selectedResumesSet.clear();
        if (this.chkSelectAll) this.chkSelectAll.checked = false;
        this.updateSelectedCount();

        try {
            const data = await API.getScannedResumes();
            this.scannedResumes = data.resumes || [];
            this.orderActive = data.evaluation_order_active;
            this.orderPath = data.evaluation_order_path;
            this.tier1Count = data.tier1_count || 0;
            this.tier2Count = data.tier2_count || 0;

            if (this.scannedResumes.length === 0) {
                this.scannedContainer.innerHTML = '<div class="empty-state" style="padding: 1.5rem 0;">No scanned resumes found. Upload PDF resumes in Step 1 first.</div>';
                return;
            }
            this.renderScannedList();
        } catch (err) {
            this.scannedContainer.innerHTML = `<div class="error-state">Failed to load resumes: ${err.message}</div>`;
        }
    }

    /**
     * Renders candidate checkbox cards list in left panel, grouped into Tier 1, Tier 2, and Tier 3 blocks.
     */
    renderScannedList() {
        this.scannedContainer.innerHTML = '';

        // Render Secret Order Status Banner
        const banner = document.createElement('div');
        banner.style.cssText = 'padding: 8px 12px; border-radius: 8px; font-size: 0.78rem; font-weight: 600; margin-bottom: 10px; display: flex; align-items: center; justify-content: space-between;';
        if (this.orderActive) {
            banner.style.background = 'rgba(16, 185, 129, 0.12)';
            banner.style.border = '1px solid rgba(16, 185, 129, 0.3)';
            banner.style.color = '#34d399';
            banner.innerHTML = `<span>🔒 Secret Order: Active</span><span style="font-size:0.72rem; opacity:0.85;">Tier 1: ${this.tier1Count} • Tier 2: ${this.tier2Count}</span>`;
        } else {
            banner.style.background = 'rgba(245, 158, 11, 0.12)';
            banner.style.border = '1px solid rgba(245, 158, 11, 0.3)';
            banner.style.color = '#fbbf24';
            banner.innerHTML = `<span>⚠️ Secret Order: File Not Found</span><span style="font-size:0.72rem;">evaluation_order.txt</span>`;
        }
        this.scannedContainer.appendChild(banner);

        // Group resumes into Tiers
        const tiers = {
            1: { title: 'Resume Tier 1 (Priority)', badgeClass: 'tier-badge-1', items: [] },
            2: { title: 'Resume Tier 2 (Secondary)', badgeClass: 'tier-badge-2', items: [] },
            3: { title: 'Resume Tier 3 (Unlisted)', badgeClass: 'tier-badge-3', items: [] }
        };

        this.scannedResumes.forEach(r => {
            const t = r.tier || 3;
            if (!tiers[t]) tiers[t] = tiers[3];
            tiers[t].items.push(r);
        });

        [1, 2, 3].forEach(tNum => {
            const group = tiers[tNum];
            if (group.items.length === 0) return;

            const block = document.createElement('div');
            block.className = `scanned-tier-block tier-${tNum}-block`;
            block.style.cssText = 'background: var(--bg-main); border: 1px solid var(--border); border-radius: 12px; padding: 12px; margin-bottom: 12px;';

            block.innerHTML = `
                <div class="tier-section-title" style="margin-top:0;">
                    <span>${group.title}</span>
                    <span class="tier-badge ${group.badgeClass}">${group.items.length} candidate(s)</span>
                </div>
                <div class="tier-items-list" style="display: flex; flex-direction: column; gap: 8px; margin-top: 8px;"></div>
            `;

            const itemsContainer = block.querySelector('.tier-items-list');

            group.items.forEach(resItem => {
                const isSel = this.selectedResumesSet.has(resItem.filename);
                const card = document.createElement('div');
                card.className = `resume-card-item ${isSel ? 'selected' : ''}`;
                card.innerHTML = `
                    <input type="checkbox" class="chk-resume" data-file="${resItem.filename}" ${isSel ? 'checked' : ''}>
                    <div class="resume-info">
                        <span class="resume-title">${this.escapeHtml(resItem.filename)}</span>
                        <span class="resume-meta">✉ ${this.escapeHtml(resItem.email)} • ${this.escapeHtml(resItem.title)}</span>
                    </div>
                `;

                const chk = card.querySelector('.chk-resume');
                card.addEventListener('click', (e) => {
                    if (e.target !== chk) chk.checked = !chk.checked;
                    if (chk.checked) {
                        this.selectedResumesSet.add(resItem.filename);
                        card.classList.add('selected');
                    } else {
                        this.selectedResumesSet.delete(resItem.filename);
                        card.classList.remove('selected');
                    }
                    this.updateSelectedCount();
                });

                itemsContainer.appendChild(card);
            });

            this.scannedContainer.appendChild(block);
        });
    }

    /**
     * Updates selected count badge and enables/disables evaluation submit button.
     */
    updateSelectedCount() {
        if (this.selectedCountBadge) {
            this.selectedCountBadge.textContent = `${this.selectedResumesSet.size} selected`;
        }
        if (this.btnRunEval) {
            this.btnRunEval.disabled = this.selectedResumesSet.size === 0;
        }
    }

    /**
     * Submits job criteria and candidate selection to run batch AI evaluation.
     */
    async runEvaluation() {
        const stdReq = document.getElementById('hr-std-req').value;
        const hiddenReq = document.getElementById('hr-hidden-req').value;
        const filenames = Array.from(this.selectedResumesSet);

        if (filenames.length === 0) {
            alert('Please select at least one candidate resume.');
            return;
        }

        if (this.loaderOverlay) {
            this.loaderTitle.textContent = `Evaluating ${filenames.length} Candidate(s)...`;
            this.loaderDesc.textContent = 'Running evaluation strictly in secret evaluation_order...';
            this.loaderOverlay.style.display = 'flex';
        }

        try {
            const data = await API.evaluateBatch(stdReq, hiddenReq, filenames);
            if (data.results) {
                this.renderDashboard(data.results);
            } else {
                alert('Evaluation failed.');
            }
        } catch (err) {
            alert('Evaluation error: ' + err.message);
        } finally {
            if (this.loaderOverlay) this.loaderOverlay.style.display = 'none';
        }
    }

    /**
     * Renders candidate evaluation results divided into separate Resume Tier 1, Tier 2, and Tier 3 blocks.
     * Candidates within each block maintain exact evaluation order.
     * @param {Array<Object>} results - Candidate evaluation result objects.
     */
    renderDashboard(results) {
        this.lastResults = results;
        if (this.placeholderPanel) this.placeholderPanel.style.display = 'none';
        if (this.resultsPanel) this.resultsPanel.style.display = 'block';
        if (this.evalTotalBadge) this.evalTotalBadge.textContent = `${results.length} Evaluated`;

        if (!this.tierBlocksContainer) return;
        this.tierBlocksContainer.innerHTML = '';

        // Group evaluation results by Tier
        const tierGroups = {
            1: { title: 'Resume Tier 1', badgeClass: 'tier-badge-1', cardClass: 'tier-1-card', items: [] },
            2: { title: 'Resume Tier 2', badgeClass: 'tier-badge-2', cardClass: 'tier-2-card', items: [] },
            3: { title: 'Resume Tier 3', badgeClass: 'tier-badge-3', cardClass: 'tier-3-card', items: [] }
        };

        results.forEach(res => {
            const t = res.tier || 3;
            if (!tierGroups[t]) tierGroups[t] = tierGroups[3];
            tierGroups[t].items.push(res);
        });

        let inspectSet = false;

        [1, 2, 3].forEach(tNum => {
            const group = tierGroups[tNum];
            if (group.items.length === 0) return;

            const blockCard = document.createElement('div');
            blockCard.className = `tier-block-card ${group.cardClass}`;
            
            blockCard.innerHTML = `
                <div class="panel-header-split" style="margin-bottom: 12px;">
                    <div style="display: flex; align-items: center; gap: 10px;">
                        <h3 style="margin: 0;">${group.title}</h3>
                        <span class="tier-badge ${group.badgeClass}">Evaluation Order: Tier ${tNum}</span>
                    </div>
                    <span class="text-muted" style="font-size: 0.85rem;">${group.items.length} Evaluated</span>
                </div>
                <div class="table-responsive">
                    <table class="leaderboard-table">
                        <thead>
                            <tr>
                                <th>Eval Order</th>
                                <th>Candidate / Email</th>
                                <th>Score</th>
                                <th>Match Recommendation</th>
                                <th>Strengths / Gaps</th>
                                <th>Action</th>
                            </tr>
                        </thead>
                        <tbody class="tier-tbody"></tbody>
                    </table>
                </div>
            `;

            const tbody = blockCard.querySelector('.tier-tbody');

            group.items.forEach((res, idx) => {
                const evalOrderNum = idx + 1;
                const tr = document.createElement('tr');

                tr.innerHTML = `
                    <td><span class="rank-badge">${evalOrderNum}</span></td>
                    <td>
                        <strong>${this.escapeHtml(res.resume_name)}</strong><br>
                        <span style="font-size:0.75rem; color: var(--text-muted);">✉ ${this.escapeHtml(res.candidate_email || res.candidate_identifier || 'N/A')}</span>
                    </td>
                    <td><strong style="color: var(--accent-bright); font-size:1.1rem;">${res.overall_score || 0}</strong>/100</td>
                    <td><span class="badge-rec rec-${res.match_recommendation}">${res.match_recommendation}</span></td>
                    <td style="font-size:0.8rem;">
                        <span style="color:var(--success-light);">✓ ${res.summary?.total_strengths || 0}</span> | 
                        <span style="color:var(--danger-light);">✗ ${res.summary?.total_gaps || 0}</span>
                    </td>
                    <td>
                        <button class="btn btn-sm btn-secondary btn-inspect">Inspect Detail</button>
                    </td>
                `;

                tr.querySelector('.btn-inspect').addEventListener('click', () => {
                    this.renderCandidateDetail(res);
                });

                tbody.appendChild(tr);

                if (!inspectSet) {
                    this.renderCandidateDetail(res);
                    inspectSet = true;
                }
            });

            this.tierBlocksContainer.appendChild(blockCard);
        });
    }

    /**
     * Renders detailed 5-dimension scorecard for selected candidate.
     * @param {Object} cand - Candidate evaluation details.
     */
    renderCandidateDetail(cand) {
        if (!this.detailView) return;
        this.detailView.style.display = 'block';

        document.getElementById('det-cand-name').textContent = cand.candidate_identifier || cand.resume_name;
        document.getElementById('det-cand-file').textContent = `${cand.resume_name}.json • Evaluated ${cand.evaluated_at ? new Date(cand.evaluated_at).toLocaleTimeString() : ''}`;
        document.getElementById('det-cand-score').textContent = cand.overall_score || '0.0';

        const recBadge = document.getElementById('det-cand-rec');
        recBadge.textContent = cand.match_recommendation;
        recBadge.className = `rec-tag badge-rec rec-${cand.match_recommendation}`;

        const dimensionsContainer = document.getElementById('dimensions-container');
        dimensionsContainer.innerHTML = '';

        const dims = cand.dimension_scores || {};
        Object.keys(dims).forEach(key => {
            const d = dims[key];
            const card = document.createElement('div');
            card.className = 'dimension-card';

            const strengthsList = (d.strengths || []).map(s => `<li>${this.escapeHtml(s)}</li>`).join('');
            const gapsList = (d.gaps || []).map(g => `<li style="color:#f87171;">${this.escapeHtml(g)}</li>`).join('');
            const reasoningText = d.reasoning_summary ? this.escapeHtml(d.reasoning_summary) : '';

            card.innerHTML = `
                <div class="dim-header">
                    <span>${this.escapeHtml(d.category_name)} (${Math.round((d.weight || 0.2) * 100)}%)</span>
                    <span class="dim-score">${d.score}/100</span>
                </div>
                <div class="dim-progress-track">
                    <div class="dim-progress-fill" style="width: ${d.score}%;"></div>
                </div>
                ${reasoningText ? `
                    <div style="font-size:0.8rem; font-weight:600; margin-top:6px; color: var(--accent-bright);">🧠 AI Reasoning (Lập luận đánh giá):</div>
                    <div class="dim-reasoning-box">${reasoningText}</div>
                ` : ''}
                <div style="font-size:0.8rem; font-weight:600; margin-top:6px;">Strengths:</div>
                <ul class="dim-list">${strengthsList || '<li>None noted</li>'}</ul>
                <div style="font-size:0.8rem; font-weight:600; margin-top:6px;">Gaps / Concerns:</div>
                <ul class="dim-list">${gapsList || '<li>None noted</li>'}</ul>
            `;
            dimensionsContainer.appendChild(card);
        });

        this.detailView.scrollIntoView({ behavior: 'smooth' });
    }

    escapeHtml(str) {
        if (!str) return '';
        return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }
}
