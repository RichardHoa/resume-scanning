/**
 * ==============================================================================
 * Shared Waiting Screen (click-blocking loader overlay with time estimates)
 * ==============================================================================
 * Description: Drives the page's #loader-overlay for every operation that makes
 *              HR wait. Single-call waits animate a progress bar and countdown
 *              against the server's expected duration for the operation kind.
 *              Batch waits list every item with its state, count the items by
 *              state, and estimate the time remaining from the Batch's throughput,
 *              since its items run in parallel.
 */

import { API } from './api.js';
import { byId } from './dom.js';
import { html } from './html.js';

const TICK_MS = 250;
// The bar never reaches 100% until the operation actually finishes.
const MAX_BAR_FRACTION = 0.95;

// The duration kind of a whole Batch's seconds per item, for each per-item kind
const BATCH_ITEM_KINDS = { extract: 'extract_batch_item', evaluate_candidate: 'evaluate_batch_item' };

const ITEM_STATE_LABELS = {
    waiting: 'Đang chờ',
    running: 'Đang xử lý',
    done: 'Xong',
    failed: 'Lỗi',
    cancelled: 'Đã hủy'
};

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
        this.overlay = byId('loader-overlay');
        this.titleEl = byId('loader-title');
        this.descEl = byId('loader-desc');
        this.progressEl = byId('loader-progress');
        this.timeEl = byId('loader-time');
        this.countEl = byId('loader-count');
        this.itemsEl = byId('loader-items');
        this.btnCancel = byId('loader-cancel');
        this.timer = null;
        this.wait = null;

        this.btnCancel.addEventListener('click', () => this.cancel());
    }

    /**
     * Shows the waiting screen for a single LLM or embedding call.
     * @param {string} kind - Operation kind ('scrutiny', 'decompose', 'save_criteria').
     */
    startSingle(kind, title, desc) {
        this.begin({ mode: 'single', kind, title, desc });
    }

    /**
     * Shows the waiting screen for a Batch, before its first status arrives.
     * @param {string} kind - Per-item operation kind ('extract', 'evaluate_candidate').
     * @param {number} total - Number of items in the Batch, as far as the page knows.
     * @param {function(): Promise<void>} onCancel - Stops the Batch ("Dừng lô").
     */
    startBatch(kind, title, desc, total, onCancel) {
        this.begin({ mode: 'batch', kind, title, desc, total, onCancel });
    }

    /**
     * Reports a Batch job's status: its items, their counts and its elapsed time on the server, so a page that
     * reconnected after a reload estimates from the Batch's real start.
     * @param {Object} job - A status from API.getBatchJob.
     */
    reportBatch(job) {
        const wait = this.wait;
        if (!wait || wait.mode !== 'batch') return;
        wait.startedAt = performance.now() - job.elapsed_seconds * 1000;
        if (job.total > 0) wait.total = job.total;
        wait.counts = job.counts;
        const finished = job.counts.done + job.counts.failed;
        if (finished > wait.finished) {
            wait.finished = finished;
            wait.lastCompletionElapsed = job.elapsed_seconds;
        }
        this.renderItems(job.items);
        this.render();
    }

    /**
     * Closes the waiting screen. Call on both success and failure.
     */
    finish() {
        clearInterval(this.timer);
        this.timer = null;
        this.wait = null;
        this.overlay.hidden = true;
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

    begin({ mode, kind, title, desc, total = 0, onCancel = null }) {
        clearInterval(this.timer);
        const wait = {
            mode,
            kind,
            total,
            counts: null,
            finished: 0,
            lastCompletionElapsed: 0,
            startedAt: performance.now(),
            expectedSeconds: null,
            expectedBatchItemSeconds: null,
            onCancel
        };
        this.wait = wait;

        this.titleEl.textContent = title;
        this.descEl.textContent = desc || '';
        this.countEl.hidden = mode !== 'batch';
        this.itemsEl.hidden = true;
        this.itemsEl.innerHTML = '';
        this.btnCancel.hidden = !onCancel;
        this.btnCancel.disabled = false;
        this.btnCancel.textContent = 'Dừng lô';
        this.overlay.hidden = false;

        this.render();
        this.timer = setInterval(() => this.render(), TICK_MS);

        API.getExpectedDurations()
            .then(data => {
                const expected = (data && data.expected_seconds) || {};
                // Ignore a late answer for a wait that has already finished or been replaced.
                if (this.wait !== wait) return;
                if (Number(expected[kind]) > 0) wait.expectedSeconds = Number(expected[kind]);
                const batchKind = BATCH_ITEM_KINDS[kind];
                if (batchKind && Number(expected[batchKind]) > 0) wait.expectedBatchItemSeconds = Number(expected[batchKind]);
                this.render();
            })
            .catch(err => console.error('[WaitingScreen] Failed to load expected durations:', err));
    }

    /**
     * "Dừng lô": items not started are cancelled, running ones finish; the wait goes on until the Batch ends.
     */
    async cancel() {
        const wait = this.wait;
        if (!wait || !wait.onCancel) return;
        this.btnCancel.disabled = true;
        this.btnCancel.textContent = 'Đang dừng… (chờ các mục đang xử lý xong)';
        try {
            await wait.onCancel();
        } catch (err) {
            if (this.wait === wait) {
                this.btnCancel.disabled = false;
                this.btnCancel.textContent = 'Dừng lô';
            }
            alert('Không dừng được lô: ' + err.message);
        }
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
            fraction = wait.total > 0 ? wait.finished / wait.total : 0;
            remaining = this.batchRemainingSeconds(elapsed);
            this.countEl.textContent = this.countText();
        }

        const clamped = Math.min(Math.max(fraction, 0), MAX_BAR_FRACTION);
        this.progressEl.style.width = `${(clamped * 100).toFixed(1)}%`;

        if (remaining === null) {
            this.timeEl.textContent = 'Đang ước tính thời gian còn lại…';
        } else if (remaining <= 0) {
            this.timeEl.textContent = 'Sắp xong…';
        } else {
            this.timeEl.textContent = formatRemaining(remaining);
        }
    }

    /** "Xong 3 · Đang xử lý 4 · Lỗi 1 · Đang chờ 32", failures apart, so "N/N" never hides one. */
    countText() {
        const counts = this.wait.counts;
        if (!counts) return `0/${this.wait.total}`;
        const parts = ['done', 'running', 'failed', 'waiting']
            .map(state => `${ITEM_STATE_LABELS[state]} ${counts[state]}`);
        if (counts.cancelled > 0) parts.push(`${ITEM_STATE_LABELS.cancelled} ${counts.cancelled}`);
        return parts.join(' · ');
    }

    /**
     * Before any item finishes: the longer of one item's duration and the Batch's recorded seconds per item x items.
     * After that: the items left at the throughput measured at the last completion, counted down since it.
     * @returns {?number} Seconds remaining, or null when there is nothing to estimate from yet.
     */
    batchRemainingSeconds(elapsed) {
        const wait = this.wait;
        const counts = wait.counts;
        const left = counts ? counts.waiting + counts.running : wait.total;
        if (wait.finished > 0 && wait.lastCompletionElapsed > 0) {
            const throughput = wait.finished / wait.lastCompletionElapsed;
            return left / throughput - (elapsed - wait.lastCompletionElapsed);
        }
        if (!wait.expectedSeconds) return null;
        const batchSeconds = wait.expectedBatchItemSeconds ? wait.expectedBatchItemSeconds * wait.total : 0;
        return Math.max(wait.expectedSeconds, batchSeconds) - elapsed;
    }

    /** One line per item, with its state. */
    renderItems(items) {
        this.itemsEl.hidden = items.length === 0;
        this.itemsEl.innerHTML = html`${items.map(item => html`
            <li class="loader-item loader-item--${item.state}">
                <span class="loader-item-name">${item.name}</span>
                <span class="loader-item-state">${ITEM_STATE_LABELS[item.state] || item.state}</span>
            </li>
        `)}`;
    }
}
