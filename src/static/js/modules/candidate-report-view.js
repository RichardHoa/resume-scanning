/**
 * ==============================================================================
 * Candidate Report View (shared detail modal)
 * ==============================================================================
 * Description: The one view of a candidate's full evaluation report, used by the
 *              candidate pool and the evaluator's results. It builds its own modal
 *              markup, then shows per-Category scores and criterion Verdicts,
 *              Must-have tags and Criterion Points, Review Panel feedback, HR
 *              Check Items, the original resume PDF, a PDF download and a
 *              developer panel loaded on demand. Closes on Escape or a click on
 *              the backdrop, and gives focus back to what opened it.
 */

import { API } from './api.js';
import { CATEGORY_NAMES, MUST_HAVE, NICE_TO_HAVE } from './criteria-editor.js';
import { earnedPointsLabel, runSplitLabel } from './criterion-points.js';
import { renderDevDetailsContent, bindDevDetailsContent } from './dev-details-panel.js';
import { byId, downloadBlob } from './dom.js';
import { html, raw } from './html.js';
import {
    KIND, reportKind, isScored, isMissingPosition, mustHaveMisses, shownCategories, failedCategoryNames,
    matchBand, recommendationLabel, scoreBand, overallScoreTone, candidateIdentity,
    FAILED_EVALUATION_LABEL, SCANNED_RESUME_LABEL, SCANNED_RESUME_MESSAGE, MISSING_POSITION_LABEL,
    MISSING_POSITION_MESSAGE, MUST_HAVE_REJECTION_LABEL, MUST_HAVE_REJECTION_MESSAGE
} from './report.js';

const FEEDBACK_TITLE = 'Nhận xét của hội đồng đánh giá';
const FEEDBACK_FAILED_LABEL = 'Không thể tạo nhận xét';
const DEV_DETAILS_TITLE = 'Chi tiết cho nhà phát triển';
const MUST_HAVE_TAG = raw('<span class="modal-must-have-tag">Bắt buộc</span>');

// Review Panel Panelists, in display order (keys match candidate_feedback.panelist_views)
const PANELIST_NAMES = {
    leadership: 'Lãnh đạo',
    domain_expertise: 'Chuyên môn',
    people_culture: 'Con người & Văn hóa'
};

// Built once per page; the header is filled in on each open
const MODAL_MARKUP = `
    <div class="modal-overlay" id="cand-detail-modal" role="dialog" aria-modal="true" aria-labelledby="modal-cand-name" hidden>
        <div class="modal-card">
            <div class="modal-header">
                <div class="modal-header-info">
                    <h2 id="modal-cand-name">Tên ứng viên</h2>
                    <span class="modal-subtext" id="modal-cand-role"></span>
                </div>
                <div class="modal-header-actions">
                    <div class="modal-score-box" id="modal-cand-score"></div>
                    <button class="btn btn-secondary btn-sm" id="modal-btn-resume" type="button">Xem CV</button>
                    <button class="btn btn-secondary btn-sm" id="modal-btn-download" type="button">
                        <svg class="icon-svg" viewBox="0 0 24 24" aria-hidden="true" focusable="false"><path d="M19 9h-4V3H9v6H5l7 7 7-7zM5 18v2h14v-2H5z"/></svg> Tải PDF
                    </button>
                    <button class="modal-close-btn" id="modal-close-btn" aria-label="Đóng chi tiết ứng viên" type="button">&times;</button>
                </div>
            </div>
            <div class="modal-body" id="modal-cand-body"></div>
        </div>
    </div>
`;

/**
 * A Criterion's Criterion Points as stored in the report: earned / max out of its Category's 100,
 * or the bonus a Nice-to-have added, which never costs points when missing.
 * @param {Object} c - One entry of a Category's criteria_evaluations.
 */
function pointsTag(c) {
    return html`<span class="modal-points-tag">${earnedPointsLabel(c.earned_points, c.max_points, c.importance === NICE_TO_HAVE)}</span>`;
}

