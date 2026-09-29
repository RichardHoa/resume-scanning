/**
 * ==============================================================================
 * Shared Waiting Screen (click-blocking loader overlay with time estimates)
 * ==============================================================================
 * Description: Drives the page's #loader-overlay for every operation that makes
 *              HR wait. Single-call waits animate a progress bar and countdown
 *              against the server's expected duration for the operation kind.
 *              Batch waits show "completed/total" and extrapolate the time
 *              remaining from how fast candidates actually finish.
 * Line Count: ~200 lines (Strict Limit: < 500 lines)
 */

import { API } from './api.js';

const TICK_MS = 250;
// The bar never reaches 100% until the operation actually finishes.
const MAX_BAR_FRACTION = 0.95;

/**
 * Formats a positive number of seconds as "Còn khoảng 1 phút 05 giây" / "Còn khoảng 12 giây".
 */
function formatRemaining(seconds) {
    const total = Math.max(1, Math.ceil(seconds));
    const minutes = Math.floor(total / 60);
    const secs = total % 60;
    if (minutes === 0) return `Còn khoảng ${secs} giây`;
    return `Còn khoảng ${minutes} phút ${String(secs).padStart(2, '0')} giây`;
}

export class WaitingScreen {
    constructor() {
        this.overlay = document.getElementById('loader-overlay');
        this.titleEl = document.getElementById('loader-title');
        this.descEl = document.getElementById('loader-desc');
        this.progressEl = document.getElementById('loader-progress');
        this.timeEl = document.getElementById('loader-time');
        this.countEl = document.getElementById('loader-count');
        this.timer = null;
        this.wait = null;
    }

    /**
     * Shows the waiting screen for a single LLM or embedding call.
     * @param {string} kind - Operation kind ('scrutiny', 'decompose', 'save_criteria', 'extract').
     */
    startSingle(kind, title, desc) {
        this.begin({ mode: 'single', kind, title, desc });
    }

    /**
     * Shows the waiting screen for a batch of per-candidate operations.
     * @param {string} kind - Per-item operation kind ('evaluate_candidate').
     * @param {number} total - Number of items in the batch.
     */
    startBatch(kind, title, desc, total) {
        this.begin({ mode: 'batch', kind, title, desc, total });
    }

    /**
     * Reports batch progress; the time remaining is re-extrapolated from it.
     */
    reportProgress(completed, total) {
        if (!this.wait || this.wait.mode !== 'batch') return;
        if (total > 0) this.wait.total = total;
        if (completed > this.wait.completed) {
            this.wait.completed = completed;
            this.wait.lastCompletionElapsed = this.elapsedSeconds();
        }
        this.render();
    }

    /**
     * Closes the waiting screen. Call on both success and failure.
     */
    finish() {
        clearInterval(this.timer);
        this.timer = null;
        this.wait = null;
        if (this.overlay) this.overlay.style.display = 'none';
    }

    /**
     * Runs an async single-call operation behind the waiting screen, closing it however the
     * operation ends. Errors propagate to the caller, after the screen is closed.
     */
    async run(kind, title, desc, operation) {
        this.startSingle(kind, title, desc);
        try {
            return await operation();
        } finally {
            this.finish();
        }
    }

    begin({ mode, kind, title, desc, total = 0 }) {
        clearInterval(this.timer);
        const wait = {
            mode,
            kind,
            total,
            completed: 0,
            lastCompletionElapsed: 0,
            startedAt: performance.now(),
            expectedSeconds: null
        };
        this.wait = wait;

        if (this.titleEl) this.titleEl.textContent = title;
        if (this.descEl) this.descEl.textContent = desc || '';
        if (this.countEl) this.countEl.style.display = mode === 'batch' ? 'block' : 'none';
        if (this.overlay) this.overlay.style.display = 'flex';

        this.render();
        this.timer = setInterval(() => this.render(), TICK_MS);

        API.getExpectedDurations()
            .then(data => {
                const seconds = data && data.expected_seconds ? Number(data.expected_seconds[kind]) : NaN;
                // Ignore a late answer for a wait that has already finished or been replaced.
                if (this.wait === wait && seconds > 0) {
                    wait.expectedSeconds = seconds;
                    this.render();
                }
            })
            .catch(err => console.error('[WaitingScreen] Failed to load expected durations:', err));
    }

    elapsedSeconds() {
        return this.wait ? (performance.now() - this.wait.startedAt) / 1000 : 0;
    }

    render() {
        const wait = this.wait;
        if (!wait) return;
        const elapsed = this.elapsedSeconds();

        let fraction;
        let remaining;
        if (wait.mode === 'single') {
            fraction = wait.expectedSeconds ? elapsed / wait.expectedSeconds : 0;
            remaining = wait.expectedSeconds ? wait.expectedSeconds - elapsed : null;
        } else {
            fraction = wait.total > 0 ? wait.completed / wait.total : 0;
            remaining = this.batchRemainingSeconds(elapsed);
            if (this.countEl) this.countEl.textContent = `${wait.completed}/${wait.total} ứng viên`;
        }

        const clamped = Math.min(Math.max(fraction, 0), MAX_BAR_FRACTION);
        if (this.progressEl) this.progressEl.style.width = `${(clamped * 100).toFixed(1)}%`;

        if (this.timeEl) {
            if (remaining === null) {
                this.timeEl.textContent = 'Đang ước tính thời gian còn lại…';
            } else if (remaining <= 0) {
                this.timeEl.textContent = 'Sắp xong…';
            } else {
                this.timeEl.textContent = formatRemaining(remaining);
            }
        }
    }

    /**
     * Average time per completed candidate x candidates left, counted down since the last
     * completion. Before the first completion, falls back to the expected per-candidate duration.
     * @returns {?number} Seconds remaining, or null when there is nothing to estimate from yet.
     */
    batchRemainingSeconds(elapsed) {
        const wait = this.wait;
        const left = Math.max(wait.total - wait.completed, 0);
        if (wait.completed > 0) {
            const perCandidate = wait.lastCompletionElapsed / wait.completed;
            return perCandidate * left - (elapsed - wait.lastCompletionElapsed);
        }
        if (!wait.expectedSeconds) return null;
        return wait.expectedSeconds * left - elapsed;
    }
}
