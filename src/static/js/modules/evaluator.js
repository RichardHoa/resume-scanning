/**
 * ==============================================================================
 * Step 2: HR Evaluator Controller
 * ==============================================================================
 * Description: Manages the 4-step HR workflow:
 *              1. Input requirements & decompose into 5-dimension RAG criteria + hr_rag.txt
 *              2. Inspect & freely edit/adjust RAG criteria before evaluation
 *              3. Candidate selection with live filtering & secret tier ordering (ResumeSelection)
 *              4. AI batch evaluation against verified RAG criteria, run as a server Batch job
 *                 (reconnected to after a reload), with KPI statistics and leaderboards (ResultsDashboard)
 */

import { API } from './api.js';
import { CriteriaEditor, CATEGORY_NAMES } from './criteria-editor.js';
import { WaitingScreen } from './waiting-screen.js';
import { BatchStore, followBatchJob, offerRunningBatch, runningBatchFromRefusal } from './batch-job.js';
import { ResumeSelection } from './resume-selection.js';
import { ResultsDashboard } from './results-dashboard.js';
import { byId } from './dom.js';
import { html } from './html.js';

export class EvaluatorController {
    constructor() {
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
        this.resumeSelection = new ResumeSelection(count => { this.btnRunEval.disabled = count === 0; });
        this.dashboard = new ResultsDashboard();
        this.initEvents();
        this.checkExistingRag();
        this.resumeSelection.load();
        this.reconnectToRunningBatch();
    }

    /**
     * Binds DOM element references across all stages.
     */
    initDOMElements() {
        // Stage containers, in step order
        this.stages = ['eval-req-stage', 'eval-rag-verify-stage', 'eval-candidates-stage', 'eval-results-stage'].map(byId);
        // Stepped nav steps (1 to 4)
        this.stepNavs = [1, 2, 3, 4].map(n => byId(`step-nav-${n}`));

        // Inputs & Buttons - Step 1
        this.hrStdReqInput = byId('hr-std-req');
        this.hrHiddenReqInput = byId('hr-hidden-req');
        this.btnDecomposeReqs = byId('btn-decompose-reqs');
        this.btnUseExistingRag = byId('btn-use-existing-rag');

        // Step 1: Clarification Questions (Implicit Assumption scrutiny), shown beside each field
        this.intakePanel = byId('intake-panel');
        this.scrutinyPanel = byId('scrutiny-panel');
        this.scrutinyListStandard = byId('scrutiny-list-standard');
        this.scrutinyListHidden = byId('scrutiny-list-hidden');
        this.btnProceedDecompose = byId('btn-proceed-decompose');

        // Step 2: RAG Verification & Editor
        this.criteriaEditorContainer = byId('criteria-editor-container');
        this.hrRagPreviewText = byId('hr-rag-preview-text');
        this.tabBtnCategories = byId('tab-btn-categories');
        this.tabBtnRawFile = byId('tab-btn-raw-file');
        this.paneCategoriesEditor = byId('pane-categories-editor');
        this.paneRawFile = byId('pane-raw-file');
        this.btnBackToReqs = byId('btn-back-to-requirements');
        this.btnSaveCriteriaChanges = byId('btn-save-criteria-changes');
        this.btnProceedToCandidates = byId('btn-proceed-to-candidates');

        // Step 3: Candidate Selection (the list itself is ResumeSelection's)
        this.activeRagBannerText = byId('active-rag-banner-text');
        this.btnBackToRagVerify = byId('btn-back-to-rag-verify');
        this.btnBackToCriteriaStep = byId('btn-back-to-criteria-step');
        this.btnRunEval = byId('btn-run-eval');

        // Step 4: Results (the leaderboards are ResultsDashboard's)
        this.btnModifyCriteria = byId('btn-modify-criteria');
    }

