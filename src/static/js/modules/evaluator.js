/**
 * ==============================================================================
 * Step 2: HR Evaluator Controller (Fulbright Redesign Edition)
 * ==============================================================================
 * Description: Manages 2-step HR workflow:
 *              1. Input requirements & decompose into 5-dimension RAG criteria + hr_rag.txt
 *              2. Inspect & freely edit/adjust RAG criteria before evaluation
 *              3. Candidate selection with live filtering & secret tier ordering
 *              4. AI batch evaluation against verified RAG criteria, KPI statistics,
 *                 and full-width dossier inspector.
 * Line Count: ~450 lines (Strict Limit: < 500 lines)
 */

import { API } from './api.js';

export class EvaluatorController {
    constructor() {
        this.scannedResumes = [];
        this.selectedResumesSet = new Set();
        this.lastResults = [];
        this.searchTerm = '';
        this.currentCategories = {
            seniority_title: [],
            technical_skills: [],
            work_experience: [],
            education_certifications: [],
            hidden_culture: []
        };
        this.currentHrRagText = '';

        this.initDOMElements();
        this.initEvents();
        this.checkExistingRag();
    }

    /**
     * Binds DOM element references across all stages.
     */
    initDOMElements() {
        // Stage containers
        this.stageReq = document.getElementById('eval-req-stage');
        this.stageRagVerify = document.getElementById('eval-rag-verify-stage');
        this.stageCandidates = document.getElementById('eval-candidates-stage');
        this.stageResults = document.getElementById('eval-results-stage');

        // Inputs & Buttons - Step 1
        this.hrStdReqInput = document.getElementById('hr-std-req');
        this.hrHiddenReqInput = document.getElementById('hr-hidden-req');
        this.btnDecomposeReqs = document.getElementById('btn-decompose-reqs');
        this.btnUseExistingRag = document.getElementById('btn-use-existing-rag');

        // Step 2: RAG Verification & Editor
        this.criteriaEditorContainer = document.getElementById('criteria-editor-container');
        this.hrRagPreviewText = document.getElementById('hr-rag-preview-text');
        this.tabBtnCategories = document.getElementById('tab-btn-categories');
        this.tabBtnRawFile = document.getElementById('tab-btn-raw-file');
        this.paneCategoriesEditor = document.getElementById('pane-categories-editor');
        this.paneRawFile = document.getElementById('pane-raw-file');
        this.btnBackToReqs = document.getElementById('btn-back-to-requirements');
        this.btnSaveCriteriaChanges = document.getElementById('btn-save-criteria-changes');
        this.btnProceedToCandidates = document.getElementById('btn-proceed-to-candidates');

        // Step 3: Candidate Selection
        this.activeRagBannerText = document.getElementById('active-rag-banner-text');
        this.btnBackToRagVerify = document.getElementById('btn-back-to-rag-verify');
        this.btnBackToCriteriaStep = document.getElementById('btn-back-to-criteria-step');
        this.scannedContainer = document.getElementById('scanned-resumes-container');
        this.chkSelectAll = document.getElementById('chk-select-all');
        this.selectedCountBadge = document.getElementById('selected-count-badge');
        this.candSearchInput = document.getElementById('eval-cand-search');
        this.btnRefreshResumes = document.getElementById('btn-refresh-resumes');
        this.btnRunEval = document.getElementById('btn-run-eval');

        // Step 4: Results & Dossier Inspector
        this.tierBlocksContainer = document.getElementById('tier-blocks-container');
        this.evalTotalBadge = document.getElementById('eval-total-badge');
        this.btnModifyCriteria = document.getElementById('btn-modify-criteria');
        this.detailView = document.getElementById('candidate-detail-view');

        // KPI Banner elements
        this.kpiTotalVal = document.getElementById('kpi-total-val');
        this.kpiStrongVal = document.getElementById('kpi-strong-val');
        this.kpiPotentialVal = document.getElementById('kpi-potential-val');
        this.kpiAvgScoreVal = document.getElementById('kpi-avg-score-val');

        // Stepped nav steps (1 to 4)
        this.stepNav1 = document.getElementById('step-nav-1');
        this.stepNav2 = document.getElementById('step-nav-2');
        this.stepNav3 = document.getElementById('step-nav-3');
        this.stepNav4 = document.getElementById('step-nav-4');

        // Loader Overlay
        this.loaderOverlay = document.getElementById('loader-overlay');
        this.loaderTitle = document.getElementById('loader-title');
        this.loaderDesc = document.getElementById('loader-desc');
    }

