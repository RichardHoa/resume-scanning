/**
 * ==============================================================================
 * Centralized REST API Service Wrapper
 * ==============================================================================
 * Description: Provides async helper methods for communicating with FastAPI
 *              backend endpoints (PDF extraction, evaluation batch execution,
 *              RAG vector status, candidate pool records, and prompt logs).
 * Line Count: ~100 lines (Strict Limit: < 500 lines)
 */
export const API = {
    /**
     * Retrieves server configuration (model name, backend engine, mock mode).
     * @returns {Promise<Object>} JSON response object containing server parameters.
     */
    async fetchConfig() {
        const res = await fetch('/api/config');
        if (!res.ok) throw new Error('Failed to load server configuration.');
        return await res.json();
    },

    /**
     * Uploads a candidate PDF resume file to start AI layout extraction.
     * @param {File} file - PDF resume file object.
     * @returns {Promise<{data: Object, extractionTime: string|null}>} Extracted JSON & execution time header.
     */
    async extractCv(file) {
        const formData = new FormData();
        formData.append('file', file);
        const response = await fetch('/api/extract', {
            method: 'POST',
            body: formData
        });
        if (!response.ok) {
            const errData = await response.json().catch(() => ({}));
            throw new Error(errData.detail || 'Extraction failed.');
        }
        const data = await response.json();
        const timeHeader = response.headers.get('X-Extraction-Time');
        return { data, extractionTime: timeHeader };
    },

    /**
     * Retrieves list of scanned resumes available in approved_jsons/ and output_jsons/.
     * @returns {Promise<{resumes: Array<Object>}>} Array of candidate summary objects.
     */
    async getScannedResumes() {
        const res = await fetch('/api/scanned_resumes');
        if (!res.ok) throw new Error('Failed to fetch scanned resumes.');
        return await res.json();
    },

    /**
     * Evaluates candidate resumes against standard & hidden job criteria.
     * @param {string} stdReq - Standard job requirements text.
     * @param {string} hiddenReq - HR hidden / culture fit requirements text.
     * @param {Array<string>} filenames - List of candidate JSON filenames to evaluate.
     * @returns {Promise<Object>} Batch evaluation leaderboard results.
     */
    async evaluateBatch(stdReq, hiddenReq, filenames) {
        const res = await fetch('/api/evaluate_batch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                standard_requirements: stdReq,
                hidden_requirements: hiddenReq,
                resume_filenames: filenames
            })
        });
        if (!res.ok) {
            const errData = await res.json().catch(() => ({}));
            throw new Error(errData.detail || 'Evaluation failed.');
        }
        return await res.json();
    },

    /**
     * Fetches current RAG ChromaDB vector status and 5-dimension criteria breakdown.
     * @returns {Promise<Object>} RAG summary report object.
     */
    async getRagInfo() {
        const res = await fetch('/api/rag');
        if (!res.ok) throw new Error('Failed to fetch RAG database status.');
        return await res.json();
    },

    /**
     * Clears persistent local ChromaDB vector store.
     * @returns {Promise<Object>} Success status message.
     */
    async clearRagInfo() {
        const res = await fetch('/api/rag', { method: 'DELETE' });
        if (!res.ok) throw new Error('Failed to clear RAG database.');
        return await res.json();
    },

    /**
     * Retrieves secret evaluation tier email ordering metadata.
     * @returns {Promise<{tier1: Array<string>, tier2: Array<string>, file_found: boolean}>} Secret tier data.
     */
    async getEvaluationOrder() {
        const res = await fetch('/api/evaluation_order');
        if (!res.ok) throw new Error('Failed to fetch evaluation order configuration.');
        return await res.json();
    },

    /**
     * Lists candidate evaluation reports stored in eval_results/.
     * @returns {Promise<{evaluations: Array<Object>}>} Array of candidate evaluation objects.
     */
    async getEvalResults() {
        const res = await fetch('/api/eval_results');
        if (!res.ok) throw new Error('Failed to fetch candidate evaluations.');
        return await res.json();
    },

    /**
     * Retrieves full detail report JSON for a specific candidate evaluation.
     * @param {string} filename - Target evaluation report filename.
     * @returns {Promise<Object>} Full evaluation detail object.
     */
    async getEvalResultDetail(filename) {
        const res = await fetch(`/api/eval_results/${encodeURIComponent(filename)}`);
        if (!res.ok) throw new Error('Failed to fetch evaluation detail.');
        return await res.json();
    },

    /**
     * Deletes an evaluation report JSON file.
     * @param {string} filename - Target evaluation report filename to delete.
     * @returns {Promise<Object>} Operation success result.
     */
    async deleteEvalResult(filename) {
        const res = await fetch(`/api/eval_results/${encodeURIComponent(filename)}`, { method: 'DELETE' });
        if (!res.ok) throw new Error('Failed to delete evaluation result.');
        return await res.json();
    }
};
