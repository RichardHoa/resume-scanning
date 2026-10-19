/**
 * ==============================================================================
 * Shared Criteria Editor (Verify step & RAG Workbench)
 * ==============================================================================
 * Description: Renders a warning that a missing Must-have rejects the candidate, a
 *              collapsible guide to the Importance levels (always open on render),
 *              then a matrix: one row per Category, one column per
 *              Importance (Bắt buộc / Tiêu chuẩn / Ưu tiên), and a last row of HR
 *              Check Items (requirements no resume would show, never scored) that
 *              spans every column. Each item is a chip whose text is edited in place
 *              (Enter never inserts a newline, so items stay single logical lines).
 *              Dragging a chip to another cell sets its Category and Importance in one
 *              move; its "⋯" menu does the same (and deletes) for keyboard and touch.
 *              Every cell has its own add box. A chip dropped in the HR Check Items
 *              loses its Importance, so one moved back out is Standard. When the editor is
 *              narrower than 900px each row stacks its cells, each labelled with its Importance.
 *              Each Criterion shows its Criterion Points out of its Category's 100, updated
 *              as HR moves it. A Category whose Criteria are all Nice-to-have, or that has
 *              one text twice, is flagged and blocks saving (callers check confirmSavable()).
 *              Callers pass in the RAG summary's categories ({category_key:
 *              [{text, importance}]}), its HR Check Items (strings) and its
 *              Importance levels (src/core/config.py is their only source), and
 *              read them back with getCategories() ({category_key: [{text,
 *              importance}]}) and getHrCheckItems() (strings).
 */

import { maxPointsLabel } from './criterion-points.js';
import { html, raw } from './html.js';

// Display names of the five Categories, in row order. Also used to label evaluation dimensions.
export const CATEGORY_NAMES = {
    seniority_title: 'Vị trí & Số năm kinh nghiệm',
    technical_skills: 'Kỹ năng, Công cụ & Chuyên môn',
    work_experience: 'Kinh nghiệm làm việc, Dự án & Trách nhiệm',
    education_certifications: 'Bằng cấp & Chứng chỉ',
    hidden_culture: 'Yêu cầu ẩn & Văn hóa'
};

// Key of the HR Check Items list, as the server stores and returns it
export const HR_CHECK_ITEMS_KEY = 'hr_check_items';
export const HR_CHECK_ITEMS_NAME = 'Cần HR kiểm tra thủ công';

// The Importance keys results are tagged by (MUST_HAVE and NICE_TO_HAVE in src/core/config.py).
// Every other level detail comes from the server with the RAG summary
export const MUST_HAVE = 'must_have';
export const NICE_TO_HAVE = 'nice_to_have';

// Shown on a Category the server refuses to save (hr_rag_problem in src/providers/rag_engine.py)
const BONUS_ONLY_MESSAGE = 'Nhóm này cần ít nhất một tiêu chí Bắt buộc hoặc Tiêu chuẩn';
const DUPLICATE_MESSAGE = 'Nhóm này có hai tiêu chí trùng nội dung';

// Every list the editor holds, in row order: the five Categories, then the HR Check Items
const LIST_NAMES = { ...CATEGORY_NAMES, [HR_CHECK_ITEMS_KEY]: HR_CHECK_ITEMS_NAME };

// What each Importance level means to HR, shown in the guide (trusted markup). Keyed like src/core/config.py;
// a level missing here is listed with its label and weight only
const IMPORTANCE_HELP = {
    must_have: 'Ứng viên bắt buộc phải có. Nếu CV không cho thấy bằng chứng cho dù chỉ <strong>một</strong> tiêu chí Bắt buộc, ứng viên <strong>bị loại ngay</strong>. CV đáp ứng một phần thì không bị loại.',
    standard: 'Yêu cầu thông thường của vị trí. Đây là mức mặc định khi bạn không chọn mức nào khác.',
    nice_to_have: 'Điểm cộng. Ứng viên có thì được cộng thêm điểm (mỗi chiều tối đa 100 điểm); không có thì <strong>không bị trừ điểm</strong>.'
};