    /**
     * Binds event listeners across the 4-step workflow.
     */
    initEvents() {
        // Step 1 triggers
        if (this.btnDecomposeReqs) {
            this.btnDecomposeReqs.addEventListener('click', () => this.decomposeRequirements());
        }
        if (this.btnUseExistingRag) {
            this.btnUseExistingRag.addEventListener('click', () => this.useExistingRagAndProceed());
        }

        // Step 2 triggers (RAG Verification & Tabs)
        if (this.tabBtnCategories && this.tabBtnRawFile) {
            this.tabBtnCategories.addEventListener('click', () => this.switchRagTab('categories'));
            this.tabBtnRawFile.addEventListener('click', () => this.switchRagTab('raw'));
        }
        if (this.btnBackToReqs) {
            this.btnBackToReqs.addEventListener('click', () => this.goToStage(1));
        }
        if (this.btnSaveCriteriaChanges) {
            this.btnSaveCriteriaChanges.addEventListener('click', () => this.saveModifiedCriteria(true));
        }
        if (this.btnProceedToCandidates) {
            this.btnProceedToCandidates.addEventListener('click', async () => {
                await this.saveModifiedCriteria(false);
                this.goToStage(3);
            });
        }

        // Step 3 triggers (Candidate Selection)
        if (this.btnBackToRagVerify) {
            this.btnBackToRagVerify.addEventListener('click', () => this.goToStage(2));
        }
        if (this.btnBackToCriteriaStep) {
            this.btnBackToCriteriaStep.addEventListener('click', () => this.goToStage(1));
        }
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

        // Step 4 triggers (Results)
        if (this.btnModifyCriteria) {
            this.btnModifyCriteria.addEventListener('click', () => this.goToStage(2));
        }
    }

    /**
     * Checks if RAG already has stored criteria to show the quick skip button.
     */
    async checkExistingRag() {
        try {
            const ragData = await API.getRagInfo();
            if (ragData && ragData.has_stored_rag && ragData.total_items > 0) {
                if (this.btnUseExistingRag) {
                    this.btnUseExistingRag.style.display = 'inline-flex';
                    this.btnUseExistingRag.textContent = `Use Active RAG (${ragData.total_items} items) & Skip →`;
                }
            }
        } catch (e) {
            console.warn('Could not check RAG status:', e);
        }
    }

    /**
     * Navigates between workflow stages (1: Requirements, 2: RAG Verify, 3: Candidates, 4: Results).
     */
    goToStage(stepNum) {
        if (this.stageReq) this.stageReq.style.display = stepNum === 1 ? 'block' : 'none';
        if (this.stageRagVerify) this.stageRagVerify.style.display = stepNum === 2 ? 'block' : 'none';
        if (this.stageCandidates) this.stageCandidates.style.display = stepNum === 3 ? 'block' : 'none';
        if (this.stageResults) this.stageResults.style.display = stepNum === 4 ? 'block' : 'none';

        this.updateStepIndicator(stepNum);

        if (stepNum === 3 && this.scannedResumes.length === 0) {
            this.loadScannedResumes();
        }
        if (stepNum === 3) {
            this.updateActiveRagBanner();
        }
    }

