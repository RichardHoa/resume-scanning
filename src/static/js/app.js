/**
 * ==============================================================================
 * AI Resume Extractor & Evaluation Dashboard - Main Entry Script
 * ==============================================================================
 * Description: Multi-page application bootstrapper. Automatically detects the
 *              current active HTML page, initializes page-specific controllers,
 *              and polls server configuration parameters for header status badges.
 */

import { API } from './modules/api.js';
import { ExtractorController } from './modules/extractor.js';
import { EvaluatorController } from './modules/evaluator.js';
import { RagController } from './modules/rag.js';
import { CandidatePoolController } from './modules/candidates.js';

document.addEventListener('DOMContentLoaded', () => {
    // 1. Load Server Configuration for Header Status Badges
    fetchServerConfig();

    // 2. Multi-Page DOM Detection & Controller Bootstrapping
    initCurrentPage();

    /**
     * Inspects active DOM elements to instantiate only the necessary page controller.
     */
    function initCurrentPage() {
        // Step 1: CV Extractor Page Initialization
        if (document.getElementById('dropzone') || document.getElementById('page-extractor')) {
            new ExtractorController();
        }

        // Step 2: HR Evaluator Page Initialization
        if (document.getElementById('scanned-resumes-container') || document.getElementById('page-evaluator')) {
            const evaluatorCtrl = new EvaluatorController();
            evaluatorCtrl.loadScannedResumes();
        }

        // Page 3: RAG Knowledge Base Page Initialization
        if (document.getElementById('rag-categories-grid') || document.getElementById('page-rag')) {
            const ragCtrl = new RagController();
            ragCtrl.loadRagKnowledgeBase();
        }

        // Page 4: Candidate Evaluation Pool Page Initialization
        if (document.getElementById('cand-cards-grid') || document.getElementById('page-candidates')) {
            const candidatesCtrl = new CandidatePoolController();
            candidatesCtrl.loadCandidatePool();
        }
    }

    /**
     * Fetches current backend model, backend type (vLLM / Transformers), and mock mode config.
     */
    async function fetchServerConfig() {
        try {
            const data = await API.fetchConfig();
            const modelParts = (data.model || '').split('/');
            const shortModelName = modelParts[modelParts.length - 1] || 'Default Model';

            const elModel = document.getElementById('val-model');
            if (elModel) {
                elModel.textContent = shortModelName + (data.mock ? ' (Mock Mode)' : '');
            }

            const elMode = document.getElementById('val-mode');
            if (elMode) {
                elMode.textContent = data.image_mode ? 'Vision Mode' : 'Text Mode';
            }
        } catch (e) {
            console.error('[App] Failed to load server configuration:', e);
        }
    }
});