// Always shown above the guide: a Must-have decides who is rejected, not just the score
const MUST_HAVE_WARNING = '<strong>Cân nhắc kỹ trước khi đánh dấu “Bắt buộc”.</strong> Ứng viên thiếu bằng chứng cho <strong>bất kỳ một</strong> tiêu chí Bắt buộc nào sẽ <strong>bị loại ngay</strong>, dù các tiêu chí khác tốt đến đâu. Chỉ chọn mức này cho yêu cầu thật sự không thể thiếu; nếu không chắc, hãy chọn Tiêu chuẩn.';

const HR_CHECK_HELP = 'Yêu cầu mà CV thông thường không thể hiện (vd: sẵn sàng tăng ca, thời gian nhận việc, mức lương mong muốn). Không chấm điểm ứng viên theo các mục này; HR tự kiểm tra khi phỏng vấn.';

// Value of the "⋯" menu option that deletes the item
const DELETE_ACTION = '__delete__';

export class CriteriaEditor {
    /**
     * @param {HTMLElement} container - Element the guide and matrix are rendered into.
     */
    constructor(container) {
        this.container = container;
        this.categories = CriteriaEditor.emptyCategories();
        this.importanceLevels = {};
        this.defaultImportance = '';
        this.matrixEl = null;
        this.dragged = null;
        window.addEventListener('resize', () => this.resizeAll());
    }

    static emptyCategories() {
        const cats = {};
        Object.keys(LIST_NAMES).forEach(k => { cats[k] = []; });
        return cats;
    }

    /**
     * Replaces the edited set with the RAG summary's. Every list is held as [{text, importance}];
     * the HR Check Items' importance is unused.
     * @param {Object} rawCats - {category_key: [{text, importance}]} for the five Categories.
     * @param {Array<string>} hrCheckItems - The HR Check Items.
     * @param {Object} importanceLevels - {key: {label, weight}} from the RAG summary, in column order.
     * @param {string} defaultImportance - The level of a Criterion that has none (the RAG summary's).
     */
    setCategories(rawCats, hrCheckItems, importanceLevels, defaultImportance) {
        this.importanceLevels = importanceLevels;
        this.defaultImportance = defaultImportance;
        this.categories = CriteriaEditor.emptyCategories();
        Object.keys(CATEGORY_NAMES).forEach(k => {
            this.categories[k] = rawCats[k].map(it => ({ text: it.text, importance: this.normalizeImportance(it.importance) }));
        });
        this.categories[HR_CHECK_ITEMS_KEY] = hrCheckItems.map(text => ({ text, importance: this.defaultImportance }));
        this.render();
    }

    /** A known Importance key; anything missing or unknown reads as the default level. */
    normalizeImportance(value) {
        return Object.hasOwn(this.importanceLevels, value) ? value : this.defaultImportance;
    }

    /**
     * Returns a copy of the five Categories as {category_key: [{text, importance}]}.
     */
    getCategories() {
        const cats = {};
        Object.keys(CATEGORY_NAMES).forEach(k => {
            cats[k] = this.categories[k].map(({ text, importance }) => ({ text, importance }));
        });
        return cats;
    }

    /** Returns a copy of the HR Check Items as plain strings: they have no Importance. */
    getHrCheckItems() {
        return this.categories[HR_CHECK_ITEMS_KEY].map(item => item.text);
    }

    /** Number of Criteria in the five Categories; HR Check Items are not Criteria. */
    totalCount() {
        return Object.values(this.getCategories()).reduce((acc, items) => acc + items.length, 0);
    }

