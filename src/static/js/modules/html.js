/**
 * ==============================================================================
 * HTML escaping
 * ==============================================================================
 * Description: The one place markup is escaped. Build markup with the html tagged
 *              template: every ${} value is escaped unless it is SafeHtml (another
 *              html result, or raw() around trusted markup such as a module
 *              constant). Assigning a SafeHtml to innerHTML uses its markup.
 */

/** Markup that is already safe to insert as-is. */
export class SafeHtml {
    constructor(markup) {
        this.markup = markup;
    }

    toString() {
        return this.markup;
    }
}

/**
 * Escapes text for HTML content or a quoted attribute value.
 * @param {*} value - Any value; null and undefined become ''.
 * @returns {string}
 */
export function escapeHtml(value) {
    if (value == null) return '';
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

/**
 * Wraps trusted markup (a module constant, never user or server text) so html inserts it unescaped.
 * @param {string} markup
 * @returns {SafeHtml}
 */
export function raw(markup) {
    return new SafeHtml(String(markup ?? ''));
}

// One ${} value: SafeHtml as-is, arrays item by item, false/null/undefined as nothing, anything else escaped
function renderValue(value) {
    if (value instanceof SafeHtml) return value.markup;
    if (Array.isArray(value)) return value.map(renderValue).join('');
    if (value === false || value == null) return '';
    return escapeHtml(value);
}

/**
 * Tagged template for markup: html`<li>${text}</li>`. Values are escaped unless SafeHtml; arrays are joined
 * item by item; false, null and undefined render nothing, so ${cond && html`...`} works.
 * @returns {SafeHtml}
 */
export function html(strings, ...values) {
    let markup = strings[0];
    values.forEach((value, i) => {
        markup += renderValue(value) + strings[i + 1];
    });
    return new SafeHtml(markup);
}
