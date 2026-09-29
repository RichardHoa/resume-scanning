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
 * Line Count: ~860 lines (Strict Limit: < 500 lines)
 */

import { API } from './api.js';
import { CriteriaEditor, CATEGORY_NAMES } from './criteria-editor.js';
import { WaitingScreen } from './waiting-screen.js';

// How often the batch-evaluation job status is polled while the waiting screen shows.
const EVAL_JOB_POLL_MS = 1500;

// Display text for the match_recommendation keys; the keys themselves stay as CSS class suffixes.
const RECOMMENDATION_LABELS = {
    STRONG_MATCH: 'PHÙ HỢP CAO',
    POTENTIAL_MATCH: 'CÓ TIỀM NĂNG',
    LOW_MATCH: 'PHÙ HỢP THẤP',
    REJECT: 'LOẠI'
};

export class EvaluatorController {
    constructor() {
        this.scannedResumes = [];
        this.selectedResumesSet = new Set();
        this.lastResults = [];
        this.searchTerm = '';
        this.currentHrRagText = '';
        this.currentStage = 1;

        // Number of Criteria stored in the RAG; the "Use Active RAG" skip button only shows when > 0.
        this.storedRagItemCount = 0;

        // Clarify-once intake state. Clarification Questions are asked once per pass through
        // requirement intake; a pass starts on page load and on each return to Step 1.
        //   checkedText      - the {std, hidden} text the last clarification check ran on (kept across passes)
        //   checkedThisPass  - whether a check has already run in the current pass
        //   questionsShowing - Clarification Questions are on screen; only the panel's button decomposes
        this.intake = { checkedText: null, checkedThisPass: false, questionsShowing: false };

        this.initDOMElements();
        this.criteriaEditor = new CriteriaEditor(this.criteriaEditorContainer);
        this.waitingScreen = new WaitingScreen();
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

        // Step 1: Clarification Questions (Implicit Assumption scrutiny), shown beside each field
        this.intakePanel = document.getElementById('intake-panel');
        this.scrutinyPanel = document.getElementById('scrutiny-panel');
        this.scrutinyListStandard = document.getElementById('scrutiny-list-standard');
        this.scrutinyListHidden = document.getElementById('scrutiny-list-hidden');
        this.btnProceedDecompose = document.getElementById('btn-proceed-decompose');

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
    }