    /**
     * The weight a Category's Must-have and Standard Criteria share its 100 points by (0 when all
     * are Nice-to-have). Mirrors base_weight in src/core/importance.py.
     */
    baseWeight(catKey) {
        return this.savedItems(catKey)
            .filter(item => item.importance !== NICE_TO_HAVE)
            .reduce((acc, item) => acc + (this.importanceLevels[item.importance]?.weight || 0), 0);
    }

    /**
     * A Criterion's points out of its Category's 100, e.g. "33.3 điểm", or the bonus a
     * Nice-to-have adds, e.g. "+16.7 điểm thưởng". Mirrors criterion_max_points in
     * src/core/importance.py; the evaluation report's stored points are the source of truth.
     */
    pointsLabel(catKey, item) {
        const base = this.baseWeight(catKey);
        if (!base || !item.text.trim()) return '';
        return maxPointsLabel((this.importanceLevels[item.importance]?.weight || 0) / base * 100, item.importance === NICE_TO_HAVE);
    }

    /** A Category's items the server would store: blank ones are dropped on save. */
    savedItems(catKey) {
        return this.categories[catKey].filter(item => item.text.trim());
    }

    /** Why a Category can't be saved (all Nice-to-have, or one text twice), or '' when it can. */
    categoryProblem(catKey) {
        const items = this.savedItems(catKey);
        if (items.length && !this.baseWeight(catKey)) return BONUS_ONLY_MESSAGE;
        if (new Set(items.map(item => item.text.trim())).size < items.length) return DUPLICATE_MESSAGE;
        return '';
    }

    /**
     * Whether the set can be saved; when it can't, tells HR which Categories to fix.
     * Callers check this before saving. The server refuses the same sets.
     * @returns {boolean}
     */
    confirmSavable() {
        const problems = Object.keys(CATEGORY_NAMES)
            .map(k => [CATEGORY_NAMES[k], this.categoryProblem(k)])
            .filter(([, problem]) => problem)
            .map(([name, problem]) => `${name}: ${problem}.`);
        if (problems.length) alert(problems.join('\n'));
        return !problems.length;
    }

    /** An Importance level as HR reads it, e.g. "Bắt buộc ×2". */
    levelLabel(key) {
        const level = this.importanceLevels[key];
        return `${level.label} ×${level.weight}`;
    }

    /** Renders the Must-have warning, the guide (open again) and the matrix. */
    render() {
        if (!this.container) return;
        this.container.innerHTML = '';
        const warning = document.createElement('p');
        warning.className = 'criteria-must-have-warning';
        warning.innerHTML = raw(MUST_HAVE_WARNING);
        this.container.appendChild(warning);
        this.container.appendChild(this.buildGuide());
        this.matrixEl = document.createElement('div');
        this.matrixEl.className = 'criteria-matrix';
        this.matrixEl.style.setProperty('--criteria-matrix-cols', Object.keys(this.importanceLevels).length || 1);
        this.container.appendChild(this.matrixEl);
        this.renderMatrix();
    }

