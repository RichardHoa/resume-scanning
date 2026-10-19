/**
 * ==============================================================================
 * DOM helpers
 * ==============================================================================
 * Description: Element lookup that fails loudly, and client-side file download.
 */

/**
 * The element with this id. Every controller runs only on its own page, whose markup has its elements,
 * so a missing one is a mistyped id: it throws instead of being silently skipped.
 * @param {string} id
 * @returns {HTMLElement}
 */
export function byId(id) {
    const el = document.getElementById(id);
    if (!el) throw new Error('Missing #' + id);
    return el;
}

/**
 * Saves a Blob through the browser's download prompt.
 * @param {Blob} blob
 * @param {string} filename - Suggested file name.
 */
export function downloadBlob(blob, filename) {
    const url = URL.createObjectURL(blob);
    const anchor = document.createElement('a');
    anchor.href = url;
    anchor.download = filename;
    document.body.appendChild(anchor);
    anchor.click();
    anchor.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
}
