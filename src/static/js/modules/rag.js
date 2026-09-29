/**
 * ==============================================================================
 * RAG Knowledge Base Controller
 * ==============================================================================
 * Description: Manages viewing persistent local ChromaDB vector store status,
 *              editing stored Criteria across 5 dimensions with the shared Criteria
 *              editor, saving them back to the RAG, and clearing vector database cache.
 * Line Count: ~135 lines (Strict Limit: < 500 lines)
 */

import { API } from './api.js';
import { CriteriaEditor } from './criteria-editor.js';
import { WaitingScreen } from './waiting-screen.js';

export class RagController {
    constructor() {
        this.initDOMElements();
        this.criteriaEditor = new CriteriaEditor(this.ragCategoriesGrid);
        this.waitingScreen = new WaitingScreen();
        this.initEvents();
    }

    /**
     * Binds DOM element references required for RAG database status display.
     */
    initDOMElements() {
        this.btnRefreshRag = document.getElementById('btn-refresh-rag');
        this.btnClearRag = document.getElementById('btn-clear-rag');
        this.btnSaveRag = document.getElementById('btn-save-rag');
        this.ragCategoriesGrid = document.getElementById('rag-categories-grid');
        this.hrRagCodeView = document.getElementById('hr-rag-code-view');
        this.statusBadge = document.getElementById('rag-status-badge');
        this.engineBadge = document.getElementById('rag-engine-badge');
        this.totalCountSpan = document.getElementById('rag-total-count');
        this.dbPathCode = document.getElementById('rag-db-path');
    }

    /**
     * Registers event listeners for refresh and clear RAG triggers.
     */
    initEvents() {
        if (this.btnRefreshRag) {
            this.btnRefreshRag.addEventListener('click', () => this.loadRagKnowledgeBase());
        }
        if (this.btnClearRag) {
            this.btnClearRag.addEventListener('click', () => this.clearRagDatabase());
        }
        if (this.btnSaveRag) {
            this.btnSaveRag.addEventListener('click', () => this.saveRagCriteria());
        }
    }

    /**
     * Fetches current RAG vector store stats and loads the Criteria into the shared editor.
     */
    async loadRagKnowledgeBase() {
        if (!this.ragCategoriesGrid) return;
        this.ragCategoriesGrid.innerHTML = '<div class="loading-state">Đang tải kho tri thức RAG...</div>';
        // Saving before a successful load would send empty Categories and wipe the stored Criteria.
        if (this.btnSaveRag) this.btnSaveRag.disabled = true;

        try {
            const data = await API.getRagInfo();
            this.renderRagSummary(data);
            if (this.btnSaveRag) this.btnSaveRag.disabled = false;
        } catch (err) {
            this.ragCategoriesGrid.innerHTML = `<div class="error-state">Không tải được CSDL RAG: ${this.escapeHtml(err.message)}</div>`;
        }
    }

    /**
     * Renders status badges, the Criteria editor and the hr_rag.txt preview from a RAG summary.
     */
    renderRagSummary(data) {
        if (this.dbPathCode) this.dbPathCode.textContent = data.db_path || 'rag/chroma_db';
        if (this.totalCountSpan) this.totalCountSpan.textContent = data.total_items || 0;
        if (this.engineBadge && data.engine) this.engineBadge.textContent = data.engine;

        if (this.statusBadge) {
            if (data.has_stored_rag) {
                this.statusBadge.textContent = 'RAG đang hoạt động (bỏ qua bước phân loại bằng LLM)';
                this.statusBadge.className = 'badge-success';
            } else {
                this.statusBadge.textContent = 'RAG trống (khi đánh giá sẽ chạy phân loại)';
                this.statusBadge.className = 'badge-rec rec-LOW_MATCH';
            }
        }

        if (this.hrRagCodeView) {
            this.hrRagCodeView.textContent = data.hr_rag_text || 'Hiện chưa lưu tệp tóm tắt hr_rag.txt nào.';
        }

        this.criteriaEditor.setCategories(data.categories || {});
    }

    /**
     * Saves the whole edited set back to the RAG. Requirement text is omitted so the server
     * keeps HR's stored original Standard/Hidden Requirements in hr_rag.txt.
     */
    async saveRagCriteria() {
        if (!this.btnSaveRag) return;
        try {
            const updated = await this.waitingScreen.run(
                'save_criteria',
                'Đang lưu tiêu chí vào RAG...',
                'Đang embedding lại toàn bộ tiêu chí vào kho vector RAG và cập nhật hr_rag.txt...',
                () => API.updateRagCriteria(this.criteriaEditor.getCategories())
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
            const data = await API.clearRagInfo();
            alert('Đã xóa cơ sở dữ liệu RAG.');
            this.loadRagKnowledgeBase();
        } catch (err) {
            alert('Không xóa được cơ sở dữ liệu RAG: ' + err.message);
        }
    }

    escapeHtml(str) {
        if (!str) return '';
        return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }
}