/**
 * How many evaluation runs gave the Criterion its shown Verdict, so HR can tell a clear Verdict from a close one;
 * nothing after a single run.
 * @param {Object} c - One entry of a Category's criteria_evaluations.
 */
function runSplitTag(c) {
    const label = runSplitLabel(c);
    return label && html`<span class="modal-run-split-tag" title="Số lần đánh giá cho kết quả này">${label}</span>`;
}

/** A titled bullet list, or nothing when the list is empty. */
function bulletSection(title, items, cls) {
    return items.length > 0 && html`
        <div class="modal-section-title">${title}</div>
        <ul class="modal-bullets ${cls}">${items.map(i => html`<li>${i}</li>`)}</ul>
    `;
}

/** A warning callout at the top of the report: icon, upper-case label and explanation. */
function alertBanner(icon, label, message) {
    return html`
        <div class="modal-alert-banner">
            <div class="modal-alert-icon">${icon}</div>
            <div class="modal-alert-content">
                <strong>${label.toUpperCase()}</strong>
                <p>${message}</p>
            </div>
        </div>
    `;
}

export class CandidateReportView {
    constructor() {
        this.report = null;
        this.evaluationHtml = '';
        this.showingResume = false;
        this.lastFocusedElement = null;

        document.body.insertAdjacentHTML('beforeend', MODAL_MARKUP);
        this.modal = byId('cand-detail-modal');
        this.nameEl = byId('modal-cand-name');
        this.roleEl = byId('modal-cand-role');
        this.scoreEl = byId('modal-cand-score');
        this.body = byId('modal-cand-body');
        this.btnClose = byId('modal-close-btn');
        this.btnDownload = byId('modal-btn-download');
        this.btnResume = byId('modal-btn-resume');

        this.btnClose.addEventListener('click', () => this.close());
        this.modal.addEventListener('click', (e) => {
            if (e.target === this.modal) this.close();
        });
        document.addEventListener('keydown', (e) => {
            if (e.key === 'Escape' && !this.modal.hidden) this.close();
        });
        this.btnDownload.addEventListener('click', () => this.downloadReportPdf());
        this.btnResume.addEventListener('click', () => this.toggleResumeView());
    }

    /**
     * Opens the modal on a candidate's full evaluation report.
     * @param {Object} report - Evaluation report, as listed by /api/eval_results or returned by a batch.
     * @param {HTMLElement} triggerEl - The element that opened it; it gets focus back on close.
     */
    open(report, triggerEl) {
        this.lastFocusedElement = triggerEl;
        this.report = report;

        const { name, email } = candidateIdentity(report);
        const scored = isScored(report);
        const evaluatedAt = report.evaluated_at ? new Date(report.evaluated_at).toLocaleString('vi-VN') : 'Không có';

        // Name, email, match, score and evaluation time appear once, in the modal header
        this.nameEl.innerHTML = html`${name} <span class="match-pill band-${matchBand(report)}">${recommendationLabel(report)}</span>`;
        this.roleEl.innerHTML = html`${email && html`<a href="mailto:${email}" class="modal-email-link">${email}</a> • `}Đánh giá lúc ${evaluatedAt}`;
        this.scoreEl.innerHTML = html`
            <span class="modal-score-number score--${overallScoreTone(report)}">${scored ? Number(report.overall_score).toFixed(1) : '—'}</span>
            <span class="modal-score-label">Tổng điểm</span>
        `;
        // A batch's Failed Evaluation of an unreadable file has no report file to build a PDF from
        this.btnDownload.hidden = !report.filename;

        const kind = reportKind(report);
        // An unscored report has no Category scores to show; a Failed Evaluation's partial ones are hidden
        this.evaluationHtml = html`
            ${this.renderMustHaveRejection(mustHaveMisses(report))}
            ${isMissingPosition(report) && alertBanner('⚠️', MISSING_POSITION_LABEL, MISSING_POSITION_MESSAGE)}
            ${kind === KIND.FAILED && alertBanner('⛔', FAILED_EVALUATION_LABEL, this.failedEvaluationMessage(report))}
            ${kind === KIND.SCANNED && alertBanner('⛔', SCANNED_RESUME_LABEL, SCANNED_RESUME_MESSAGE)}
            ${scored && this.renderCandidateFeedback(report.candidate_feedback)}
            ${this.renderHrCheckItems(report.hr_check_items || [])}
            <div class="modal-dim-grid">${scored && Object.entries(shownCategories(report)).map(([key, d]) => this.renderCategory(key, d))}</div>
            ${this.renderDevDetails(report)}
        `;
        this.showEvaluation();

        this.modal.hidden = false;
        document.body.style.overflow = 'hidden';
        this.btnClose.focus();
    }

