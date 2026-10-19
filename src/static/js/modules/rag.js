/**
 * ==============================================================================
 * RAG Knowledge Base Controller
 * ==============================================================================
 * Description: Manages viewing persistent local ChromaDB vector store status,
 *              editing stored Criteria across 5 dimensions with the shared Criteria
 *              editor, saving them back to the RAG, and clearing vector database cache.
 */

import { API } from './api.js';
import { CriteriaEditor } from './criteria-editor.js';
import { WaitingScreen } from './waiting-screen.js';
import { byId } from './dom.js';
import { html } from './html.js';

export class RagController {
    constructor() {
        this.initDOMElements();
        this.criteriaEditor = new CriteriaEditor(this.ragCategoriesGrid);
        this.waitingScreen = new WaitingScreen();
        this.initEvents();
        this.loadRagKnowledgeBase();
    }

    /**
     * Binds DOM element references required for RAG database status display.
     */
    initDOMElements() {
        this.btnRefreshRag = byId('btn-refresh-rag');
        this.btnClearRag = byId('btn-clear-rag');
        this.btnSaveRag = byId('btn-save-rag');
        this.ragCategoriesGrid = byId('rag-categories-grid');
        this.hrRagCodeView = byId('hr-rag-code-view');
        this.statusBadge = byId('rag-status-badge');
        this.engineBadge = byId('rag-engine-badge');
        this.totalCountSpan = byId('rag-total-count');
        this.dbPathCode = byId('rag-db-path');
    }

    /**
     * Registers event listeners for refresh and clear RAG triggers.
     */
    initEvents() {
        this.btnRefreshRag.addEventListener('click', () => this.loadRagKnowledgeBase());
        this.btnClearRag.addEventListener('click', () => this.clearRagDatabase());
        this.btnSaveRag.addEventListener('click', () => this.saveRagCriteria());
    }

    /**
     * Fetches current RAG vector store stats and loads the Criteria into the shared editor.
     */
    async loadRagKnowledgeBase() {
        this.ragCategoriesGrid.innerHTML = '<div class="loading-state">Đang tải kho tri thức RAG...</div>';
        // Saving before a successful load would send empty Categories and wipe the stored Criteria.
        this.btnSaveRag.disabled = true;

        try {
            const data = await API.getRagInfo();
            this.renderRagSummary(data);
            this.btnSaveRag.disabled = false;
        } catch (err) {
            this.ragCategoriesGrid.innerHTML = html`<div class="error-state">Không tải được CSDL RAG: ${err.message}</div>`;
        }
    }

    /**
     * Renders status badges, the Criteria editor and the hr_rag.txt preview from a RAG summary.
     */
    renderRagSummary(data) {
        this.dbPathCode.textContent = data.db_path;
        this.totalCountSpan.textContent = data.total_items;
        this.engineBadge.textContent = data.engine;

        if (data.has_stored_rag) {
            this.statusBadge.textContent = 'RAG đang hoạt động (bỏ qua bước phân loại bằng LLM)';
            this.statusBadge.className = 'badge-success';
        } else {
            this.statusBadge.textContent = 'RAG trống (khi đánh giá sẽ chạy phân loại)';
            this.statusBadge.className = 'badge-warning';
        }

        this.hrRagCodeView.textContent = data.hr_rag_text || 'Hiện chưa lưu tệp tóm tắt hr_rag.txt nào.';

        this.criteriaEditor.setCategories(data.categories, data.hr_check_items, data.importance_levels, data.default_importance);
    }

    /**
     * Saves the whole edited set back to the RAG. Requirement text is omitted so the server
     * keeps HR's stored original Standard/Hidden Requirements in hr_rag.txt.
     */
    async saveRagCriteria() {
        if (!this.criteriaEditor.confirmSavable()) return;
        try {
            const updated = await this.waitingScreen.run(
                'save_criteria',
                'Đang lưu tiêu chí vào RAG...',
                'Đang embedding lại toàn bộ tiêu chí vào kho vector RAG và cập nhật hr_rag.txt...',
                () => API.updateRagCriteria(this.criteriaEditor.getCategories(), this.criteriaEditor.getHrCheckItems())
            );
            this.renderRagSummary(updated);
            alert('Đã lưu tiêu chí vào RAG.');
        } catch (err) {
            alert('Không lưu được tiêu chí RAG: ' + err.message);
        }
    }

    /**
     * Wipes local ChromaDB vector store and resets database status.
     */
    async clearRagDatabase() {
        if (!confirm('Bạn có chắc muốn xóa cơ sở dữ liệu RAG? Toàn bộ tiêu chí đã lưu sẽ bị xóa.')) {
            return;
        }
        try {
            await API.clearRagInfo();
            alert('Đã xóa cơ sở dữ liệu RAG.');
            this.loadRagKnowledgeBase();
        } catch (err) {
            alert('Không xóa được cơ sở dữ liệu RAG: ' + err.message);
        }
    }
}