    /**
     * Binds event listeners across the 4-step workflow.
     */
    initEvents() {
        // Step 1 triggers
        if (this.btnDecomposeReqs) {
            this.btnDecomposeReqs.addEventListener('click', () => this.handleDecomposeClick());
        }
        if (this.btnProceedDecompose) {
            this.btnProceedDecompose.addEventListener('click', () => this.decomposeFromQuestionsPanel());
        }
        if (this.btnUseExistingRag) {
            this.btnUseExistingRag.addEventListener('click', () => this.useExistingRagAndProceed());
        }
        [this.hrStdReqInput, this.hrHiddenReqInput].forEach(input => {
            if (input) input.addEventListener('input', () => this.updateUseExistingRagVisibility());
        });

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
                // Stay on the Verify step when the save fails; saveModifiedCriteria shows the error.
                if (await this.saveModifiedCriteria(false)) this.goToStage(3);
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
            this.setStoredRagItemCount(ragData);
        } catch (e) {
            console.warn('Could not check RAG status:', e);
        }
    }

    /**
     * Records how many Criteria the RAG holds, from any RAG summary response.
     */
    setStoredRagItemCount(summary) {
        this.storedRagItemCount = summary && summary.has_stored_rag ? (summary.total_items || 0) : 0;
        this.updateUseExistingRagVisibility();
    }

    /**
     * "Use Active RAG & Skip" shows only when the RAG has stored Criteria and both requirement
     * textareas are empty, so HR can't throw away new requirements they are typing.
     */
    updateUseExistingRagVisibility() {
        if (!this.btnUseExistingRag) return;
        const { stdReq, hiddenReq } = this.readRequirementText();
        const visible = this.storedRagItemCount > 0 && !stdReq && !hiddenReq;
        this.btnUseExistingRag.style.display = visible ? 'inline-flex' : 'none';
        if (visible) {
            this.btnUseExistingRag.textContent = `Dùng RAG đang hoạt động (${this.storedRagItemCount} tiêu chí) & Bỏ qua →`;
        }
    }

    readRequirementText() {
        return {
            stdReq: (this.hrStdReqInput ? this.hrStdReqInput.value : '').trim(),
            hiddenReq: (this.hrHiddenReqInput ? this.hrHiddenReqInput.value : '').trim()
        };
    }

    /**
     * Navigates between workflow stages (1: Requirements, 2: RAG Verify, 3: Candidates, 4: Results).
     */
    goToStage(stepNum) {
        if (stepNum === 1 && this.currentStage !== 1) {
            this.startNewIntakePass();
        }
        this.currentStage = stepNum;

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
        if (stepNum === 2) {
            // Criterion textareas can only measure their height once the stage is visible.
            this.criteriaEditor.resizeAll();
        }
    }

    /**
     * Returning to requirement intake starts a new pass: questions are cleared and the next
     * Decompose re-checks only if the text differs from what was last checked.
     */
    startNewIntakePass() {
        this.intake.checkedThisPass = false;
        this.hideScrutinyPanel();
        this.updateUseExistingRagVisibility();
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
            this.criteriaEditor.resizeAll();
        } else {
            if (this.tabBtnCategories) this.tabBtnCategories.classList.remove('active');
            if (this.tabBtnRawFile) this.tabBtnRawFile.classList.add('active');
            if (this.paneCategoriesEditor) this.paneCategoriesEditor.style.display = 'none';
            if (this.paneRawFile) this.paneRawFile.style.display = 'block';
        }
    }

    /**
     * Main "Decompose" button. Runs the Implicit Assumption clarification check once per pass:
     * on the first Decompose of a pass, or after returning from Category review with changed
     * text. Decomposes directly otherwise, or when the check finds no Implicit Assumptions.
     */
    async handleDecomposeClick() {
        const { stdReq, hiddenReq } = this.readRequirementText();

        if (!stdReq && !hiddenReq) {
            alert('Vui lòng nhập Yêu cầu công việc tiêu chuẩn hoặc Yêu cầu ẩn trước khi phân rã.');
            return;
        }

        const checked = this.intake.checkedText;
        const textChanged = !checked || checked.std !== stdReq || checked.hidden !== hiddenReq;
        const needsCheck = !checked || (!this.intake.checkedThisPass && textChanged);

        if (!needsCheck) {
            await this.decomposeRequirements(stdReq, hiddenReq);
            return;
        }

        let stdFindings;
        let hiddenFindings;
        try {
            const result = await this.waitingScreen.run(
                'scrutiny',
                'Đang kiểm tra yêu cầu...',
                'Đang tìm các giả định chưa được nêu rõ trước khi phân loại...',
                () => API.scrutinizeRequirements(stdReq, hiddenReq, 'vietnamese')
            );
            this.intake.checkedText = { std: stdReq, hidden: hiddenReq };
            this.intake.checkedThisPass = true;
            stdFindings = result.standard_requirements || [];
            hiddenFindings = result.hidden_requirements || [];
        } catch (err) {
            // Fail closed: a broken scrutiny call likely means decomposition would fail too.
            alert('Lỗi khi kiểm tra yêu cầu: ' + err.message);
            return;
        }

        if (stdFindings.length === 0 && hiddenFindings.length === 0) {
            await this.decomposeRequirements(stdReq, hiddenReq);
            return;
        }

        this.renderScrutinyPanel(stdFindings, hiddenFindings);
    }

    /**
     * The Decompose button shown alongside Clarification Questions: always decomposes the
     * current text directly, whatever HR edited, without a second check.
     */
    async decomposeFromQuestionsPanel() {
        const { stdReq, hiddenReq } = this.readRequirementText();
        // HR's edits made while reading the questions count as addressed, so returning from
        // Category review with this same text goes straight to decomposition.
        this.intake.checkedText = { std: stdReq, hidden: hiddenReq };
        await this.decomposeRequirements(stdReq, hiddenReq);
    }

    /**
     * Shows Clarification Questions beside the field they refer to and swaps the main
     * Decompose button for the panel's own.
     */
    renderScrutinyPanel(stdFindings, hiddenFindings) {
        const renderList = (listEl, findings) => {
            if (!listEl) return;
            listEl.innerHTML = findings.length > 0
                ? findings.map(f => `
                    <div class="scrutiny-question-item">
                        <div class="scrutiny-assumption">Giả định: ${this.escapeHtml(f.assumption)}</div>
                        <div class="scrutiny-question">${this.escapeHtml(f.question)}</div>
                    </div>
                `).join('')
                : '<div class="scrutiny-empty-note">Không có câu hỏi</div>';
        };

        renderList(this.scrutinyListStandard, stdFindings);
        renderList(this.scrutinyListHidden, hiddenFindings);

        this.intake.questionsShowing = true;
        if (this.intakePanel) this.intakePanel.classList.add('has-questions');
        if (this.scrutinyPanel) this.scrutinyPanel.style.display = 'block';
        if (this.btnDecomposeReqs) this.btnDecomposeReqs.style.display = 'none';
        if (this.btnProceedDecompose) this.btnProceedDecompose.style.display = 'inline-flex';
        if (this.intakePanel) this.intakePanel.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    hideScrutinyPanel() {
        this.intake.questionsShowing = false;
        if (this.intakePanel) this.intakePanel.classList.remove('has-questions');
        if (this.scrutinyPanel) this.scrutinyPanel.style.display = 'none';
        if (this.scrutinyListStandard) this.scrutinyListStandard.innerHTML = '';
        if (this.scrutinyListHidden) this.scrutinyListHidden.innerHTML = '';
        if (this.btnProceedDecompose) this.btnProceedDecompose.style.display = 'none';
        if (this.btnDecomposeReqs) this.btnDecomposeReqs.style.display = '';
    }

    /**
     * Step 1 -> Step 2: Decomposes requirements using LLM and populates the editor.
     */
    async decomposeRequirements(stdReq, hiddenReq) {
        if (!stdReq && !hiddenReq) {
            alert('Vui lòng nhập Yêu cầu công việc tiêu chuẩn hoặc Yêu cầu ẩn trước khi phân rã.');
            return;
        }

        try {
            const data = await this.waitingScreen.run(
                'decompose',
                'Đang phân rã yêu cầu...',
                'Đang tách các tiêu chí đơn lẻ theo 5 chiều bằng LLM và vector embedding...',
                () => API.decomposeRequirements(stdReq, hiddenReq, 'vietnamese')
            );
            this.processRagSummaryData(data);
            this.setStoredRagItemCount(data);
            this.goToStage(2);
        } catch (err) {
            alert('Lỗi khi phân loại yêu cầu: ' + err.message);
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
            alert('Không tải được RAG đang hoạt động: ' + err.message);
        }
    }

    /**
     * Ingests summary data into controller state and renders the shared Criteria editor.
     */
    processRagSummaryData(data) {
        this.currentHrRagText = data.hr_rag_text || '';
        if (this.hrRagPreviewText) {
            this.hrRagPreviewText.textContent = this.currentHrRagText || 'Chưa tạo tệp hr_rag.txt.';
        }
        this.criteriaEditor.setCategories(data.categories || {});
    }

    /**
     * Saves user modifications back to backend vector store & updates hr_rag.txt.
     */
    async saveModifiedCriteria(showSuccessAlert = true) {
        const { stdReq, hiddenReq } = this.readRequirementText();
        // With both textareas empty (HR came in through "Use Active RAG"), omit the text so the
        // server keeps the stored original requirements in hr_rag.txt.
        const hasText = Boolean(stdReq || hiddenReq);

        try {
            const updated = await this.waitingScreen.run(
                'save_criteria',
                'Đang lưu tiêu chí...',
                'Đang embedding lại các tiêu chí vào kho vector RAG và cập nhật hr_rag.txt...',
                () => API.updateRagCriteria(
                    this.criteriaEditor.getCategories(),
                    hasText ? stdReq : null,
                    hasText ? hiddenReq : null
                )
            );
            this.setStoredRagItemCount(updated);
            this.currentHrRagText = updated.hr_rag_text || '';
            if (this.hrRagPreviewText) {
                this.hrRagPreviewText.textContent = this.currentHrRagText;
            }
            if (showSuccessAlert) {
                alert('✓ Đã lưu thay đổi vào kho vector RAG và hr_rag.txt!');
            }
            return true;
        } catch (err) {
            alert('Không lưu được thay đổi tiêu chí: ' + err.message);
            return false;
        }
    }

    /**
     * Updates active RAG summary banner in Candidate Selection stage.
     */
    updateActiveRagBanner() {
        if (!this.activeRagBannerText) return;
        const totalItems = this.criteriaEditor.totalCount();
        this.activeRagBannerText.innerHTML = `<strong>Tiêu chí RAG đã xác minh và đang hoạt động:</strong> ${totalItems} tiêu chí thuộc 5 chiều được lưu trong kho vector ChromaDB.`;
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
        this.scannedContainer.innerHTML = '<div class="loading-state">Đang tải danh sách CV đã quét...</div>';
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
                this.scannedContainer.innerHTML = '<div class="empty-state" style="padding: 1.5rem 0;">Chưa có CV nào được quét. Hãy tải CV PDF lên ở Bước 1 trước.</div>';
                return;
            }
            this.renderScannedList();
        } catch (err) {
            this.scannedContainer.innerHTML = `<div class="error-state">Không tải được danh sách CV: ${this.escapeHtml(err.message)}</div>`;
        }
    }

    /**
     * Renders candidate checkbox list grouped by tier.
     */
    renderScannedList() {
        this.scannedContainer.innerHTML = '';

        const resumes = this.getFilteredResumes();
        if (resumes.length === 0) {
            this.scannedContainer.innerHTML = '<div class="empty-state" style="padding: 1rem 0; font-size: 0.85rem;">Không có ứng viên nào khớp với từ khóa tìm kiếm.</div>';
            return;
        }

        // Secret order status banner
        const banner = document.createElement('div');
        banner.style.cssText = 'padding: 8px 12px; border-radius: 8px; font-size: 0.78rem; font-weight: 600; margin-bottom: 10px; display: flex; align-items: center; justify-content: space-between;';
        if (this.orderActive) {
            banner.style.background = '#DCFCE7';
            banner.style.border = '1px solid #86EFAC';
            banner.style.color = '#15803D';
            banner.innerHTML = `<span>🔒 Thứ tự bí mật: Đang áp dụng</span><span style="font-size:0.72rem; opacity:0.9;">Nhóm 1: ${this.tier1Count} • Nhóm 2: ${this.tier2Count}</span>`;
        } else {
            banner.style.background = '#FFFBEB';
            banner.style.border = '1px solid #FCD34D';
            banner.style.color = '#B45309';
            banner.innerHTML = `<span>⚠️ Thứ tự bí mật: Không tìm thấy tệp</span><span style="font-size:0.72rem;">evaluation_order.txt</span>`;
        }
        this.scannedContainer.appendChild(banner);

        const tiers = {
            1: { title: 'Nhóm CV 1 (Ưu tiên)', badgeClass: 'tier-badge-1', items: [] },
            2: { title: 'Nhóm CV 2 (Thứ cấp)', badgeClass: 'tier-badge-2', items: [] },
            3: { title: 'Nhóm CV 3 (Ứng viên ngoài danh sách)', badgeClass: 'tier-badge-3', items: [] }
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
                    <span class="tier-badge ${group.badgeClass}">${group.items.length} ứng viên</span>
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
            this.selectedCountBadge.textContent = `Đã chọn ${this.selectedResumesSet.size}`;
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
            alert('Vui lòng chọn ít nhất một CV ứng viên.');
            return;
        }

        this.waitingScreen.startBatch(
            'evaluate_candidate',
            `Đang đánh giá ${filenames.length} ứng viên...`,
            'Đang chấm điểm 5 chiều vector RAG theo đúng thứ tự đánh giá...',
            filenames.length
        );

        let data;
        try {
            // Use existing verified RAG criteria
            data = await this.runEvaluationJob(stdReq, hiddenReq, filenames);
        } catch (err) {
            // Close the waiting screen before the blocking alert so it isn't left behind it.
            this.waitingScreen.finish();
            alert('Lỗi đánh giá: ' + err.message);
            return;
        }
        this.waitingScreen.finish();

        try {
            if (data && Array.isArray(data.results)) {
                if (data.results.length === 0) {
                    alert('Không có kết quả đánh giá nào. Hãy kiểm tra các ứng viên đã chọn đã được quét/trích xuất ở Bước 1.');
                } else {
                    this.renderDashboard(data.results);
                }
            } else {
                alert('Đánh giá thất bại: Máy chủ trả về dữ liệu không hợp lệ.');
            }
        } catch (err) {
            alert('Lỗi đánh giá: ' + err.message);
        }
    }

    /**
     * Starts batch evaluation as a background job and polls it, reporting per-candidate
     * progress to the waiting screen, until it finishes.
     * @returns {Promise<Object>} The same results payload the synchronous batch endpoint returns.
     */
    async runEvaluationJob(stdReq, hiddenReq, filenames) {
        const { job_id: jobId } = await API.startEvaluationJob(stdReq, hiddenReq, filenames, true, 'vietnamese');
        for (;;) {
            await new Promise(resolve => setTimeout(resolve, EVAL_JOB_POLL_MS));
            const job = await API.getEvaluationJob(jobId);
            this.waitingScreen.reportProgress(job.completed, job.total);
            if (job.state === 'done') return job.result;
            if (job.state === 'failed') throw new Error(job.error || 'Tác vụ đánh giá thất bại.');
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
        if (this.evalTotalBadge) this.evalTotalBadge.textContent = `Đã đánh giá ${totalCount}`;

        if (!this.tierBlocksContainer) return;
        this.tierBlocksContainer.innerHTML = '';

        const tierGroups = {
            1: { title: 'Nhóm CV 1 (Ứng viên ưu tiên)', badgeClass: 'tier-badge-1', cardClass: 'tier-1-card', items: [] },
            2: { title: 'Nhóm CV 2 (Ứng viên thứ cấp)', badgeClass: 'tier-badge-2', cardClass: 'tier-2-card', items: [] },
            3: { title: 'Nhóm CV 3 (Ứng viên ngoài danh sách)', badgeClass: 'tier-badge-3', cardClass: 'tier-3-card', items: [] }
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
                        <span class="tier-badge ${group.badgeClass}">Nhóm ${tNum}</span>
                    </div>
                    <span class="text-muted" style="font-size: 0.85rem; font-weight:600;">${group.items.length} ứng viên</span>
                </div>
                <div class="table-responsive">
                    <table class="leaderboard-table">
                        <thead>
                            <tr>
                                <th>Hạng</th>
                                <th>Ứng viên / Email</th>
                                <th>Điểm phù hợp</th>
                                <th>Đề xuất</th>
                                <th>Điểm mạnh / Thiếu sót</th>
                                <th>Thao tác</th>
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
                        <span style="font-size:0.78rem; color: var(--text-muted);">✉ ${this.escapeHtml(res.candidate_email || res.candidate_identifier || 'Không có')}</span>
                    </td>
                    <td><strong style="color: var(--brand-azure); font-size:1.2rem; font-family:var(--font-mono);">${res.overall_score || 0}</strong><span style="font-size:0.8rem; color:var(--text-muted);">/100</span></td>
                    <td><span class="badge-rec rec-${res.match_recommendation}">${this.recommendationLabel(res.match_recommendation)}</span></td>
                    <td style="font-size:0.82rem; font-weight:600;">
                        <span style="color:#15803D;">✓ ${res.summary?.total_strengths || 0}</span> • 
                        <span style="color:#B91C1C;">✗ ${res.summary?.total_gaps || 0}</span>
                    </td>
                    <td>
                        <button class="btn btn-sm btn-secondary btn-inspect">Xem hồ sơ</button>
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
        if (fileEl) fileEl.textContent = `${cand.resume_name}.json • Đánh giá lúc ${cand.evaluated_at ? new Date(cand.evaluated_at).toLocaleTimeString('vi-VN') : 'vừa xong'}`;
        if (scoreEl) scoreEl.textContent = cand.overall_score || '0.0';

        if (recBadge) {
            recBadge.textContent = this.recommendationLabel(cand.match_recommendation);
            recBadge.className = `badge-rec rec-${cand.match_recommendation}`;
        }

        // Executive summary body
        if (summaryEl) {
            summaryEl.textContent = cand.summary?.executive_summary || `Ứng viên đạt ${cand.overall_score}/100 điểm, mức độ phù hợp: ${this.recommendationLabel(cand.match_recommendation)}. Được đánh giá theo 5 chiều vector RAG.`;
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
                : '<li>Chưa ghi nhận điểm mạnh rõ ràng.</li>';
        }

        if (gapsListEl) {
            const allGaps = [];
            const dims = cand.dimension_scores || {};
            Object.values(dims).forEach(d => {
                (d.gaps || []).forEach(g => allGaps.push(g));
            });
            gapsListEl.innerHTML = allGaps.length > 0
                ? allGaps.map(g => `<li>${this.escapeHtml(g)}</li>`).join('')
                : '<li>Không có thiếu sót hay rủi ro lớn.</li>';
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
                        <span>${this.escapeHtml(CATEGORY_NAMES[key] || d.category_name)} (${Math.round((d.weight || 0.2) * 100)}%)</span>
                        <span class="dim-score">${d.score}/100</span>
                    </div>
                    <div class="dim-progress-track">
                        <div class="dim-progress-fill" style="width: ${d.score}%;"></div>
                    </div>
                    ${reasoningText ? `
                        <div style="font-size:0.8rem; font-weight:700; margin-top:6px; color: var(--brand-legacy-blue);">🧠 Lập luận của AI:</div>
                        <div class="dim-reasoning-box">${reasoningText}</div>
                    ` : ''}
                    <div style="font-size:0.8rem; font-weight:700; margin-top:6px; color:#15803D;">Điểm mạnh:</div>
                    <ul class="dim-list">${strengthsList || '<li>Không có</li>'}</ul>
                    <div style="font-size:0.8rem; font-weight:700; margin-top:6px; color:#B91C1C;">Thiếu sót / Lưu ý:</div>
                    <ul class="dim-list">${gapsList || '<li>Không có</li>'}</ul>
                `;
                dimensionsContainer.appendChild(card);
            });
        }

        this.detailView.scrollIntoView({ behavior: 'smooth' });
    }

    recommendationLabel(rec) {
        return RECOMMENDATION_LABELS[rec] || rec || '';
    }

    escapeHtml(str) {
        if (!str) return '';
        return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }
}