    /**
     * Closes the modal and restores keyboard focus.
     */
    close() {
        this.modal.hidden = true;
        document.body.style.overflow = '';
        this.report = null;
        // Drops the resume iframe, so the next candidate opens on the evaluation view
        this.evaluationHtml = '';
        this.showEvaluation();
        this.lastFocusedElement.focus();
    }

    /** Why a Failed Evaluation has no result, naming the Categories it could not score when it knows them. */
    failedEvaluationMessage(report) {
        const names = failedCategoryNames(report);
        const what = names.length > 0 ? `các mục: ${names.join(', ')}` : 'một số mục đánh giá';
        return `Không thể chấm điểm ${what}. Kết quả này không được xếp hạng. Hãy chọn lại ứng viên này và bấm Đánh giá để chạy lại.`;
    }

    /**
     * One Category's card: weight, score bar, strengths, criteria met and without evidence, and gaps.
     * @param {string} catKey - Category key of dimension_scores.
     * @param {Object} d - That Category's result.
     */
    renderCategory(catKey, d) {
        return html`
            <div class="modal-dim-card">
                <div class="modal-dim-header">
                    <div class="modal-dim-title">
                        ${CATEGORY_NAMES[catKey]}
                        <span class="modal-dim-weight">Trọng số: ${(d.weight * 100).toFixed(0)}%</span>
                    </div>
                    <div>
                        <span class="dim-score-pill">${d.score.toFixed(1)} / 100</span>
                    </div>
                </div>
                <div class="modal-dim-progress">
                    <div class="modal-dim-progress-fill bar-fill--${scoreBand(d.score)}" style="width: ${Math.min(100, Math.max(5, d.score))}%;"></div>
                </div>
                ${d.bonus_capped && html`<div class="modal-dim-capped-note">Đã đạt tối đa 100 điểm</div>`}
                ${bulletSection('Điểm mạnh chính:', d.strengths, 'strengths')}
                ${this.renderCategoryMetCriteria(d)}
                ${this.renderCategoryNoEvidence(d)}
                ${bulletSection('Thiếu sót đã xác định:', d.gaps, 'gaps')}
            </div>
        `;
    }

    /**
     * Renders the Must-have Rejection banner: the must-have Criteria the resume shows no evidence for.
     * @param {Array<{category: string, criterion: string}>} items - The report's must_have_rejection.
     * @returns {SafeHtml|false} The banner, or nothing when the candidate was not rejected.
     */
    renderMustHaveRejection(items) {
        return items.length > 0 && html`
            <div class="modal-must-have-rejection-banner" role="note">
                <strong>${MUST_HAVE_REJECTION_LABEL.toUpperCase()}: ${items.length} tiêu chí</strong>
                <p>${MUST_HAVE_REJECTION_MESSAGE}</p>
                <ul class="modal-bullets gaps">${items.map(m => html`
                    <li>${m.criterion} <span class="modal-must-have-rejection-cat">(${CATEGORY_NAMES[m.category]})</span></li>
                `)}</ul>
            </div>
        `;
    }

