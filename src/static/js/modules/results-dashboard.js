/**
 * ==============================================================================
 * Results Dashboard (Evaluator Step 4)
 * ==============================================================================
 * Description: A batch's results: KPI totals, then one leaderboard table per
 *              result section (tiers, Must-have Rejections, Scanned Resumes).
 *              "Xem hồ sơ" opens the candidate's full report in the shared view.
 */

import { CandidateReportView } from './candidate-report-view.js';
import { byId } from './dom.js';
import { html } from './html.js';
import {
    KIND, reportKind, isScored, isMissingPosition, matchBand, recommendationLabel, groupIntoSections, candidateIdentity,
    MISSING_POSITION_LABEL, MISSING_POSITION_MESSAGE
} from './report.js';

export class ResultsDashboard {
    constructor() {
        this.reportView = new CandidateReportView();
        this.container = byId('tier-blocks-container');
        this.totalBadge = byId('eval-total-badge');
        this.kpiTotalVal = byId('kpi-total-val');
        this.kpiStrongVal = byId('kpi-strong-val');
        this.kpiPotentialVal = byId('kpi-potential-val');
        this.kpiAvgScoreVal = byId('kpi-avg-score-val');
    }

    /**
     * Renders a batch's KPI totals and leaderboard tables.
     * @param {Array<Object>} results - The batch's evaluation results.
     * @param {boolean} techMode - Whether the Tech resume set's evaluation order is in use.
     */
    render(results, techMode) {
        // Must-have Rejections and unscored results count as neither a match nor in the average
        const ranked = results.filter(r => reportKind(r) === KIND.RANKED);
        const avgScore = ranked.length > 0
            ? (ranked.reduce((acc, r) => acc + r.overall_score, 0) / ranked.length).toFixed(1)
            : '0.0';
        this.kpiTotalVal.textContent = results.length;
        this.kpiStrongVal.textContent = ranked.filter(r => matchBand(r) === 'STRONG_MATCH').length;
        this.kpiPotentialVal.textContent = ranked.filter(r => matchBand(r) === 'POTENTIAL_MATCH').length;
        this.kpiAvgScoreVal.textContent = avgScore;
        this.totalBadge.textContent = `Đã đánh giá ${results.length}`;

        this.container.innerHTML = '';
        groupIntoSections(results, techMode).forEach(section => {
            const block = document.createElement('div');
            block.className = `tier-block-card tier-${section.tone}-block`;
            block.innerHTML = html`
                <div class="panel-header-split leaderboard-header">
                    <div class="leaderboard-title-group">
                        <h3 class="leaderboard-title">${section.title}</h3>
                        <span class="tier-badge tier-badge-${section.tone}">${section.badge}</span>
                    </div>
                    <span class="text-muted leaderboard-count">${section.items.length} ứng viên</span>
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

            const tbody = block.querySelector('.tier-tbody');
            // Only ranked candidates are numbered; Failed Evaluations in the same tier are never ranked
            let rank = 0;
            section.items.forEach(res => {
                const isRanked = reportKind(res) === KIND.RANKED;
                if (isRanked) rank++;
                tbody.appendChild(this.buildRow(res, isRanked ? rank : 0));
            });
            this.container.appendChild(block);
        });
    }

    /**
     * One leaderboard row.
     * @param {Object} res - Evaluation result.
     * @param {number} rank - Its rank in the section, or 0 when it is not ranked.
     * @returns {HTMLTableRowElement}
     */
    buildRow(res, rank) {
        const tr = document.createElement('tr');
        const scored = isScored(res);
        const { contactEmail } = candidateIdentity(res);
        tr.innerHTML = html`
            <td>${rank > 0 ? html`<span class="rank-badge rank-${rank}">${rank}</span>` : '—'}</td>
            <td>
                <strong class="leaderboard-name">${res.resume_name}</strong><br>
                <span class="leaderboard-email">✉ ${contactEmail || 'Không có'}</span>
                ${isMissingPosition(res) && html`<br><span class="badge-warning" title="${MISSING_POSITION_MESSAGE}">⚠️ ${MISSING_POSITION_LABEL}</span>`}
            </td>
            <td>${scored
                ? html`<strong class="leaderboard-score${rank > 0 ? '' : ' leaderboard-score--muted'}">${res.overall_score}</strong><span class="leaderboard-score-max">/100</span>`
                : html`<strong class="leaderboard-score leaderboard-score--muted">—</strong>`}</td>
            <td><span class="match-pill band-${matchBand(res)}">${recommendationLabel(res)}</span></td>
            <td class="leaderboard-tally">${scored && html`
                <span class="leaderboard-tally-strengths">✓ ${res.summary.total_strengths}</span> •
                <span class="leaderboard-tally-gaps">✗ ${res.summary.total_gaps}</span>
            `}</td>
            <td>
                <button class="btn btn-sm btn-secondary btn-inspect" type="button">Xem hồ sơ</button>
            </td>
        `;
        const button = tr.querySelector('.btn-inspect');
        button.addEventListener('click', () => this.reportView.open(res, button));
        return tr;
    }
}
