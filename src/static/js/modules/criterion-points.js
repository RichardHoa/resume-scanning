/**
 * ==============================================================================
 * Criterion Points labels
 * ==============================================================================
 * Description: How HR reads a Criterion's share of its Category's 100 points, on the
 *              RAG page's live preview and in the candidate modal. The PDF report's
 *              points_label in src/reports/candidate_report.py uses the same wording.
 */

/**
 * Criterion Points as HR reads them: one decimal, without a trailing ".0".
 * @param {number} points
 * @returns {string}
 */
export function formatPoints(points) {
    return String(Number((points || 0).toFixed(1)));
}

/**
 * What a Criterion is worth before any evaluation, e.g. "33.3 điểm", or the bonus a
 * Nice-to-have adds at most, e.g. "+16.7 điểm thưởng".
 * @param {number} maxPoints
 * @param {boolean} isBonus - Whether the Criterion is a Nice-to-have.
 * @returns {string}
 */
export function maxPointsLabel(maxPoints, isBonus) {
    return isBonus ? `+${formatPoints(maxPoints)} điểm thưởng` : `${formatPoints(maxPoints)} điểm`;
}

/**
 * What a candidate earned on a Criterion, e.g. "25 / 50", or the bonus a Nice-to-have
 * added, "+25", which never costs points when missing: "+0 · không trừ điểm".
 * @param {number} earnedPoints
 * @param {number} maxPoints
 * @param {boolean} isBonus - Whether the Criterion is a Nice-to-have.
 * @returns {string}
 */
export function earnedPointsLabel(earnedPoints, maxPoints, isBonus) {
    if (!isBonus) return `${formatPoints(earnedPoints)} / ${formatPoints(maxPoints)}`;
    return earnedPoints > 0 ? `+${formatPoints(earnedPoints)}` : '+0 · không trừ điểm';
}
