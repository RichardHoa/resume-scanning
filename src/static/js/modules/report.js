/**
 * ==============================================================================
 * Evaluation report model
 * ==============================================================================
 * Description: What a candidate's evaluation report is, as every page shows it.
 *              A report has one kind (ranked, Must-have Rejection, Failed
 *              Evaluation or Scanned Resume) and one match band; the labels,
 *              tiers and result sections all derive from those.
 */

import { CATEGORY_NAMES } from './criteria-editor.js';

export const KIND = { RANKED: 'ranked', REJECTED: 'rejected', FAILED: 'failed', SCANNED: 'scanned' };

export const FAILED_EVALUATION_LABEL = 'Lỗi – cần chạy lại';
export const SCANNED_RESUME_LABEL = 'CV bản scan – không đọc được';
export const SCANNED_RESUME_MESSAGE = 'CV là bản scan (không có lớp văn bản), hệ thống không đọc được nên không chấm điểm hay xếp hạng. Vui lòng yêu cầu ứng viên gửi bản PDF có thể chọn chữ.';
export const MISSING_POSITION_LABEL = 'Thiếu vị trí ứng tuyển';
export const MISSING_POSITION_MESSAGE = 'CV không ghi vị trí ứng tuyển; hệ thống mặc định ứng viên ứng tuyển vị trí này và vẫn đánh giá, xếp hạng như bình thường.';
export const MUST_HAVE_REJECTION_LABEL = 'Bị loại – thiếu tiêu chí bắt buộc';
export const MUST_HAVE_REJECTION_MESSAGE = 'CV không cho thấy bằng chứng cho các tiêu chí HR đánh dấu là bắt buộc dưới đây, nên ứng viên bị loại và không được xếp hạng. Điểm vẫn được giữ để HR tham khảo. Nếu CV chỉ bỏ sót thông tin, hãy đổi mức độ quan trọng của tiêu chí trong trang RAG rồi đánh giá lại ứng viên.';
export const REJECTED_SECTION_TITLE = MUST_HAVE_REJECTION_LABEL;
export const SCANNED_SECTION_TITLE = 'CV bản scan – cần ứng viên gửi lại';

// Display text for the match_recommendation keys
export const RECOMMENDATION_LABELS = {
    STRONG_MATCH: 'PHÙ HỢP CAO',
    POTENTIAL_MATCH: 'CÓ TIỀM NĂNG',
    LOW_MATCH: 'PHÙ HỢP THẤP',
    REJECT: 'LOẠI',
    MUST_HAVE_REJECTED: MUST_HAVE_REJECTION_LABEL
};

/**
 * The report's kind. A Failed Evaluation (any Category failed) keeps its partial score but is never ranked; HR reruns
 * it. A Scanned Resume has no readable text, so it was never evaluated; only a new PDF fixes it. A Must-have Rejection
 * is fully scored but out: never ranked and given no Candidate Feedback. Everything else is ranked.
 * @returns {string} One of KIND.
 */
export function reportKind(r) {
    if (r.status === 'error') return KIND.FAILED;
    if (r.status === 'scanned') return KIND.SCANNED;
    if (r.match_recommendation === 'MUST_HAVE_REJECTED') return KIND.REJECTED;
    return KIND.RANKED;
}

/** Whether the report has scores to show: ranked candidates and Must-have Rejections. */
export function isScored(r) {
    const kind = reportKind(r);
    return kind === KIND.RANKED || kind === KIND.REJECTED;
}

/**
 * The label shown instead of a score for an unscored report (a Failed Evaluation or a Scanned Resume).
 * @returns {string} The label, or '' for a scored report.
 */
export function unscoredLabel(r) {
    switch (reportKind(r)) {
        case KIND.FAILED: return FAILED_EVALUATION_LABEL;
        case KIND.SCANNED: return SCANNED_RESUME_LABEL;
        default: return '';
    }
}

/**
 * A Missing Position resume states no applied-for position. It is still evaluated and ranked as if
 * applying for this job; the flag only tells HR the position was missing.
 */
export function isMissingPosition(r) {
    return r.missing_position === true;
}

/**
 * The must-have Criteria a Must-have Rejection judged NO_EVIDENCE.
 * @returns {Array<{category: string, criterion: string}>} Empty unless the report is a Must-have Rejection.
 */
export function mustHaveMisses(r) {
    return reportKind(r) === KIND.REJECTED ? r.must_have_rejection : [];
}

/**
 * The Category results to show: a Not Applicable Category got no Criterion from HR's requirements and is never judged.
 * @returns {Object} dimension_scores without Not Applicable Categories.
 */
export function shownCategories(r) {
    return Object.fromEntries(Object.entries(r.dimension_scores || {}).filter(([, d]) => !d.not_applicable));
}

