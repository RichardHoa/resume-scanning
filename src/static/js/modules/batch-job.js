/**
 * ==============================================================================
 * Batch jobs, from the page's side
 * ==============================================================================
 * Description: Remembers the running Batch in the browser so a reload reconnects
 *              to it, remembers the Batch just extracted for the evaluator's
 *              "Chọn lô vừa trích xuất", and follows a Batch on the waiting screen
 *              until it ends. Browser storage can be missing or throw; a reload
 *              then only loses the reconnect.
 */

import { API } from './api.js';

// How often a Batch job's status is polled while the waiting screen shows.
const POLL_MS = 1500;
const RUNNING_BATCH_KEY = 'resume-scanning.running-batch';
const LAST_EXTRACTED_KEY = 'resume-scanning.last-extracted-batch';
const SELECT_LAST_EXTRACTED_KEY = 'resume-scanning.select-last-extracted';

/** The page that follows each kind of Batch. */
export const BATCH_PAGES = { extract: '/extractor', evaluate: '/evaluator' };

function readStored(key) {
    try {
        const raw = localStorage.getItem(key);
        return raw ? JSON.parse(raw) : null;
    } catch {
        return null;
    }
}

function writeStored(key, value) {
    try {
        if (value === null) localStorage.removeItem(key);
        else localStorage.setItem(key, JSON.stringify(value));
    } catch {
        // Without storage the page still works; only a reload loses track of the Batch
    }
}

export const BatchStore = {
    /** Remembers the Batch this browser is following, for a reload to reconnect to. */
    rememberRunning(jobId, kind) {
        writeStored(RUNNING_BATCH_KEY, { jobId, kind });
    },

    /** @returns {?{jobId: string, kind: string}} The Batch this browser was following, if any. */
    running() {
        const stored = readStored(RUNNING_BATCH_KEY);
        return stored && typeof stored.jobId === 'string' ? stored : null;
    },

    forgetRunning() {
        writeStored(RUNNING_BATCH_KEY, null);
    },

    /** Remembers the resume JSON file names of the Batch just extracted. */
    rememberLastExtracted(filenames) {
        writeStored(LAST_EXTRACTED_KEY, filenames);
    },

    /** @returns {Array<string>} The resume JSON file names of the Batch just extracted, or none. */
    lastExtracted() {
        const stored = readStored(LAST_EXTRACTED_KEY);
        return Array.isArray(stored) ? stored : [];
    },

    /** Asks the evaluator to select the Batch just extracted once its resume list loads. */
    requestSelectLastExtracted() {
        writeStored(SELECT_LAST_EXTRACTED_KEY, true);
    },

    /** @returns {boolean} Whether the selection was asked for; asking is used up by reading it. */
    takeSelectLastExtracted() {
        const asked = readStored(SELECT_LAST_EXTRACTED_KEY) === true;
        writeStored(SELECT_LAST_EXTRACTED_KEY, null);
        return asked;
    }
};

/**
 * The running Batch a refused start names, when it was refused because one runs.
 * @param {Error & {status?: number, data?: Object}} err
 * @returns {?{jobId: string, kind: string}}
 */
export function runningBatchFromRefusal(err) {
    if (err.status !== 409 || !err.data || !err.data.running_job_id) return null;
    return { jobId: err.data.running_job_id, kind: err.data.running_kind };
}

/**
 * Offers to open the running Batch that refused a new one, on the page that follows its kind.
 * @param {{jobId: string, kind: string}} running
 * @param {function({jobId: string, kind: string}): void} followHere - Follows a Batch of this page's kind.
 * @param {string} hereKind - The kind of Batch this page follows.
 */
export function offerRunningBatch(running, followHere, hereKind) {
    const kindLabel = running.kind === 'extract' ? 'trích xuất' : 'đánh giá';
    if (!confirm(`Đang có một lô khác chạy (lô ${kindLabel}). Mỗi lần chỉ chạy được một lô.\n\nMở lô đang chạy?`)) return;
    BatchStore.rememberRunning(running.jobId, running.kind);
    if (running.kind === hereKind) followHere(running);
    else window.location.href = BATCH_PAGES[running.kind];
}

/**
 * Polls a Batch job, reporting each status to the waiting screen, until it is no longer running.
 * @param {string} jobId
 * @param {import('./waiting-screen.js').WaitingScreen} waitingScreen
 * @returns {Promise<Object>} The job's final status (done, cancelled or failed).
 */
export async function followBatchJob(jobId, waitingScreen) {
    for (;;) {
        const job = await API.getBatchJob(jobId);
        waitingScreen.reportBatch(job);
        if (job.state !== 'running') return job;
        await new Promise(resolve => setTimeout(resolve, POLL_MS));
    }
}