    /**
     * Updates top progress step indicators.
     */
    updateStepIndicator(activeStep) {
        const stepEls = [this.stepNav1, this.stepNav2, this.stepNav3, this.stepNav4];
        stepEls.forEach((stepEl, idx) => {
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
     * Toggles between Interactive Categories Editor and Raw hr_rag.txt View.
     */
    switchRagTab(tab) {
        if (tab === 'categories') {
            if (this.tabBtnCategories) this.tabBtnCategories.classList.add('active');
            if (this.tabBtnRawFile) this.tabBtnRawFile.classList.remove('active');
            if (this.paneCategoriesEditor) this.paneCategoriesEditor.style.display = 'block';
            if (this.paneRawFile) this.paneRawFile.style.display = 'none';
        } else {
            if (this.tabBtnCategories) this.tabBtnCategories.classList.remove('active');
            if (this.tabBtnRawFile) this.tabBtnRawFile.classList.add('active');
            if (this.paneCategoriesEditor) this.paneCategoriesEditor.style.display = 'none';
            if (this.paneRawFile) this.paneRawFile.style.display = 'block';
        }
    }

    /**
     * Step 1 -> Step 2: Decomposes requirements using LLM and populates the editor.
     */
    async decomposeRequirements() {
        const stdReq = (this.hrStdReqInput ? this.hrStdReqInput.value : '').trim();
        const hiddenReq = (this.hrHiddenReqInput ? this.hrHiddenReqInput.value : '').trim();

        if (!stdReq && !hiddenReq) {
            alert('Please enter Standard Job Requirements or Hidden Requirements before decomposing.');
            return;
        }

        if (this.loaderOverlay) {
            this.loaderTitle.textContent = 'Decomposing HR Requirements...';
            this.loaderDesc.textContent = 'Extracting atomic criteria across 5 dimensions using LLM and vector embeddings...';
            this.loaderOverlay.style.display = 'flex';
        }

        try {
            const data = await API.decomposeRequirements(stdReq, hiddenReq);
            this.processRagSummaryData(data);
            this.goToStage(2);
        } catch (err) {
            alert('Requirement Categorization Error: ' + err.message);
        } finally {
            if (this.loaderOverlay) this.loaderOverlay.style.display = 'none';
        }
    }

    /**
     * Quick skip when persistent RAG is already populated.
     */
    async useExistingRagAndProceed() {
        try {
            const data = await API.getRagInfo();
            this.processRagSummaryData(data);
            this.goToStage(3);
        } catch (err) {
            alert('Failed to load active RAG: ' + err.message);
        }
    }

    /**
     * Ingests summary data into controller state and renders the interactive editor.
     */
    processRagSummaryData(data) {
        this.currentHrRagText = data.hr_rag_text || '';
        if (this.hrRagPreviewText) {
            this.hrRagPreviewText.textContent = this.currentHrRagText || 'No hr_rag.txt file generated.';
        }

        const rawCats = data.categories || {};
        this.currentCategories = {
            seniority_title: [],
            technical_skills: [],
            work_experience: [],
            education_certifications: [],
            hidden_culture: []
        };

        Object.keys(this.currentCategories).forEach(k => {
            const items = rawCats[k] || [];
            this.currentCategories[k] = items.map(it => (typeof it === 'object' && it.text ? it.text : String(it)));
        });

        this.renderCriteriaEditor();
    }

    /**
     * Renders 5-dimension category cards with live editable text inputs and add/remove controls.
     */
    renderCriteriaEditor() {
        if (!this.criteriaEditorContainer) return;
        this.criteriaEditorContainer.innerHTML = '';

        const catLabels = {
            seniority_title: '1. Seniority & Title (Vị trí & Số năm kinh nghiệm)',
            technical_skills: '2. Technical Skills (Kỹ năng, Công cụ & Chuyên môn)',
            work_experience: '3. Work Experience (Dự án & Trách nhiệm)',
            education_certifications: '4. Education & Certifications (Bằng cấp & Chứng chỉ)',
            hidden_culture: '5. Hidden & Culture Fit (Yêu cầu ẩn & Văn hóa)'
        };

        Object.keys(catLabels).forEach(catKey => {
            const items = this.currentCategories[catKey] || [];
            const card = document.createElement('div');
            card.className = 'criteria-category-card';
            card.setAttribute('data-cat', catKey);

            card.innerHTML = `
                <div class="criteria-card-header">
                    <span class="criteria-card-title">${catLabels[catKey]}</span>
                    <span class="badge-success cat-count-badge" style="font-size:0.75rem;">${items.length} items</span>
                </div>
                <div class="criteria-items-list" id="list-${catKey}"></div>
                <div class="criteria-add-box">
                    <input type="text" class="criteria-add-input" placeholder="+ Add new criterion for this dimension...">
                    <button class="btn btn-sm btn-secondary criteria-add-btn" type="button">Add</button>
                </div>
            `;

            const listEl = card.querySelector('.criteria-items-list');
            this.renderCategoryItemList(listEl, catKey);

            // Add new criterion handler
            const addInput = card.querySelector('.criteria-add-input');
            const addBtn = card.querySelector('.criteria-add-btn');
            const handleAdd = () => {
                const val = addInput.value.trim();
                if (val) {
                    this.currentCategories[catKey].push(val);
                    this.renderCategoryItemList(listEl, catKey);
                    card.querySelector('.cat-count-badge').textContent = `${this.currentCategories[catKey].length} items`;
                    addInput.value = '';
                }
            };

            addBtn.addEventListener('click', handleAdd);
            addInput.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    handleAdd();
                }
            });

            this.criteriaEditorContainer.appendChild(card);
        });
    }