/** Display names of the Categories a Failed Evaluation could not score; empty when it did not say. */
export function failedCategoryNames(r) {
    return (r.failed_categories || []).map(k => CATEGORY_NAMES[k] || k);
}

/**
 * The report's one match band: its match_recommendation when scored, 'ERROR' when not. The server sets the
 * recommendation from the overall score, so no page re-derives a band from the score.
 * @returns {string} 'STRONG_MATCH' | 'POTENTIAL_MATCH' | 'LOW_MATCH' | 'REJECT' | 'MUST_HAVE_REJECTED' | 'ERROR'
 */
export function matchBand(r) {
    return isScored(r) ? r.match_recommendation : 'ERROR';
}

/** The text of the report's match pill: its recommendation, or the unscored label. */
export function recommendationLabel(r) {
    return unscoredLabel(r) || RECOMMENDATION_LABELS[r.match_recommendation];
}

/**
 * Band of a 0-100 score, for numbers and bars. Category scores have no recommendation, so they need this;
 * the thresholds match MATCH_THRESHOLDS in src/core/config.py.
 * @returns {'high'|'mid'|'low'|'reject'}
 */
export function scoreBand(score) {
    if (score >= 85) return 'high';
    if (score >= 70) return 'mid';
    if (score >= 55) return 'low';
    return 'reject';
}

/** Colour of a report's overall score: its band when ranked, muted when it is shown but not ranked. */
export function overallScoreTone(r) {
    return reportKind(r) === KIND.RANKED ? scoreBand(r.overall_score) : 'muted';
}

/**
 * The evaluation-order section title and badge for a tier. The Tech resume set's secret file lists only the
 * top 10, in rank order, so in tech mode tier 1 is the Top 10 and everyone else is the rest.
 * @param {number} tier - 1, 2 or 3.
 * @param {boolean} techMode
 * @returns {{title: string, badge: string}}
 */
export function tierLabels(tier, techMode) {
    if (techMode) {
        return tier === 1
            ? { title: 'Top 10 ứng viên', badge: 'Top 10' }
            : { title: 'Ứng viên còn lại', badge: 'Còn lại' };
    }
    const titles = { 1: 'Nhóm CV 1 (Ứng viên ưu tiên)', 2: 'Nhóm CV 2 (Ứng viên thứ cấp)', 3: 'Nhóm CV 3 (Ứng viên ngoài danh sách)' };
    return { title: titles[tier], badge: `Nhóm ${tier}` };
}

/**
 * Rank (1-based) of a tier-1 candidate in the secret evaluation order, or 0 outside tier 1.
 * Works on reports and on scanned-resume list items, which both carry tier and tier_order.
 */
export function tierRank(r) {
    return r.tier === 1 ? r.tier_order + 1 : 0;
}

/**
 * Reports grouped for display, in order: tiers 1, 2 and 3, then Must-have Rejections, then Scanned Resumes, which are
 * never ranked so they leave their tier. Failed Evaluations stay in their tier. Empty sections are dropped.
 * @param {Array<Object>} reports
 * @param {boolean} techMode
 * @returns {Array<{key: (number|string), title: string, badge: string, tone: number, items: Array<Object>}>}
 *          tone (1-3) picks the section's tier colours.
 */
export function groupIntoSections(reports, techMode) {
    const tiers = [1, 2, 3].map(tier => ({ key: tier, ...tierLabels(tier, techMode), tone: tier, items: [] }));
    const rejected = { key: 'rejected', title: REJECTED_SECTION_TITLE, badge: 'Bị loại', tone: 3, items: [] };
    const scanned = { key: 'scanned', title: SCANNED_SECTION_TITLE, badge: 'Bản scan', tone: 3, items: [] };
    reports.forEach(r => {
        switch (reportKind(r)) {
            case KIND.SCANNED: scanned.items.push(r); break;
            case KIND.REJECTED: rejected.items.push(r); break;
            default: tiers[r.tier - 1].items.push(r);
        }
    });
    return [...tiers, rejected, scanned].filter(section => section.items.length > 0);
}

/**
 * The name and email to show once per candidate. Without an extracted name the email is the heading,
 * and is not repeated under it.
 * @returns {{name: string, email: string, contactEmail: string}} contactEmail is the email whether or not it is the heading.
 */
export function candidateIdentity(r) {
    // The server writes 'N/A' when the resume has no email
    const contactEmail = r.candidate_email === 'N/A' ? '' : r.candidate_email;
    const extractedName = (r.candidate_name || '').trim();
    return {
        name: extractedName || contactEmail || r.candidate_identifier || r.resume_name || 'Ứng viên',
        email: extractedName ? contactEmail : '',
        contactEmail
    };
}