    /** The collapsible box explaining each Importance level and the HR Check Items, in Vietnamese. */
    buildGuide() {
        const guide = document.createElement('details');
        guide.className = 'criteria-guide';
        guide.open = true;
        const levels = Object.entries(this.importanceLevels);
        const items = levels.map(([key]) => html`
            <li>
                <span class="criteria-level-tag" data-importance="${key}">${this.levelLabel(key)}</span>
                <span>${raw(IMPORTANCE_HELP[key] || '')}</span>
            </li>`);
        const example = Object.hasOwn(this.importanceLevels, NICE_TO_HAVE)
            && html`<p class="criteria-guide-example"><strong>Cách tính điểm:</strong> mỗi chiều có 100 điểm, chia cho các tiêu chí Bắt buộc và Tiêu chuẩn theo trọng số; tiêu chí ${this.importanceLevels[NICE_TO_HAVE].label} chỉ cộng thêm điểm, tối đa 100 điểm cho chiều đó. Ví dụ: 2 tiêu chí Tiêu chuẩn và 1 tiêu chí ${this.importanceLevels[NICE_TO_HAVE].label} — mỗi tiêu chí Tiêu chuẩn 50 điểm, tiêu chí ${this.importanceLevels[NICE_TO_HAVE].label} +25 điểm thưởng. Số điểm của từng tiêu chí hiện ngay trên tiêu chí. Mỗi chiều cần ít nhất một tiêu chí Bắt buộc hoặc Tiêu chuẩn.</p>`;
        guide.innerHTML = html`
            <summary>Ý nghĩa các mức độ quan trọng</summary>
            <div class="criteria-guide-body">
                <ul>
                    ${items}
                    <li>
                        <span class="criteria-level-tag criteria-level-tag-check">${HR_CHECK_ITEMS_NAME}</span>
                        <span>${HR_CHECK_HELP}</span>
                    </li>
                </ul>
                ${example}
                <p class="criteria-guide-hint">Kéo thả một tiêu chí sang ô khác để đổi chiều và mức độ quan trọng cùng lúc, hoặc dùng nút ⋯ trên tiêu chí. Nhấn vào nội dung để sửa.</p>
            </div>
        `;
        return guide;
    }

    /** Rebuilds the matrix from this.categories; the guide is left as HR set it. */
    renderMatrix() {
        if (!this.matrixEl) return;
        // Text typed into an add box but not yet added survives the rebuild
        const drafts = new Map();
        this.matrixEl.querySelectorAll('.criteria-cell').forEach(cell => {
            const value = cell.querySelector('.criteria-add-input')?.value;
            if (value) drafts.set(this.cellSelector(cell.dataset.cat, cell.dataset.importance || null), value);
        });
        this.matrixEl.innerHTML = '';
        const levels = Object.entries(this.importanceLevels);

        const head = document.createElement('div');
        head.className = 'criteria-matrix-row criteria-matrix-head';
        head.innerHTML = html`<div class="criteria-matrix-corner">Chiều đánh giá</div>${levels.map(([key, level]) =>
            html`<div class="criteria-col-head" data-importance="${key}">${level.label} <span class="criteria-col-weight">×${level.weight}</span></div>`)}`;
        this.matrixEl.appendChild(head);

        Object.keys(LIST_NAMES).forEach((catKey, catIdx) => {
            const isCheckList = catKey === HR_CHECK_ITEMS_KEY;
            const count = this.categories[catKey].length;
            const row = document.createElement('div');
            row.className = isCheckList ? 'criteria-matrix-row criteria-check-row' : 'criteria-matrix-row';
            const problem = !isCheckList && this.categoryProblem(catKey);
            row.innerHTML = html`
                <div class="criteria-row-head">
                    <span class="criteria-row-title">${!isCheckList && `${catIdx + 1}. `}${LIST_NAMES[catKey]}</span>
                    <span class="criteria-row-count">${count} ${isCheckList ? 'mục' : 'tiêu chí'}</span>
                    ${isCheckList && html`<span class="criteria-row-note">Không chấm điểm</span>`}
                    ${problem && html`<span class="criteria-row-error" role="alert">${problem}</span>`}
                </div>`;
            if (isCheckList) {
                row.appendChild(this.buildCell(catKey, null));
            } else {
                levels.forEach(([key]) => row.appendChild(this.buildCell(catKey, key)));
            }
            this.matrixEl.appendChild(row);
        });

        drafts.forEach((value, selector) => {
            const input = this.matrixEl.querySelector(`${selector} .criteria-add-input`);
            if (input) input.value = value;
        });
        this.resizeAll(this.matrixEl);
    }

