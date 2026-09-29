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
        if (!res.ok) throw new Error('Không tải được cấu hình máy chủ.');
        return await res.json();
    },

    /**
     * Uploads a candidate PDF resume file to start AI layout extraction.
     * @param {File} file - PDF resume file object.
     * @param {string} [language='vietnamese'] - Target parse language flag ('vietnamese' or 'english').
     * @returns {Promise<{data: Object, extractionTime: string|null}>} Extracted JSON & execution time header.
     */
    async extractCv(file, language = "vietnamese") {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('language', language);
        const response = await fetch('/api/extract', {
            method: 'POST',
            body: formData
        });
        if (!response.ok) {
            const errData = await response.json().catch(() => ({}));
            throw new Error(errData.error || errData.detail || 'Trích xuất thất bại.');
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
        if (!res.ok) throw new Error('Không tải được danh sách CV đã quét.');
        return await res.json();
    },

    /**
     * Evaluates candidate resumes against standard & hidden job criteria or verified RAG criteria.
     * @param {string} stdReq - Standard job requirements text.
     * @param {string} hiddenReq - HR hidden / culture fit requirements text.
     * @param {Array<string>} filenames - List of candidate JSON filenames to evaluate.
     * @param {boolean} [useExistingRag=false] - Whether to use already verified RAG criteria.
     * @returns {Promise<Object>} Batch evaluation leaderboard results.
     */
    async evaluateBatch(stdReq, hiddenReq, filenames, useExistingRag = false) {
        const res = await fetch('/api/evaluate_batch', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                standard_requirements: stdReq,
                hidden_requirements: hiddenReq,
                resume_filenames: filenames,
                use_existing_rag: useExistingRag
            })
        });
        if (!res.ok) {
            const errData = await res.json().catch(() => ({}));
            const errMsg = errData.detail || errData.error || errData.message || `Máy chủ trả về mã lỗi HTTP ${res.status}`;
            throw new Error(errMsg);
        }
        return await res.json();
    },

    /**
     * Starts a batch evaluation as a background job on the server.
     * Takes the same arguments as evaluateBatch.
     * @returns {Promise<{job_id: string}>} Id of the started job.
     */
    async startEvaluationJob(stdReq, hiddenReq, filenames, useExistingRag = false, language = "vietnamese") {
        const res = await fetch('/api/evaluate_batch/jobs', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                standard_requirements: stdReq,
                hidden_requirements: hiddenReq,
                resume_filenames: filenames,
                use_existing_rag: useExistingRag,
                language: language
            })
        });
        if (!res.ok) {
            const errData = await res.json().catch(() => ({}));
            const errMsg = errData.detail || errData.error || errData.message || `Máy chủ trả về mã lỗi HTTP ${res.status}`;
            throw new Error(errMsg);
        }
        return await res.json();
    },

    /**
     * Reads a background batch-evaluation job's status.
     * @param {string} jobId - Id returned by startEvaluationJob.
     * @returns {Promise<{state: string, total: number, completed: number, elapsed_seconds: number, result: ?Object, error: ?string}>}
     */
    async getEvaluationJob(jobId) {
        const res = await fetch(`/api/evaluate_batch/jobs/${encodeURIComponent(jobId)}`);
        if (!res.ok) {
            const errData = await res.json().catch(() => ({}));
            const errMsg = errData.detail || errData.error || errData.message || `Máy chủ trả về mã lỗi HTTP ${res.status}`;
            throw new Error(errMsg);
        }
        return await res.json();
    },

    /**
     * Fetches the expected duration in seconds per operation kind, learned from recent runs.
     * @returns {Promise<{expected_seconds: Object<string, number>}>}
     */
    async getExpectedDurations() {
        const res = await fetch('/api/durations');
        if (!res.ok) throw new Error('Không tải được thời lượng dự kiến của thao tác.');
        return await res.json();
    },

    /**
     * Decomposes HR job requirements into 5 RAG criteria dimensions and hr_rag.txt.
     * @param {string} stdReq - Standard job requirements text.
     * @param {string} hiddenReq - HR hidden / culture fit requirements text.
     * @param {string} [language='vietnamese'] - Output language.
     * @returns {Promise<Object>} Decomposed categories and hr_rag.txt content.
     */
    async decomposeRequirements(stdReq, hiddenReq, language = "vietnamese") {
        const res = await fetch('/api/rag/decompose', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                standard_requirements: stdReq,
                hidden_requirements: hiddenReq,
                language: language
            })
        });
        if (!res.ok) {
            const errData = await res.json().catch(() => ({}));
            const errMsg = errData.detail || errData.error || errData.message || `Máy chủ trả về mã lỗi HTTP ${res.status}`;
            throw new Error(errMsg);
        }
        return await res.json();
    },

    /**
     * Scrutinizes HR requirements for Implicit Assumptions, returning Clarification Questions
     * grouped by source field ('standard_requirements', 'hidden_requirements'). Ephemeral —
     * does not touch the RAG store.
     * @param {string} stdReq - Standard job requirements text.
     * @param {string} hiddenReq - HR hidden / culture fit requirements text.
     * @param {string} [language='vietnamese'] - Output language for clarification questions.
     * @returns {Promise<Object>} { standard_requirements: [{assumption, question}], hidden_requirements: [...] }
     */
    async scrutinizeRequirements(stdReq, hiddenReq, language = "vietnamese") {
        const res = await fetch('/api/rag/scrutinize', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                standard_requirements: stdReq,
                hidden_requirements: hiddenReq,
                language: language
            })
        });
        if (!res.ok) {
            const errData = await res.json().catch(() => ({}));
            const errMsg = errData.detail || errData.error || errData.message || `Máy chủ trả về mã lỗi HTTP ${res.status}`;
            throw new Error(errMsg);
        }
        return await res.json();
    },

    /**
     * Updates persistent RAG database with user-edited criteria across 5 dimensions.
     * @param {Object} categories - Map of category names to arrays of string criteria items.
     * @param {?string} [stdReq=null] - Standard requirements text; null keeps the stored original.
     * @param {?string} [hiddenReq=null] - Hidden requirements text; null keeps the stored original.
     * @returns {Promise<Object>} Updated RAG summary.
     */
    async updateRagCriteria(categories, stdReq = null, hiddenReq = null) {
        const res = await fetch('/api/rag/update', {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({
                categories: categories,
                standard_requirements: stdReq,
                hidden_requirements: hiddenReq
            })
        });
        if (!res.ok) {
            const errData = await res.json().catch(() => ({}));
            const errMsg = errData.detail || errData.error || errData.message || `Máy chủ trả về mã lỗi HTTP ${res.status}`;
            throw new Error(errMsg);
        }
        return await res.json();
    },

    /**
     * Fetches current RAG ChromaDB vector status and 5-dimension criteria breakdown.
     * @returns {Promise<Object>} RAG summary report object.
     */
    async getRagInfo() {
        const res = await fetch('/api/rag');
        if (!res.ok) throw new Error('Không tải được trạng thái cơ sở dữ liệu RAG.');
        return await res.json();
    },

    /**
     * Clears persistent local ChromaDB vector store.
     * @returns {Promise<Object>} Success status message.
     */
    async clearRagInfo() {
        const res = await fetch('/api/rag', { method: 'DELETE' });
        if (!res.ok) throw new Error('Không xóa được cơ sở dữ liệu RAG.');
        return await res.json();
    },

    /**
     * Retrieves secret evaluation tier email ordering metadata.
     * @returns {Promise<{tier1: Array<string>, tier2: Array<string>, file_found: boolean}>} Secret tier data.
     */
    async getEvaluationOrder() {
        const res = await fetch('/api/evaluation_order');
        if (!res.ok) throw new Error('Không tải được cấu hình thứ tự đánh giá.');
        return await res.json();
    },

    /**
     * Lists candidate evaluation reports stored in eval_results/.
     * @returns {Promise<{evaluations: Array<Object>}>} Array of candidate evaluation objects.
     */
    async getEvalResults() {
        const res = await fetch('/api/eval_results');
        if (!res.ok) throw new Error('Không tải được kết quả đánh giá ứng viên.');
        return await res.json();
    },

    /**
     * Retrieves full detail report JSON for a specific candidate evaluation.
     * @param {string} filename - Target evaluation report filename.
     * @returns {Promise<Object>} Full evaluation detail object.
     */
    async getEvalResultDetail(filename) {
        const res = await fetch(`/api/eval_results/${encodeURIComponent(filename)}`);
        if (!res.ok) throw new Error('Không tải được chi tiết đánh giá.');
        return await res.json();
    },

    /**
     * Deletes an evaluation report JSON file.
     * @param {string} filename - Target evaluation report filename to delete.
     * @returns {Promise<Object>} Operation success result.
     */
    async deleteEvalResult(filename) {
        const res = await fetch(`/api/eval_results/${encodeURIComponent(filename)}`, { method: 'DELETE' });
        if (!res.ok) throw new Error('Không xóa được kết quả đánh giá.');
        return await res.json();
    }
};