    /**
     * Binds event listeners across the 4-step workflow.
     */
    initEvents() {
        // Step 1 triggers
        this.btnDecomposeReqs.addEventListener('click', () => this.handleDecomposeClick());
        this.btnProceedDecompose.addEventListener('click', () => this.decomposeFromQuestionsPanel());
        this.btnUseExistingRag.addEventListener('click', () => this.useExistingRagAndProceed());
        [this.hrStdReqInput, this.hrHiddenReqInput].forEach(input => {
            input.addEventListener('input', () => this.updateUseExistingRagVisibility());
        });

        // Step 2 triggers (RAG Verification & Tabs)
        this.tabBtnCategories.addEventListener('click', () => this.switchRagTab('categories'));
        this.tabBtnRawFile.addEventListener('click', () => this.switchRagTab('raw'));
        this.btnBackToReqs.addEventListener('click', () => this.goToStage(1));
        this.btnSaveCriteriaChanges.addEventListener('click', () => this.saveModifiedCriteria(true));
        this.btnProceedToCandidates.addEventListener('click', async () => {
            // Stay on the Verify step when the save fails; saveModifiedCriteria shows the error.
            if (await this.saveModifiedCriteria(false)) this.goToStage(3);
        });

        // Step 3 triggers (Candidate Selection)
        this.btnBackToRagVerify.addEventListener('click', () => this.goToStage(2));
        this.btnBackToCriteriaStep.addEventListener('click', () => this.goToStage(1));
        this.btnRunEval.addEventListener('click', () => this.runEvaluation());

        // Step 4 triggers (Results)
        this.btnModifyCriteria.addEventListener('click', () => this.goToStage(2));
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
        this.storedRagItemCount = summary.has_stored_rag ? summary.total_items : 0;
        this.updateUseExistingRagVisibility();
    }

    /**
     * "Use Active RAG & Skip" shows only when the RAG has stored Criteria and both requirement
     * textareas are empty, so HR can't throw away new requirements they are typing.
     */
    updateUseExistingRagVisibility() {
        const { stdReq, hiddenReq } = this.readRequirementText();
        const visible = this.storedRagItemCount > 0 && !stdReq && !hiddenReq;
        this.btnUseExistingRag.hidden = !visible;
        if (visible) {
            this.btnUseExistingRag.textContent = `Dùng tiêu chí đã lưu (${this.storedRagItemCount} tiêu chí) & Chọn ứng viên →`;
        }
    }

