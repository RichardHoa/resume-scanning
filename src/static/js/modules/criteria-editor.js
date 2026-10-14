/**
 * ==============================================================================
 * Shared Criteria Editor (Verify step & RAG Workbench)
 * ==============================================================================
 * Description: Renders the five Category cards stacked full-width, one per row,
 *              then a card of HR Check Items (requirements no resume would show,
 *              never scored). Each item is an auto-growing, wrapping textarea; Enter
 *              never inserts a newline, so items stay single logical lines. A "move
 *              to" menu on each item moves it to another Category or to the HR Check
 *              Items. Callers pass categories in as {category_key: [criterion text]}
 *              plus the HR Check Items list, and read them back with getCategories()
 *              and getHrCheckItems().
 * Line Count: ~215 lines (Strict Limit: < 500 lines)
 */

// Display names of the five Categories, in card order. Also used to label evaluation dimensions.
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

// Every list the editor holds, in card order: the five Categories, then the HR Check Items
const LIST_NAMES = { ...CATEGORY_NAMES, [HR_CHECK_ITEMS_KEY]: HR_CHECK_ITEMS_NAME };

export class CriteriaEditor {
    /**
     * @param {HTMLElement} container - Element the Category cards are rendered into.
     */
    constructor(container) {
        this.container = container;
        this.categories = CriteriaEditor.emptyCategories();
        window.addEventListener('resize', () => this.resizeAll());
    }

    static emptyCategories() {
        const cats = {};
        Object.keys(LIST_NAMES).forEach(k => { cats[k] = []; });
        return cats;
    }

    /**
     * Replaces the edited set. Accepts items as plain strings or as {text} objects
     * (the shape returned by the RAG info endpoint).
     * @param {Object} rawCats - {category_key: [criterion]} for the five Categories.
     * @param {Array} [hrCheckItems=[]] - The HR Check Items.
     */
    setCategories(rawCats, hrCheckItems = []) {
        this.categories = CriteriaEditor.emptyCategories();
        const toText = it => (typeof it === 'object' && it !== null ? String(it.text || '') : String(it));
        Object.keys(CATEGORY_NAMES).forEach(k => {
            this.categories[k] = ((rawCats && rawCats[k]) || []).map(toText);
        });
        this.categories[HR_CHECK_ITEMS_KEY] = (hrCheckItems || []).map(toText);
        this.render();
    }

    /**
     * Returns a copy of the five Categories as {category_key: [criterion text]}.
     */
    getCategories() {
        const cats = {};
        Object.keys(CATEGORY_NAMES).forEach(k => { cats[k] = [...this.categories[k]]; });
        return cats;
    }

    /** Returns a copy of the HR Check Items. */
    getHrCheckItems() {
        return [...this.categories[HR_CHECK_ITEMS_KEY]];
    }

    /** Number of Criteria in the five Categories; HR Check Items are not Criteria. */
    totalCount() {
        return Object.values(this.getCategories()).reduce((acc, items) => acc + items.length, 0);
    }

    render() {
        if (!this.container) return;
        this.container.innerHTML = '';
        this.cards = {};

        Object.keys(LIST_NAMES).forEach((catKey, catIdx) => {
            const isCheckList = catKey === HR_CHECK_ITEMS_KEY;
            const card = document.createElement('div');
            card.className = isCheckList ? 'criteria-category-card criteria-hr-check-card' : 'criteria-category-card';
            card.setAttribute('data-cat', catKey);

            card.innerHTML = `
                <div class="criteria-card-header">
                    <span class="criteria-card-title">${isCheckList ? '' : `${catIdx + 1}. `}${LIST_NAMES[catKey]}</span>
                    <span class="badge-success cat-count-badge" style="font-size:0.75rem;"></span>
                </div>
                ${isCheckList ? '<p class="criteria-hr-check-note">Yêu cầu mà CV thông thường không thể hiện (vd: sẵn sàng tăng ca, thời gian nhận việc). Không chấm điểm ứng viên theo các mục này; HR tự kiểm tra khi phỏng vấn.</p>' : ''}
                <div class="criteria-items-list"></div>
                <div class="criteria-add-box">
                    <textarea rows="1" class="criteria-add-input" placeholder="${isCheckList ? '+ Thêm mục HR cần kiểm tra...' : '+ Thêm tiêu chí mới cho chiều này...'}"></textarea>
                    <button class="btn btn-sm btn-secondary criteria-add-btn" type="button">Thêm</button>
                </div>
            `;

            const listEl = card.querySelector('.criteria-items-list');
            this.cards[catKey] = { card, listEl };
            this.renderItemList(card, listEl, catKey);

            const addInput = card.querySelector('.criteria-add-input');
            const addBtn = card.querySelector('.criteria-add-btn');
            const handleAdd = () => {
                const val = addInput.value.replace(/[\r\n]+/g, ' ').trim();
                if (val) {
                    this.categories[catKey].push(val);
                    this.renderItemList(card, listEl, catKey);
                    addInput.value = '';
                    this.autosize(addInput);
                }
            };

            addBtn.addEventListener('click', handleAdd);
            addInput.addEventListener('input', () => this.autosize(addInput));
            addInput.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') {
                    e.preventDefault();
                    handleAdd();
                }
            });