    /**
     * Renders item rows inside a category card.
     */
    renderCategoryItemList(listEl, catKey) {
        listEl.innerHTML = '';
        const items = this.currentCategories[catKey] || [];

        if (items.length === 0) {
            listEl.innerHTML = '<div style="font-size:0.8rem; color:var(--text-muted); font-style:italic; padding:6px 0;">No criteria items in this category.</div>';
            return;
        }

        items.forEach((itemText, idx) => {
            const row = document.createElement('div');
            row.className = 'criteria-item-row';
            row.innerHTML = `
                <span style="font-size:0.75rem; font-weight:700; color:var(--brand-legacy-blue); width:18px;">${idx + 1}.</span>
                <input type="text" class="criteria-item-text" value="${this.escapeHtml(itemText)}" />
                <button class="criteria-item-del-btn" title="Delete criterion" type="button">
                    <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor"><path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg>
                </button>
            `;

            const textInput = row.querySelector('.criteria-item-text');
            textInput.addEventListener('input', (e) => {
                this.currentCategories[catKey][idx] = e.target.value;
            });

            const delBtn = row.querySelector('.criteria-item-del-btn');
            delBtn.addEventListener('click', () => {
                this.currentCategories[catKey].splice(idx, 1);
                this.renderCategoryItemList(listEl, catKey);
                const countBadge = listEl.closest('.criteria-category-card')?.querySelector('.cat-count-badge');
                if (countBadge) countBadge.textContent = `${this.currentCategories[catKey].length} items`;
            });

            listEl.appendChild(row);
        });
    }

    /**
     * Saves user modifications back to backend vector store & updates hr_rag.txt.
     */
    async saveModifiedCriteria(showSuccessAlert = true) {
        const stdReq = (this.hrStdReqInput ? this.hrStdReqInput.value : '').trim();
        const hiddenReq = (this.hrHiddenReqInput ? this.hrHiddenReqInput.value : '').trim();

        try {
            const updated = await API.updateRagCriteria(this.currentCategories, stdReq, hiddenReq);
            this.currentHrRagText = updated.hr_rag_text || '';
            if (this.hrRagPreviewText) {
                this.hrRagPreviewText.textContent = this.currentHrRagText;
            }
            if (showSuccessAlert) {
                alert('✓ Changes successfully saved to persistent RAG vector store and hr_rag.txt!');
            }
            return true;
        } catch (err) {
            alert('Failed to save criteria changes: ' + err.message);
            return false;
        }
    }

    /**
     * Updates active RAG summary banner in Candidate Selection stage.
     */
    updateActiveRagBanner() {
        if (!this.activeRagBannerText) return;
        const totalItems = Object.values(this.currentCategories).reduce((acc, curr) => acc + (curr ? curr.length : 0), 0);
        this.activeRagBannerText.innerHTML = `<strong>RAG Criteria Active & Verified:</strong> ${totalItems} criteria across 5 dimensions stored in ChromaDB vector store.`;
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
     * Submits verified RAG criteria and candidate selection to run batch AI evaluation.
     */
    async runEvaluation() {
        const stdReq = (this.hrStdReqInput ? this.hrStdReqInput.value : '').trim();
        const hiddenReq = (this.hrHiddenReqInput ? this.hrHiddenReqInput.value : '').trim();
        const filenames = Array.from(this.selectedResumesSet);

        if (filenames.length === 0) {
            alert('Please select at least one candidate resume.');
            return;
        }

        if (this.loaderOverlay) {
            this.loaderTitle.textContent = `Evaluating ${filenames.length} Candidate(s)...`;
            this.loaderDesc.textContent = 'Computing 5 RAG vector dimension scores strictly in evaluation order...';
            this.loaderOverlay.style.display = 'flex';
        }

        try {
            // Use existing verified RAG criteria
            const data = await API.evaluateBatch(stdReq, hiddenReq, filenames, true);
            if (data && Array.isArray(data.results)) {
                if (data.results.length === 0) {
                    alert('No evaluation results generated. Please ensure selected candidates have been scanned/extracted in Step 1.');
                } else {
                    this.renderDashboard(data.results);
                }
            } else {
                alert('Evaluation failed: Server returned an invalid response structure.');
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
        this.goToStage(4);

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


