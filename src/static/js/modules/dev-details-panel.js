/**
 * ==============================================================================
 * Developer Details Panel
 * ==============================================================================
 * Description: The contents of the candidate report's collapsed developer panel:
 *              everything a run folder holds for one evaluated resume (extraction
 *              markdown and JSON, evaluation JSON, prompt logs, token usage), in
 *              tabs, each block with a copy button and a link to its raw file.
 */

import { API } from './api.js';
import { CATEGORY_NAMES } from './criteria-editor.js';
import { html, raw } from './html.js';

// Pipeline steps the developer panel groups prompt logs by (keys match dev_details.prompt_logs[].step)
const DEV_STEP_NAMES = {
    extraction: 'Trích xuất',
    evaluation: 'Đánh giá theo mục',
    review_panel: 'Hội đồng đánh giá',
    other: 'Khác'
};

/**
 * The developer panel's tabs: extraction markdown, extraction JSON, evaluation JSON, prompt logs and token usage.
 * @param {Object} dev - The dev_details response.
 * @param {string} filename - Evaluation result file name, for the raw-file links.
 * @returns {SafeHtml} The tab bar and panels.
 */
export function renderDevDetailsContent(dev, filename) {
    const urls = API.devFileUrls(filename);
    const json = (value) => value == null ? null : (typeof value === 'string' ? value : JSON.stringify(value, null, 2));
    const tokenLines = (dev.token_usage || []).map(r => JSON.stringify(r)).join('\n');
    const tabs = [
        { key: 'markdown', label: 'Markdown', body: renderDevPre(dev.extraction_markdown, 'Không có markdown trích xuất.', urls.resumeMarkdown) },
        { key: 'extraction', label: 'JSON trích xuất', body: renderDevPre(json(dev.extraction_json), 'Không có JSON trích xuất.', urls.resumeJson) },
        { key: 'evaluation', label: 'JSON đánh giá', body: renderDevPre(json(dev.evaluation_json), 'Không có JSON đánh giá.', urls.evalJson) },
        { key: 'prompts', label: 'Prompt', body: renderDevPromptLogs(dev.prompt_logs || []) },
        { key: 'tokens', label: 'Token', body: renderDevPre(tokenLines || null, 'Không có bản ghi token.') }
    ];
    return html`
        <div class="modal-dev-meta">Thư mục chạy: <code>${dev.run_folder}</code> • Hồ sơ: <code>${dev.resume_name}</code></div>
        <div class="modal-dev-tabs" role="tablist">${tabs.map((t, i) => html`
            <button class="modal-dev-tab" type="button" role="tab" data-dev-tab="${t.key}" aria-selected="${String(i === 0)}">${t.label}</button>
        `)}</div>
        ${tabs.map((t, i) => html`
            <div class="modal-dev-panel" role="tabpanel" data-dev-panel="${t.key}" ${i > 0 && raw('hidden')}>${t.body}</div>
        `)}
    `;
}

/**
 * A block of raw text with a copy button, and a link to open the raw file when it has one.
 * @param {?string} text - The text, or null when there is none.
 * @param {string} emptyMessage - Shown instead when there is no text.
 * @param {string} [rawUrl] - URL of the raw file.
 * @returns {SafeHtml} The block.
 */
function renderDevPre(text, emptyMessage, rawUrl = '') {
    if (text == null || text === '') return html`<div class="modal-dev-empty">${emptyMessage}</div>`;
    return html`
        <div class="modal-dev-block">
            <div class="modal-dev-block-actions">
                ${rawUrl && html`<a class="modal-dev-link" href="${rawUrl}" target="_blank" rel="noopener">Mở tệp ↗</a>`}
                <button class="modal-dev-link" type="button" data-dev-copy>Sao chép</button>
            </div>
            <pre class="modal-dev-pre">${text}</pre>
        </div>
    `;
}

/**
 * The resume's prompt logs grouped by pipeline step, then category, each log file collapsed.
 * @param {Array<Object>} groups - dev_details.prompt_logs.
 * @returns {SafeHtml} The prompt logs tab.
 */
function renderDevPromptLogs(groups) {
    if (!groups.length) return html`<div class="modal-dev-empty">Không có prompt nào được ghi lại.</div>`;
    return html`${groups.map(group => html`
        <section class="modal-dev-step">
            <h4 class="modal-dev-step-title">${DEV_STEP_NAMES[group.step] || group.step}</h4>
            ${group.categories.map(c => html`
                <div class="modal-dev-category${c.broken && ' is-broken'}">
                    <div class="modal-dev-category-title">${CATEGORY_NAMES[c.category] || c.category}${c.broken && ' — JSON lỗi'} <span class="modal-dev-count">(${c.files.length})</span></div>
                    ${c.files.map(f => html`
                        <details class="modal-dev-log">
                            <summary>${f.name}</summary>
                            ${renderDevPre(f.content, 'Tệp trống.')}
                        </details>
                    `)}
                </div>
            `)}
        </section>
    `)}`;
}

/**
 * Wires the developer panel's tab switching and copy buttons.
 * @param {HTMLElement} body - The panel body holding the rendered content.
 */
export function bindDevDetailsContent(body) {
    body.querySelectorAll('[data-dev-tab]').forEach(tab => {
        tab.addEventListener('click', () => {
            body.querySelectorAll('[data-dev-tab]').forEach(t => t.setAttribute('aria-selected', String(t === tab)));
            body.querySelectorAll('[data-dev-panel]').forEach(p => { p.hidden = p.dataset.devPanel !== tab.dataset.devTab; });
        });
    });
    body.querySelectorAll('[data-dev-copy]').forEach(btn => {
        btn.addEventListener('click', async () => {
            const pre = btn.closest('.modal-dev-block').querySelector('.modal-dev-pre');
            try {
                await navigator.clipboard.writeText(pre.textContent);
                btn.textContent = 'Đã chép';
            } catch {
                btn.textContent = 'Không chép được';
            }
            setTimeout(() => { btn.textContent = 'Sao chép'; }, 1500);
        });
    });
}
