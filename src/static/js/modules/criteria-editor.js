/**
 * ==============================================================================
 * Shared Criteria Editor (Verify step & RAG Workbench)
 * ==============================================================================
 * Description: Renders the five Category cards stacked full-width, one per row.
 *              Each Criterion is an auto-growing, wrapping textarea; Enter never
 *              inserts a newline, so Criteria stay single logical lines.
 *              Callers pass categories in as {category_key: [criterion text]} and
 *              read the edited set back with getCategories().
 * Line Count: ~175 lines (Strict Limit: < 500 lines)
 */

// Display names of the five Categories, in card order. Also used to label evaluation dimensions.
export const CATEGORY_NAMES = {
    seniority_title: 'Vị trí & Số năm kinh nghiệm',
    technical_skills: 'Kỹ năng, Công cụ & Chuyên môn',
    work_experience: 'Kinh nghiệm làm việc, Dự án & Trách nhiệm',
    education_certifications: 'Bằng cấp & Chứng chỉ',
    hidden_culture: 'Yêu cầu ẩn & Văn hóa'
};

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
        Object.keys(CATEGORY_NAMES).forEach(k => { cats[k] = []; });
        return cats;
    }

    /**
     * Replaces the edited set. Accepts items as plain strings or as {text} objects
     * (the shape returned by the RAG info endpoint).
     */
    setCategories(rawCats) {
        this.categories = CriteriaEditor.emptyCategories();
        Object.keys(this.categories).forEach(k => {
            const items = (rawCats && rawCats[k]) || [];
            this.categories[k] = items.map(it => (typeof it === 'object' && it !== null ? String(it.text || '') : String(it)));
        });
        this.render();
    }

    /**
     * Returns a copy of the edited set as {category_key: [criterion text]}.
     */
    getCategories() {
        const cats = {};
        Object.keys(this.categories).forEach(k => { cats[k] = [...this.categories[k]]; });
        return cats;
    }

    totalCount() {
        return Object.values(this.categories).reduce((acc, items) => acc + items.length, 0);
    }

    render() {
        if (!this.container) return;
        this.container.innerHTML = '';

        Object.keys(CATEGORY_NAMES).forEach((catKey, catIdx) => {
            const card = document.createElement('div');
            card.className = 'criteria-category-card';
            card.setAttribute('data-cat', catKey);

            card.innerHTML = `
                <div class="criteria-card-header">
                    <span class="criteria-card-title">${catIdx + 1}. ${CATEGORY_NAMES[catKey]}</span>
                    <span class="badge-success cat-count-badge" style="font-size:0.75rem;"></span>
                </div>
                <div class="criteria-items-list"></div>
                <div class="criteria-add-box">
                    <textarea rows="1" class="criteria-add-input" placeholder="+ Thêm tiêu chí mới cho chiều này..."></textarea>
                    <button class="btn btn-sm btn-secondary criteria-add-btn" type="button">Thêm</button>
                </div>
            `;

            const listEl = card.querySelector('.criteria-items-list');
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
        const countBadge = card.querySelector('.cat-count-badge');
        if (countBadge) countBadge.textContent = `${items.length} tiêu chí`;

        if (items.length === 0) {
            listEl.innerHTML = '<div style="font-size:0.8rem; color:var(--text-muted); font-style:italic; padding:6px 0;">Chưa có tiêu chí nào trong chiều này.</div>';
            return;
        }

        items.forEach((itemText, idx) => {
            const row = document.createElement('div');
            row.className = 'criteria-item-row';
            row.innerHTML = `
                <span class="criteria-item-num">${idx + 1}.</span>
                <textarea rows="1" class="criteria-item-text"></textarea>
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