    /**
     * Renders the HR Check Items: requirements no resume would show, never scored, listed for HR to check by hand.
     * Failed and Scanned reports have none.
     * @param {Array<string>} items - The report's hr_check_items.
     * @returns {SafeHtml|false} The card, or nothing when there are none.
     */
    renderHrCheckItems(items) {
        return items.length > 0 && html`
            <div class="modal-hr-check-card">
                <div class="modal-dim-title">Cần HR kiểm tra thủ công</div>
                <p class="modal-hr-check-note">CV thông thường không thể hiện các yêu cầu này, nên ứng viên không bị chấm điểm theo chúng. Hãy kiểm tra trực tiếp, ví dụ khi phỏng vấn.</p>
                <ul class="modal-bullets">${items.map(i => html`<li>${i}</li>`)}</ul>
            </div>
        `;
    }

    /**
     * Renders a Category's criteria judged STRONG or PARTIAL, each followed by the resume quotes that support it.
     * @param {Object} d - One entry of the report's dimension_scores.
     * @returns {SafeHtml|false} The section, or nothing when no criterion has evidence.
     */
    renderCategoryMetCriteria(d) {
        const met = d.criteria_evaluations.filter(c => c.verdict === 'STRONG_EVIDENCE' || c.verdict === 'PARTIAL_EVIDENCE');
        return met.length > 0 && html`
            <div class="modal-section-title">Tiêu chí đáp ứng:</div>
            <ul class="modal-bullets strengths">${met.map(c => html`
                <li>
                    ${c.criterion}${c.importance === MUST_HAVE && MUST_HAVE_TAG}${c.verdict === 'PARTIAL_EVIDENCE' && raw('<span class="modal-partial-tag">Đáp ứng một phần</span>')}${runSplitTag(c)}${pointsTag(c)}
                    ${(c.evidence_quotes || []).map(q => html`<div class="modal-quote-box">"${q}"</div>`)}
                </li>
            `)}</ul>
        `;
    }

    /**
     * Renders a Category's criteria judged NO_EVIDENCE: requirements the resume shows nothing for.
     * @param {Object} d - One entry of the report's dimension_scores.
     * @returns {SafeHtml|false} The section, or nothing when no criterion lacks evidence.
     */
    renderCategoryNoEvidence(d) {
        const missing = d.criteria_evaluations.filter(c => c.verdict === 'NO_EVIDENCE');
        return missing.length > 0 && html`
            <div class="modal-section-title">Tiêu chí chưa có bằng chứng:</div>
            <ul class="modal-bullets gaps">${missing.map(c => html`<li>${c.criterion}${c.importance === MUST_HAVE && MUST_HAVE_TAG}${runSplitTag(c)}${pointsTag(c)}</li>`)}</ul>
        `;
    }

    /**
     * Renders the Review Panel's Candidate Feedback card, with each Panelist's final view collapsed.
     * Skipped or absent feedback (scoring-only runs, Must-have Rejections) renders nothing.
     * @param {Object} [feedback] - The report's candidate_feedback object.
     * @returns {SafeHtml|false} The card, or nothing when there is nothing to show.
     */
    renderCandidateFeedback(feedback) {
        if (!feedback) return false;
        if (feedback.status === 'failed') {
            return html`
                <div class="modal-feedback-card">
                    <div class="modal-dim-title">${FEEDBACK_TITLE}</div>
                    <div class="modal-feedback-failed">${FEEDBACK_FAILED_LABEL}</div>
                </div>
            `;
        }
        if (feedback.status !== 'ok') return false;

        const views = feedback.panelist_views || {};
        const panelists = Object.keys(PANELIST_NAMES).filter(key => views[key]);
        return html`
            <div class="modal-feedback-card">
                <div class="modal-dim-title">${FEEDBACK_TITLE}</div>
                ${feedback.summary && html`<div class="modal-reasoning-box">${feedback.summary}</div>`}
                ${bulletSection('Điểm mạnh:', feedback.strengths, 'strengths')}
                ${bulletSection('Điểm yếu và kỹ năng còn thiếu:', feedback.weaknesses, 'gaps')}
                ${panelists.length > 0 && html`
                    <div class="modal-section-title">Ý kiến từng thành viên hội đồng:</div>
                    ${panelists.map(key => html`
                        <details class="modal-panelist-view">
                            <summary>${PANELIST_NAMES[key]}</summary>
                            <div class="modal-panelist-view-text">${views[key]}</div>
                        </details>
                    `)}
                `}
            </div>
        `;
    }