    /**
     * One cell of the matrix: the Category's items at one Importance (or all HR Check Items
     * when importance is null), plus an add box. It is also a drop target.
     */
    buildCell(catKey, importance) {
        const cell = document.createElement('div');
        cell.className = 'criteria-cell';
        cell.dataset.cat = catKey;
        if (importance) {
            cell.dataset.importance = importance;
            const label = document.createElement('div');
            label.className = 'criteria-cell-label';
            label.dataset.importance = importance;
            label.textContent = this.levelLabel(importance);
            cell.appendChild(label);
        }

        const list = document.createElement('div');
        list.className = 'criteria-chip-list';
        this.categories[catKey]
            .filter(item => importance === null || item.importance === importance)
            .forEach(item => list.appendChild(this.buildChip(catKey, item)));
        cell.appendChild(list);

        const addBox = document.createElement('div');
        addBox.className = 'criteria-add-box';
        addBox.innerHTML = html`
            <textarea rows="1" class="criteria-add-input" placeholder="+ Thêm" aria-label="Thêm ${importance ? `tiêu chí ${this.importanceLevels[importance].label} vào` : 'mục vào'} ${LIST_NAMES[catKey]}"></textarea>
            <button class="btn btn-sm btn-secondary criteria-add-btn" type="button" aria-label="Thêm">+</button>
        `;
        const addInput = addBox.querySelector('.criteria-add-input');
        const handleAdd = () => {
            const val = addInput.value.replace(/[\r\n]+/g, ' ').trim();
            if (!val) return;
            this.categories[catKey].push({ text: val, importance: importance || this.defaultImportance });
            this.renderMatrix();
            // Keep typing into the same cell's add box
            this.matrixEl.querySelector(`${this.cellSelector(catKey, importance)} .criteria-add-input`)?.focus();
        };
        addBox.querySelector('.criteria-add-btn').addEventListener('click', handleAdd);
        addInput.addEventListener('input', () => this.autosize(addInput));
        addInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                handleAdd();
            }
        });
        cell.appendChild(addBox);

        cell.addEventListener('dragover', (e) => {
            if (!this.dragged) return;
            e.preventDefault();
            e.dataTransfer.dropEffect = 'move';
            cell.classList.add('is-drop-target');
        });
        cell.addEventListener('dragleave', (e) => {
            if (!cell.contains(e.relatedTarget)) cell.classList.remove('is-drop-target');
        });
        cell.addEventListener('drop', (e) => {
            e.preventDefault();
            cell.classList.remove('is-drop-target');
            if (!this.dragged) return;
            const { catKey: fromCat, item } = this.dragged;
            this.dragged = null;
            this.moveItem(fromCat, item, catKey, importance);
        });
        return cell;
    }

    cellSelector(catKey, importance) {
        return importance
            ? `.criteria-cell[data-cat="${catKey}"][data-importance="${importance}"]`
            : `.criteria-cell[data-cat="${catKey}"]`;
    }

    /** One item: a drag handle, its in-place editable text and its "⋯" menu. */
    buildChip(catKey, item) {
        const chip = document.createElement('div');
        chip.className = 'criteria-chip';
        chip.innerHTML = html`
            <span class="criteria-chip-handle" title="Kéo để chuyển sang ô khác" aria-hidden="true">⠿</span>
            <textarea rows="1" class="criteria-item-text" aria-label="Nội dung tiêu chí"></textarea>
            ${catKey !== HR_CHECK_ITEMS_KEY && html`<span class="criteria-chip-points">${this.pointsLabel(catKey, item)}</span>`}
            <select class="criteria-chip-menu" title="Chuyển hoặc xóa" aria-label="Chuyển hoặc xóa tiêu chí">
                <option value="" selected>⋯</option>
                ${this.menuOptions(catKey, item)}
            </select>
        `;

        const textInput = chip.querySelector('.criteria-item-text');
        textInput.value = item.text;
        textInput.addEventListener('keydown', (e) => {
            if (e.key === 'Enter') {
                e.preventDefault();
                textInput.blur();
            }
        });
        textInput.addEventListener('input', () => {
            // Pasted text can still carry newlines; fold them into spaces.
            if (/[\r\n]/.test(textInput.value)) {
                textInput.value = textInput.value.replace(/[\r\n]+/g, ' ');
            }
            item.text = textInput.value;
            this.autosize(textInput);
        });

        // Only the handle starts a drag, so selecting text in the textarea still works
        const handle = chip.querySelector('.criteria-chip-handle');
        handle.addEventListener('mousedown', () => {
            chip.draggable = true;
            // A press with no drag must not leave the chip draggable
            document.addEventListener('mouseup', () => { if (!this.dragged) chip.draggable = false; }, { once: true });
        });
        chip.addEventListener('dragstart', (e) => {
            this.dragged = { catKey, item };
            e.dataTransfer.effectAllowed = 'move';
            e.dataTransfer.setData('text/plain', item.text);
            chip.classList.add('is-dragging');
        });
        chip.addEventListener('dragend', () => {
            chip.draggable = false;
            chip.classList.remove('is-dragging');
            this.dragged = null;
            this.matrixEl?.querySelectorAll('.is-drop-target').forEach(el => el.classList.remove('is-drop-target'));
        });

        chip.querySelector('.criteria-chip-menu').addEventListener('change', (e) => {
            const value = e.target.value;
            if (!value) return;
            if (value === DELETE_ACTION) {
                const list = this.categories[catKey];
                const idx = list.indexOf(item);
                if (idx !== -1) list.splice(idx, 1);
                this.renderMatrix();
                return;
            }
            const [toCat, toImportance] = value.split('|');
            this.moveItem(catKey, item, toCat, toImportance || null);
        });
        return chip;
    }

    /** The "⋯" menu: every other cell, grouped by row, then delete. */
    menuOptions(catKey, item) {
        const levels = Object.entries(this.importanceLevels);
        const groups = Object.keys(LIST_NAMES).map(k => {
            if (k === HR_CHECK_ITEMS_KEY) {
                return k !== catKey && html`<optgroup label="Chuyển đến: ${LIST_NAMES[k]}"><option value="${k}|">${LIST_NAMES[k]} (không chấm điểm)</option></optgroup>`;
            }
            const options = levels.map(([key, level]) => {
                const here = k === catKey && key === item.importance;
                return html`<option value="${k}|${key}"${here && raw(' disabled')}>${level.label}${here && ' (hiện tại)'}</option>`;
            });
            return html`<optgroup label="Chuyển đến: ${LIST_NAMES[k]}">${options}</optgroup>`;
        });
        return html`${groups}<optgroup label="Thao tác"><option value="${DELETE_ACTION}">Xóa</option></optgroup>`;
    }

    /**
     * Moves an item to the end of another cell. A Criterion takes the target column's
     * Importance; an HR Check Item has none, so one moved there (and later back out) is Standard.
     */
    moveItem(fromCat, item, toCat, toImportance) {
        if (!this.categories[toCat]) return;
        const isCheck = toCat === HR_CHECK_ITEMS_KEY;
        if (fromCat === toCat && (isCheck || item.importance === toImportance)) return;
        const from = this.categories[fromCat];
        const idx = from.indexOf(item);
        if (idx === -1) return;
        from.splice(idx, 1);
        item.importance = isCheck ? this.defaultImportance : this.normalizeImportance(toImportance);
        this.categories[toCat].push(item);
        this.renderMatrix();
    }

    /**
     * Grows a textarea to fit its content. Skipped while the editor is hidden
     * (scrollHeight is 0), so callers re-run resizeAll() once it is shown.
     */
    autosize(el) {
        if (!el || el.scrollHeight === 0) return;
        el.style.height = 'auto';
        // scrollHeight excludes borders; add them back so no scrollbar appears.
        const borders = el.offsetHeight - el.clientHeight;
        el.style.height = `${el.scrollHeight + borders}px`;
    }

    resizeAll(root = this.container) {
        if (!root) return;
        root.querySelectorAll('textarea').forEach(el => this.autosize(el));
    }
}
