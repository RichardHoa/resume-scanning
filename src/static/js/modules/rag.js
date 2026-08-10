/**
 * ==============================================================================
 * RAG Knowledge Base Controller
 * ==============================================================================
 * Description: Manages viewing persistent local ChromaDB vector store status,
 *              rendering decomposed HR requirements across 5 criteria dimensions,
 *              and clearing vector database cache.
 * Line Count: ~120 lines (Strict Limit: < 500 lines)
 */

import { API } from './api.js';

export class RagController {
    constructor() {
        this.initDOMElements();
        this.initEvents();
    }

    /**
     * Binds DOM element references required for RAG database status display.
     */
    initDOMElements() {
        this.btnRefreshRag = document.getElementById('btn-refresh-rag');
        this.btnClearRag = document.getElementById('btn-clear-rag');
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
    }

    /**
     * Fetches current RAG vector store stats and renders 5 criteria dimension cards.
     */
    async loadRagKnowledgeBase() {
        if (!this.ragCategoriesGrid) return;
        this.ragCategoriesGrid.innerHTML = '<div class="loading-state">Loading RAG Knowledge Base...</div>';

        try {
            const data = await API.getRagInfo();

            if (this.dbPathCode) this.dbPathCode.textContent = data.db_path || 'rag/chroma_db';
            if (this.totalCountSpan) this.totalCountSpan.textContent = data.total_items || 0;
            if (this.engineBadge && data.engine) this.engineBadge.textContent = data.engine;

            if (this.statusBadge) {
                if (data.has_stored_rag) {
                    this.statusBadge.textContent = 'RAG Active (Skipping LLM Categorization)';
                    this.statusBadge.className = 'badge-success';
                } else {
                    this.statusBadge.textContent = 'RAG Empty (Evaluating will trigger categorization)';
                    this.statusBadge.className = 'badge-rec rec-LOW_MATCH';
                }
            }

            if (this.hrRagCodeView) {
                this.hrRagCodeView.textContent = data.hr_rag_text || 'No hr_rag.txt summary file currently stored.';
            }

            this.ragCategoriesGrid.innerHTML = '';

            const catLabels = {
                "seniority_title": "1. SENIORITY_TITLE (Title & Experience Years)",
                "technical_skills": "2. TECHNICAL_SKILLS (Tools & Languages)",
                "work_experience": "3. WORK_EXPERIENCE (Projects & Responsibilities)",
                "education_certifications": "4. EDUCATION_CERTIFICATIONS (Degrees & Certs)",
                "hidden_culture": "5. HIDDEN_CULTURE (Unstated Rules & Soft Skills)"
            };

            const categories = data.categories || {};
            Object.keys(catLabels).forEach(catKey => {
                const items = categories[catKey] || [];
                const card = document.createElement('div');
                card.className = 'dimension-card';

                const itemsListHtml = items.length > 0
                    ? items.map((it, idx) => `
                        <li style="margin-bottom: 6px;">
                            <strong>${idx + 1}.</strong> ${this.escapeHtml(it.text)}
                            <span style="font-size:0.7rem; color:var(--text-muted); float:right;">[${this.escapeHtml(it.type)}]</span>
                        </li>
                      `).join('')
                    : '<li style="color: var(--text-muted); font-style: italic;">No criteria items stored</li>';

                card.innerHTML = `
                    <div class="dim-header">
                        <span>${catLabels[catKey]}</span>
                        <span class="dim-score" style="font-size: 0.85rem; padding: 2px 8px;">${items.length} items</span>
                    </div>
                    <ul class="dim-list" style="margin-top: 8px;">
                        ${itemsListHtml}
                    </ul>
                `;
                this.ragCategoriesGrid.appendChild(card);
            });
        } catch (err) {
            this.ragCategoriesGrid.innerHTML = `<div class="error-state">Failed to load RAG DB: ${err.message}</div>`;
        }
    }

    /**
     * Wipes local ChromaDB vector store and resets database status.
     */
    async clearRagDatabase() {
        if (!confirm('Are you sure you want to delete the persistent RAG database? This will wipe stored criteria.')) {
            return;
        }
        try {
            const data = await API.clearRagInfo();
            alert(data.message || 'RAG database cleared successfully.');
            this.loadRagKnowledgeBase();
        } catch (err) {
            alert('Failed to clear RAG database: ' + err.message);
        }
    }

    escapeHtml(str) {
        if (!str) return '';
        return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;').replace(/"/g, '&quot;');
    }
}
