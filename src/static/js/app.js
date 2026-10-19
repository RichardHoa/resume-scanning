/**
 * ==============================================================================
 * AI Resume Extractor & Evaluation Dashboard - Main Entry Script
 * ==============================================================================
 * Description: Multi-page application bootstrapper. Starts the controller of the
 *              page named by <body data-page> (set by the shared layout); each
 *              controller loads its own initial data.
 */

import { ExtractorController } from './modules/extractor.js';
import { EvaluatorController } from './modules/evaluator.js';
import { RagController } from './modules/rag.js';
import { CandidatePoolController } from './modules/candidates.js';

const PAGE_CONTROLLERS = {
    extractor: () => new ExtractorController(),
    evaluator: () => new EvaluatorController(),
    rag: () => new RagController(),
    candidates: () => new CandidatePoolController()
};

document.addEventListener('DOMContentLoaded', () => {
    PAGE_CONTROLLERS[document.body.dataset.page]?.();
});