    readRequirementText() {
        return {
            stdReq: this.hrStdReqInput.value.trim(),
            hiddenReq: this.hrHiddenReqInput.value.trim()
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
        this.stages.forEach((stage, idx) => { stage.hidden = idx + 1 !== stepNum; });
        this.updateStepIndicator(stepNum);

        if (stepNum === 3 && this.resumeSelection.resumes.length === 0) {
            this.resumeSelection.load();
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
     * Updates top progress step indicators; the active step carries aria-current.
     */
    updateStepIndicator(activeStep) {
        this.stepNavs.forEach((stepEl, idx) => {
            const stepNum = idx + 1;
            stepEl.classList.toggle('active', stepNum === activeStep);
            stepEl.classList.toggle('completed', stepNum < activeStep);
            if (stepNum === activeStep) stepEl.setAttribute('aria-current', 'step');
            else stepEl.removeAttribute('aria-current');
        });
    }

    /**
     * Toggles between Interactive Categories Editor and Raw hr_rag.txt View.
     */
    switchRagTab(tab) {
        const showCategories = tab === 'categories';
        this.tabBtnCategories.classList.toggle('active', showCategories);
        this.tabBtnRawFile.classList.toggle('active', !showCategories);
        this.paneCategoriesEditor.hidden = !showCategories;
        this.paneRawFile.hidden = showCategories;
        if (showCategories) this.criteriaEditor.resizeAll();
    }

    /**
     * Main "Decompose" button. Runs the Implicit Assumption clarification check once per pass:
     * on the first Decompose of a pass, or after returning from Category review with changed
     * text. Decomposes directly otherwise, or when the check finds no Implicit Assumptions.
     */
    async handleDecomposeClick() {
        const { stdReq, hiddenReq } = this.readRequirementText();

        if (!stdReq && !hiddenReq) {
            alert('Vui lòng nhập Yêu cầu công việc tiêu chuẩn hoặc Yêu cầu ẩn trước khi tạo tiêu chí.');
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
        let stdSplits;
        let hiddenSplits;
        try {
            const result = await this.waitingScreen.run(
                'scrutiny',
                'Đang kiểm tra yêu cầu...',
                'Đang tìm chỗ chưa rõ và các dòng gộp nhiều yêu cầu...',
                () => API.scrutinizeRequirements(stdReq, hiddenReq)
            );
            this.intake.checkedText = { std: stdReq, hidden: hiddenReq };
            this.intake.checkedThisPass = true;
            stdFindings = result.standard_requirements || [];
            hiddenFindings = result.hidden_requirements || [];
            const splits = result.split_suggestions || {};
            stdSplits = splits.standard_requirements || [];
            hiddenSplits = splits.hidden_requirements || [];
        } catch (err) {
            // Fail closed: a broken scrutiny call likely means decomposition would fail too.
            alert('Lỗi khi kiểm tra yêu cầu: ' + err.message);
            return;
        }

        if ([stdFindings, hiddenFindings, stdSplits, hiddenSplits].every(list => list.length === 0)) {
            await this.decomposeRequirements(stdReq, hiddenReq);
            return;
        }

        this.renderScrutinyPanel(stdFindings, hiddenFindings, stdSplits, hiddenSplits);
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
     * Shows Clarification Questions, and the Combined Requirements HR could split, beside the
     * field they refer to and swaps the main Decompose button for the panel's own.
     */
    renderScrutinyPanel(stdFindings, hiddenFindings, stdSplits, hiddenSplits) {
        const renderList = (listEl, findings, splits) => {
            const questions = findings.length > 0
                ? html`${findings.map(f => html`
                    <div class="scrutiny-question-item">
                        <div class="scrutiny-question">${f.question}</div>
                    </div>
                `)}`
                : html`<div class="scrutiny-empty-note">Không có câu hỏi</div>`;
            const splitBlock = splits.length > 0 && html`
                    <div class="scrutiny-split-title">Gợi ý tách yêu cầu (mỗi dòng chỉ nên có 1 yêu cầu)</div>
                    ${splits.map(split => html`
                        <div class="scrutiny-question-item scrutiny-split-item">
                            <div class="scrutiny-split-original">“${split.requirement}”</div>
                            <div class="scrutiny-split-hint">Nên viết thành các dòng riêng:</div>
                            <ul class="scrutiny-split-parts">${split.parts.map(part => html`<li>${part}</li>`)}</ul>
                        </div>
                    `)}`;
            listEl.innerHTML = html`${questions}${splitBlock}`;
        };

        renderList(this.scrutinyListStandard, stdFindings, stdSplits);
        renderList(this.scrutinyListHidden, hiddenFindings, hiddenSplits);

        this.intake.questionsShowing = true;
        this.intakePanel.classList.add('has-questions');
        this.scrutinyPanel.hidden = false;
        this.btnDecomposeReqs.hidden = true;
        this.btnProceedDecompose.hidden = false;
        this.intakePanel.scrollIntoView({ behavior: 'smooth', block: 'start' });
    }

    hideScrutinyPanel() {
        this.intake.questionsShowing = false;
        this.intakePanel.classList.remove('has-questions');
        this.scrutinyPanel.hidden = true;
        this.scrutinyListStandard.innerHTML = '';
        this.scrutinyListHidden.innerHTML = '';
        this.btnProceedDecompose.hidden = true;
        this.btnDecomposeReqs.hidden = false;
    }

    /**
     * Step 1 -> Step 2: Decomposes requirements using LLM and populates the editor.
     */
    async decomposeRequirements(stdReq, hiddenReq) {
        if (!stdReq && !hiddenReq) {
            alert('Vui lòng nhập Yêu cầu công việc tiêu chuẩn hoặc Yêu cầu ẩn trước khi tạo tiêu chí.');
            return;
        }

        try {
            const data = await this.waitingScreen.run(
                'decompose',
                'Đang tạo tiêu chí chấm điểm...',
                'AI đang tách yêu cầu của bạn thành từng tiêu chí và xếp vào 5 nhóm...',
                () => API.decomposeRequirements(stdReq, hiddenReq)
            );
            this.processRagSummaryData(data);
            this.setStoredRagItemCount(data);
            this.goToStage(2);
        } catch (err) {
            alert('Lỗi khi tạo tiêu chí: ' + err.message);
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
            alert('Không tải được tiêu chí đã lưu: ' + err.message);
        }
    }

    /**
     * Shows the hr_rag.txt preview in the Verify step's raw-file tab.
     */
    setHrRagText(text) {
        this.hrRagPreviewText.textContent = text || 'Chưa có tiêu chí nào.';
    }

    /**
     * Ingests summary data into controller state and renders the shared Criteria editor.
     */
    processRagSummaryData(data) {
        this.setHrRagText(data.hr_rag_text);
        this.criteriaEditor.setCategories(data.categories, data.hr_check_items, data.importance_levels, data.default_importance);
    }

    /**
     * Saves user modifications back to backend vector store & updates hr_rag.txt.
     */
    async saveModifiedCriteria(showSuccessAlert = true) {
        const { stdReq, hiddenReq } = this.readRequirementText();
        // With both textareas empty (HR came in through "Use Active RAG"), omit the text so the
        // server keeps the stored original requirements in hr_rag.txt.
        const hasText = Boolean(stdReq || hiddenReq);
        if (!this.criteriaEditor.confirmSavable()) return false;

        try {
            const updated = await this.waitingScreen.run(
                'save_criteria',
                'Đang lưu tiêu chí...',
                'Đang lưu các tiêu chí để dùng khi chấm CV...',
                () => API.updateRagCriteria(
                    this.criteriaEditor.getCategories(),
                    this.criteriaEditor.getHrCheckItems(),
                    hasText ? stdReq : null,
                    hasText ? hiddenReq : null
                )
            );
            this.setStoredRagItemCount(updated);
            this.setHrRagText(updated.hr_rag_text);
            if (showSuccessAlert) {
                alert('✓ Đã lưu tiêu chí!');
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
        const totalItems = this.criteriaEditor.totalCount();
        const categoryCount = Object.keys(CATEGORY_NAMES).length;
        this.activeRagBannerText.innerHTML = html`<strong>Tiêu chí đang dùng:</strong> ${totalItems} tiêu chí trong ${categoryCount} nhóm. CV sẽ được chấm theo các tiêu chí này.`;
    }

    /**
     * Submits verified RAG criteria and candidate selection to run batch AI evaluation.
     */
    async runEvaluation() {
        const { stdReq, hiddenReq } = this.readRequirementText();
        const filenames = this.resumeSelection.selectedFilenames();
        if (filenames.length === 0) {
            alert('Vui lòng chọn ít nhất một CV ứng viên.');
            return;
        }

        let started;
        try {
            started = await API.startEvaluationJob(stdReq, hiddenReq, filenames);
        } catch (err) {
            const running = runningBatchFromRefusal(err);
            if (running) offerRunningBatch(running, r => this.followJob(r.jobId), 'evaluate');
            else alert('Lỗi đánh giá: ' + err.message);
            return;
        }
        BatchStore.rememberRunning(started.job_id, 'evaluate');
        await this.followJob(started.job_id, filenames.length);
    }

    /** After a reload, follows the evaluation Batch this browser started, if the server still has it. */
    reconnectToRunningBatch() {
        const running = BatchStore.running();
        if (running && running.kind === 'evaluate') this.followJob(running.jobId);
    }

    /**
     * Follows an evaluation job on the waiting screen, every candidate with its state, then opens Step 4 with
     * every candidate that finished; a stopped Batch shows the ones that finished before it stopped.
     * @param {string} jobId
     * @param {number} [total=0] - Candidates in the Batch, until the first status says.
     */
    async followJob(jobId, total = 0) {
        this.waitingScreen.startBatch(
            'evaluate_candidate',
            'Đang đánh giá hàng loạt ứng viên...',
            'Các ứng viên được chấm điểm song song theo các tiêu chí đã lưu, theo đúng thứ tự đánh giá. Có thể dừng lô: ứng viên đang xử lý vẫn được hoàn tất.',
            total,
            () => API.cancelBatchJob(jobId)
        );

        let job;
        try {
            job = await followBatchJob(jobId, this.waitingScreen);
        } catch (err) {
            // Close the waiting screen before the blocking alert so it isn't left behind it.
            this.waitingScreen.finish();
            // The server no longer has it (expired or restarted): nothing left to reconnect to
            if (err.status === 404) BatchStore.forgetRunning();
            else alert('Lỗi đánh giá: ' + err.message);
            return;
        }
        this.waitingScreen.finish();
        BatchStore.forgetRunning();

        if (job.state === 'failed') {
            alert('Lỗi đánh giá: ' + (job.error || 'Tác vụ đánh giá thất bại.'));
            return;
        }
        const data = job.result;
        if (!data || !Array.isArray(data.results)) {
            alert('Đánh giá thất bại: Máy chủ trả về dữ liệu không hợp lệ.');
            return;
        }
        if (data.results.length === 0) {
            alert(job.state === 'cancelled'
                ? 'Lô đã dừng trước khi có ứng viên nào được đánh giá xong.'
                : 'Không có kết quả đánh giá nào. Hãy kiểm tra các ứng viên đã chọn đã được quét/trích xuất ở Bước 1.');
            return;
        }
        this.goToStage(4);
        this.dashboard.render(data.results, this.resumeSelection.techMode);
    }
}