            this.container.appendChild(card);
        });

        this.resizeAll();
    }

    renderItemList(card, listEl, catKey) {
        listEl.innerHTML = '';
        const items = this.categories[catKey];
        const isCheckList = catKey === HR_CHECK_ITEMS_KEY;
        const countBadge = card.querySelector('.cat-count-badge');
        if (countBadge) countBadge.textContent = `${items.length} ${isCheckList ? 'mục' : 'tiêu chí'}`;

        if (items.length === 0) {
            const emptyText = isCheckList ? 'Không có mục nào cần HR kiểm tra thủ công.' : 'Chưa có tiêu chí nào trong chiều này.';
            listEl.innerHTML = `<div style="font-size:0.8rem; color:var(--text-muted); font-style:italic; padding:6px 0;">${emptyText}</div>`;
            return;
        }

        const moveOptions = Object.keys(LIST_NAMES)
            .filter(k => k !== catKey)
            .map(k => `<option value="${k}">${LIST_NAMES[k]}</option>`)
            .join('');

        items.forEach((itemText, idx) => {
            const row = document.createElement('div');
            row.className = 'criteria-item-row';
            row.innerHTML = `
                <span class="criteria-item-num">${idx + 1}.</span>
                <textarea rows="1" class="criteria-item-text"></textarea>
                <select class="criteria-item-move" title="Chuyển sang chiều khác" aria-label="Chuyển sang chiều khác">
                    <option value="" selected>Chuyển sang…</option>
                    ${moveOptions}
                </select>
                <button class="criteria-item-del-btn" title="Xóa tiêu chí" type="button">
                    <svg viewBox="0 0 24 24" width="14" height="14" fill="currentColor"><path d="M6 19c0 1.1.9 2 2 2h8c1.1 0 2-.9 2-2V7H6v12zM19 4h-3.5l-1-1h-5l-1 1H5v2h14V4z"/></svg>
                </button>
            `;

            const textInput = row.querySelector('.criteria-item-text');
            textInput.value = itemText;
            textInput.addEventListener('keydown', (e) => {
                if (e.key === 'Enter') e.preventDefault();
            });
            textInput.addEventListener('input', () => {
                // Pasted text can still carry newlines; fold them into spaces.
                if (/[\r\n]/.test(textInput.value)) {
                    textInput.value = textInput.value.replace(/[\r\n]+/g, ' ');
                }
                this.categories[catKey][idx] = textInput.value;
                this.autosize(textInput);
            });

            row.querySelector('.criteria-item-move').addEventListener('change', (e) => {
                const target = e.target.value;
                if (!target || !this.cards[target]) return;
                const [moved] = this.categories[catKey].splice(idx, 1);
                this.categories[target].push(moved);
                this.renderItemList(card, listEl, catKey);
                this.renderItemList(this.cards[target].card, this.cards[target].listEl, target);
            });

            row.querySelector('.criteria-item-del-btn').addEventListener('click', () => {
                this.categories[catKey].splice(idx, 1);
                this.renderItemList(card, listEl, catKey);
            });

            listEl.appendChild(row);
        });

        this.resizeAll(listEl);
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
