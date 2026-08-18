/**
 * ==============================================================================
 * Step 2: HR Evaluator Controller (Fulbright Redesign Edition)
 * ==============================================================================
 * Description: Manages job criteria, candidate selection with live filtering,
 *              batch AI evaluation, KPI statistics calculation, and full-width
 *              dossier inspector breakdown.
 * Line Count: ~360 lines
 */

import { API } from './api.js';

export class EvaluatorController {
    constructor() {
        this.scannedResumes = [];
        this.selectedResumesSet = new Set();
        this.lastResults = [];
        this.searchTerm = '';

        this.initDOMElements();
        this.initEvents();
    }

    /**
     * Binds DOM element references required for batch evaluation workflow.
     */
    initDOMElements() {
        this.scannedContainer = document.getElementById('scanned-resumes-container');
        this.chkSelectAll = document.getElementById('chk-select-all');
        this.selectedCountBadge = document.getElementById('selected-count-badge');
        this.btnRunEval = document.getElementById('btn-run-eval');
        this.btnRefreshResumes = document.getElementById('btn-refresh-resumes');
        this.candSearchInput = document.getElementById('eval-cand-search');

        this.setupStage = document.getElementById('eval-setup-stage');
        this.resultsStage = document.getElementById('eval-results-stage');
        this.btnModifyCriteria = document.getElementById('btn-modify-criteria');

        this.tierBlocksContainer = document.getElementById('tier-blocks-container');
        this.evalTotalBadge = document.getElementById('eval-total-badge');
        this.detailView = document.getElementById('candidate-detail-view');

        // KPI Banner elements
        this.kpiTotalVal = document.getElementById('kpi-total-val');
        this.kpiStrongVal = document.getElementById('kpi-strong-val');
        this.kpiPotentialVal = document.getElementById('kpi-potential-val');
        this.kpiAvgScoreVal = document.getElementById('kpi-avg-score-val');

        // Stepped nav steps
        this.stepNav1 = document.getElementById('step-nav-1');
        this.stepNav2 = document.getElementById('step-nav-2');
        this.stepNav3 = document.getElementById('step-nav-3');

        this.loaderOverlay = document.getElementById('loader-overlay');
        this.loaderTitle = document.getElementById('loader-title');
        this.loaderDesc = document.getElementById('loader-desc');
    }

    /**
     * Binds event listeners for selection, search, refresh, and stage navigation.
     */
    initEvents() {
        if (this.btnRefreshResumes) {
            this.btnRefreshResumes.addEventListener('click', () => this.loadScannedResumes());
        }

        if (this.chkSelectAll) {
            this.chkSelectAll.addEventListener('change', () => {
                this.selectedResumesSet.clear();
                if (this.chkSelectAll.checked) {
                    const filtered = this.getFilteredResumes();
                    filtered.forEach(r => this.selectedResumesSet.add(r.filename));
                }
                this.renderScannedList();
                this.updateSelectedCount();
            });
        }

        if (this.candSearchInput) {
            this.candSearchInput.addEventListener('input', (e) => {
                this.searchTerm = e.target.value.toLowerCase().trim();
                this.renderScannedList();
            });
        }

        if (this.btnRunEval) {
            this.btnRunEval.addEventListener('click', () => this.runEvaluation());
        }

        if (this.btnModifyCriteria) {
            this.btnModifyCriteria.addEventListener('click', () => {
                this.switchToSetupStage();
            });
        }
    }

    /**
     * Returns list of resumes matching search term.
     */
    getFilteredResumes() {
        if (!this.searchTerm) return this.scannedResumes;
        return this.scannedResumes.filter(r => {
            const name = (r.filename || '').toLowerCase();
            const email = (r.email || '').toLowerCase();
            const title = (r.title || '').toLowerCase();
            return name.includes(this.searchTerm) || email.includes(this.searchTerm) || title.includes(this.searchTerm);
        });
    }

    /**
     * Switch view back to setup stage.
     */
    switchToSetupStage() {
        if (this.setupStage) this.setupStage.style.display = 'block';
        if (this.resultsStage) this.resultsStage.style.display = 'none';
        this.updateStepIndicator(1);
    }

    /**
     * Update progress step indicator bar.
     */
    updateStepIndicator(activeStep) {
        [this.stepNav1, this.stepNav2, this.stepNav3].forEach((stepEl, idx) => {
            if (!stepEl) return;
            const stepNum = idx + 1;
            stepEl.classList.remove('active', 'completed');
            if (stepNum === activeStep) {
                stepEl.classList.add('active');
            } else if (stepNum < activeStep) {
                stepEl.classList.add('completed');
            }
        });
    }