    /**
     * The collapsed developer panel at the bottom of the evaluation: everything the run folder holds for this
     * resume, loaded only when opened. HR never needs it.
     * @param {Object} report - Evaluation report.
     * @returns {SafeHtml|false} The panel, or nothing without a result file name.
     */
    renderDevDetails(report) {
        return Boolean(report.filename) && html`
            <details class="modal-dev-details" id="modal-dev-details">
                <summary>${DEV_DETAILS_TITLE}</summary>
                <div class="modal-dev-body" id="modal-dev-body"><div class="loading-state">Đang tải…</div></div>
            </details>
        `;
    }

    /**
     * Loads the developer panel's contents the first time it is opened.
     */
    bindDevDetails() {
        const details = this.body.querySelector('#modal-dev-details');
        const report = this.report;
        if (!details) return;
        details.addEventListener('toggle', async () => {
            if (!details.open || details.dataset.loaded) return;
            details.dataset.loaded = 'true';
            const body = details.querySelector('#modal-dev-body');
            try {
                const dev = await API.getDevDetails(report.filename);
                // The modal may have moved on to another candidate while loading
                if (this.report !== report) return;
                body.innerHTML = renderDevDetailsContent(dev, report.filename);
                bindDevDetailsContent(body);
            } catch (err) {
                delete details.dataset.loaded;
                body.innerHTML = html`<div class="error-state">${err.message}</div>`;
            }
        });
    }

    /**
     * Shows the evaluation in the modal body (the default view).
     */
    showEvaluation() {
        this.showingResume = false;
        this.body.classList.remove('modal-body-resume');
        this.body.innerHTML = this.evaluationHtml;
        this.bindDevDetails();
        this.body.scrollTop = 0;
        this.btnResume.textContent = 'Xem CV';
    }

    /**
     * Replaces the evaluation in the modal body with the candidate's original resume PDF.
     */
    showResume() {
        const report = this.report;
        this.showingResume = true;
        this.body.classList.add('modal-body-resume');
        this.btnResume.textContent = '← Quay lại đánh giá';

        if (!report.has_resume_pdf || !report.filename) {
            this.body.innerHTML = '<div class="modal-resume-missing">Chưa lưu PDF cho ứng viên này — hãy tải lên lại.</div>';
            return;
        }
        const url = API.resumePdfUrl(report.filename);
        this.body.innerHTML = html`
            <div class="modal-resume-toolbar">
                <a class="btn btn-secondary btn-sm" href="${url}" target="_blank" rel="noopener">Mở trong tab mới ↗</a>
            </div>
            <iframe class="modal-resume-frame" src="${url}" title="CV của ${candidateIdentity(report).name}"></iframe>
        `;
    }

    /**
     * Switches the modal body between the evaluation and the resume PDF.
     */
    toggleResumeView() {
        if (this.showingResume) this.showEvaluation();
        else this.showResume();
    }

    /**
     * Downloads the candidate's evaluation report as a PDF, with the resume PDF appended when stored.
     */
    async downloadReportPdf() {
        const report = this.report;
        const btn = this.btnDownload;
        const originalHtml = btn.innerHTML;
        btn.disabled = true;
        btn.textContent = 'Đang tạo PDF…';
        try {
            const blob = await API.getReportPdf(report.filename);
            downloadBlob(blob, `${report.filename.replace(/\.json$/i, '')}_danh_gia.pdf`);
        } catch (err) {
            alert(err.message);
        } finally {
            btn.disabled = false;
            btn.innerHTML = originalHtml;
        }
    }
}