    /**
     * Fetches scanned resumes from backend.
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
     * Renders candidate checkbox list grouped by tier.
     */
    renderScannedList() {
        this.scannedContainer.innerHTML = '';

        const resumes = this.getFilteredResumes();
        if (resumes.length === 0) {
            this.scannedContainer.innerHTML = '<div class="empty-state" style="padding: 1rem 0; font-size: 0.85rem;">No candidates match your search filter.</div>';
            return;
        }

        // Secret order status banner
        const banner = document.createElement('div');
        banner.style.cssText = 'padding: 8px 12px; border-radius: 8px; font-size: 0.78rem; font-weight: 600; margin-bottom: 10px; display: flex; align-items: center; justify-content: space-between;';
        if (this.orderActive) {
            banner.style.background = '#DCFCE7';
            banner.style.border = '1px solid #86EFAC';
            banner.style.color = '#15803D';
            banner.innerHTML = `<span>🔒 Secret Order: Active</span><span style="font-size:0.72rem; opacity:0.9;">Tier 1: ${this.tier1Count} • Tier 2: ${this.tier2Count}</span>`;
        } else {
            banner.style.background = '#FFFBEB';
            banner.style.border = '1px solid #FCD34D';
            banner.style.color = '#B45309';
            banner.innerHTML = `<span>⚠️ Secret Order: File Not Found</span><span style="font-size:0.72rem;">evaluation_order.txt</span>`;
        }
        this.scannedContainer.appendChild(banner);

        const tiers = {
            1: { title: 'Resume Tier 1 (Priority)', badgeClass: 'tier-badge-1', items: [] },
            2: { title: 'Resume Tier 2 (Secondary)', badgeClass: 'tier-badge-2', items: [] },
            3: { title: 'Resume Tier 3 (Unlisted)', badgeClass: 'tier-badge-3', items: [] }
        };

        resumes.forEach(r => {
            const t = r.tier || 3;
            if (!tiers[t]) tiers[t] = tiers[3];
            tiers[t].items.push(r);
        });

        [1, 2, 3].forEach(tNum => {
            const group = tiers[tNum];
            if (group.items.length === 0) return;

            const block = document.createElement('div');
            block.className = `scanned-tier-block tier-${tNum}-block`;

            block.innerHTML = `
                <div class="panel-header-split" style="margin-bottom: 8px;">
                    <span style="font-weight: 700; font-size: 0.88rem; color: var(--brand-legacy-blue);">${group.title}</span>
                    <span class="tier-badge ${group.badgeClass}">${group.items.length} candidate(s)</span>
                </div>
                <div class="tier-items-list" style="display: flex; flex-direction: column; gap: 8px;"></div>
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

        this.updateStepIndicator(2);

        if (this.loaderOverlay) {
            this.loaderTitle.textContent = `Evaluating ${filenames.length} Candidate(s)...`;
            this.loaderDesc.textContent = 'Computing 5 RAG vector dimension scores strictly in evaluation order...';
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
     * Renders evaluation results dashboard and dossier inspector.
     */
    renderDashboard(results) {
        this.lastResults = results;

        if (this.setupStage) this.setupStage.style.display = 'none';
        if (this.resultsStage) this.resultsStage.style.display = 'block';

        this.updateStepIndicator(3);

        // Update KPI summary stats
        const totalCount = results.length;
        const strongCount = results.filter(r => r.match_recommendation === 'STRONG_MATCH').length;
        const potentialCount = results.filter(r => r.match_recommendation === 'POTENTIAL_MATCH').length;
        const avgScore = totalCount > 0 ? (results.reduce((acc, curr) => acc + (curr.overall_score || 0), 0) / totalCount).toFixed(1) : '0.0';

        if (this.kpiTotalVal) this.kpiTotalVal.textContent = totalCount;
        if (this.kpiStrongVal) this.kpiStrongVal.textContent = strongCount;
        if (this.kpiPotentialVal) this.kpiPotentialVal.textContent = potentialCount;
        if (this.kpiAvgScoreVal) this.kpiAvgScoreVal.textContent = avgScore;
        if (this.evalTotalBadge) this.evalTotalBadge.textContent = `${totalCount} Evaluated`;

        if (!this.tierBlocksContainer) return;
        this.tierBlocksContainer.innerHTML = '';

        const tierGroups = {
            1: { title: 'Resume Tier 1 (Priority Candidates)', badgeClass: 'tier-badge-1', cardClass: 'tier-1-card', items: [] },
            2: { title: 'Resume Tier 2 (Secondary Candidates)', badgeClass: 'tier-badge-2', cardClass: 'tier-2-card', items: [] },
            3: { title: 'Resume Tier 3 (Unlisted Candidates)', badgeClass: 'tier-badge-3', cardClass: 'tier-3-card', items: [] }
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
                <div class="panel-header-split" style="margin-bottom: 14px;">
                    <div style="display: flex; align-items: center; gap: 12px;">
                        <h3 style="margin: 0; color: var(--brand-legacy-blue); font-size: 1.1rem;">${group.title}</h3>
                        <span class="tier-badge ${group.badgeClass}">Tier ${tNum}</span>
                    </div>
                    <span class="text-muted" style="font-size: 0.85rem; font-weight:600;">${group.items.length} Candidate(s)</span>
                </div>
                <div class="table-responsive">
                    <table class="leaderboard-table">
                        <thead>
                            <tr>
                                <th>Rank</th>
                                <th>Candidate / Email</th>
                                <th>Match Score</th>
                                <th>Recommendation</th>
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
                    <td><span class="rank-badge rank-${evalOrderNum}">${evalOrderNum}</span></td>
                    <td>
                        <strong style="color: var(--brand-legacy-blue); font-size: 0.95rem;">${this.escapeHtml(res.resume_name)}</strong><br>
                        <span style="font-size:0.78rem; color: var(--text-muted);">✉ ${this.escapeHtml(res.candidate_email || res.candidate_identifier || 'N/A')}</span>
                    </td>
                    <td><strong style="color: var(--brand-azure); font-size:1.2rem; font-family:var(--font-mono);">${res.overall_score || 0}</strong><span style="font-size:0.8rem; color:var(--text-muted);">/100</span></td>
                    <td><span class="badge-rec rec-${res.match_recommendation}">${res.match_recommendation}</span></td>
                    <td style="font-size:0.82rem; font-weight:600;">
                        <span style="color:#15803D;">✓ ${res.summary?.total_strengths || 0}</span> • 
                        <span style="color:#B91C1C;">✗ ${res.summary?.total_gaps || 0}</span>
                    </td>
                    <td>
                        <button class="btn btn-sm btn-secondary btn-inspect">Inspect Dossier</button>
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
     * Renders spacious full-width candidate dossier detail view.
     */
    renderCandidateDetail(cand) {
        if (!this.detailView) return;
        this.detailView.style.display = 'block';

        const nameEl = document.getElementById('det-cand-name');
        const fileEl = document.getElementById('det-cand-file');
        const scoreEl = document.getElementById('det-cand-score');
        const recBadge = document.getElementById('det-cand-rec');
        const summaryEl = document.getElementById('det-cand-summary');
        const strengthsListEl = document.getElementById('det-cand-strengths-list');
        const gapsListEl = document.getElementById('det-cand-gaps-list');

        if (nameEl) nameEl.textContent = cand.candidate_identifier || cand.resume_name;
        if (fileEl) fileEl.textContent = `${cand.resume_name}.json • Evaluated ${cand.evaluated_at ? new Date(cand.evaluated_at).toLocaleTimeString() : 'Just now'}`;
        if (scoreEl) scoreEl.textContent = cand.overall_score || '0.0';

        if (recBadge) {
            recBadge.textContent = cand.match_recommendation;
            recBadge.className = `badge-rec rec-${cand.match_recommendation}`;
        }

        // Executive summary body
        if (summaryEl) {
            summaryEl.textContent = cand.summary?.executive_summary || `Candidate score is ${cand.overall_score}/100 with match classification of ${cand.match_recommendation}. Evaluated across 5 RAG vector dimensions.`;
        }

        // Populate Strengths & Gaps lists
        if (strengthsListEl) {
            const allStrengths = [];
            const dims = cand.dimension_scores || {};
            Object.values(dims).forEach(d => {
                (d.strengths || []).forEach(s => allStrengths.push(s));
            });
            strengthsListEl.innerHTML = allStrengths.length > 0
                ? allStrengths.map(s => `<li>${this.escapeHtml(s)}</li>`).join('')
                : '<li>No explicit strengths recorded.</li>';
        }

        if (gapsListEl) {
            const allGaps = [];
            const dims = cand.dimension_scores || {};
            Object.values(dims).forEach(d => {
                (d.gaps || []).forEach(g => allGaps.push(g));
            });
            gapsListEl.innerHTML = allGaps.length > 0
                ? allGaps.map(g => `<li>${this.escapeHtml(g)}</li>`).join('')
                : '<li>No major gaps or risk factors noted.</li>';
        }

        // Render 5-Dimension Scorecard Cards
        const dimensionsContainer = document.getElementById('dimensions-container');
        if (dimensionsContainer) {
            dimensionsContainer.innerHTML = '';
            const dims = cand.dimension_scores || {};
            Object.keys(dims).forEach(key => {
                const d = dims[key];
                const card = document.createElement('div');
                card.className = 'dimension-card';

                const strengthsList = (d.strengths || []).map(s => `<li>${this.escapeHtml(s)}</li>`).join('');
                const gapsList = (d.gaps || []).map(g => `<li style="color:#B91C1C;">${this.escapeHtml(g)}</li>`).join('');
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
                        <div style="font-size:0.8rem; font-weight:700; margin-top:6px; color: var(--brand-legacy-blue);">🧠 AI Reasoning:</div>
                        <div class="dim-reasoning-box">${reasoningText}</div>
                    ` : ''}
                    <div style="font-size:0.8rem; font-weight:700; margin-top:6px; color:#15803D;">Strengths:</div>
                    <ul class="dim-list">${strengthsList || '<li>None noted</li>'}</ul>
                    <div style="font-size:0.8rem; font-weight:700; margin-top:6px; color:#B91C1C;">Gaps / Concerns:</div>
                    <ul class="dim-list">${gapsList || '<li>None noted</li>'}</ul>
                `;
                dimensionsContainer.appendChild(card);
            });
        }

        this.detailView.scrollIntoView({ behavior: 'smooth' });
    }

    escapeHtml(str) {
        if (!str) return '';
        return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }
}

