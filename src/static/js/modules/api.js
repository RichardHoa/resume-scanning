/**
 * ==============================================================================
 * Centralized REST API Service Wrapper
 * ==============================================================================
 * Description: Provides async helper methods for communicating with FastAPI
 *              backend endpoints (PDF extraction, evaluation batch jobs,
 *              RAG vector status, candidate pool records, and developer details).
 *              Every failed request throws the server's own message when it sent one.
 */

/**
 * The Error for a failed response: the server's detail/error/message, else the fallback, else the HTTP status.
 * @param {Response} res
 * @param {string} [fallbackMessage]
 * @returns {Promise<Error>}
 */
async function responseError(res, fallbackMessage) {
    const errData = await res.json().catch(() => ({}));
    return new Error(errData.detail || errData.error || errData.message || fallbackMessage || `Máy chủ trả về mã lỗi HTTP ${res.status}`);
}

/**
 * Fetches a URL and reads the body, throwing responseError on a non-2xx status.
 * @param {string} url
 * @param {RequestInit} [init]
 * @param {string} [fallbackMessage] - Shown when the server gives no message.
 * @param {'json'|'blob'} [as='json'] - How to read the body.
 */
async function request(url, init, fallbackMessage, as = 'json') {
    const res = await fetch(url, init);
    if (!res.ok) throw await responseError(res, fallbackMessage);
    return as === 'blob' ? res.blob() : res.json();
}

/** POSTs a JSON body and reads the JSON reply. */
function postJson(url, body, fallbackMessage) {
    return request(url, {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body)
    }, fallbackMessage);
}

export const API = {
    /**
     * Uploads a candidate PDF resume file to start AI layout extraction (Vietnamese output).
     * @param {File} file - PDF resume file object.
     * @returns {Promise<{data: Object, extractionTime: string|null}>} Extracted JSON & execution time header.
     */
    async extractCv(file) {
        const formData = new FormData();
        formData.append('file', file);
        formData.append('language', 'vietnamese');
        // Read directly rather than through request(): the timing header is needed too
        const res = await fetch('/api/extract', { method: 'POST', body: formData });
        if (!res.ok) throw await responseError(res, 'Trích xuất thất bại.');
        return { data: await res.json(), extractionTime: res.headers.get('X-Extraction-Time') };
    },

    /**
     * Retrieves list of scanned resumes available in approved_jsons/ and output_jsons/.
     * @returns {Promise<{resumes: Array<Object>}>} Array of candidate summary objects.
     */
    getScannedResumes() {
        return request('/api/scanned_resumes', undefined, 'Không tải được danh sách CV đã quét.');
    },

    /**
     * Starts a batch evaluation of the selected resumes against the verified RAG criteria, as a background job.
     * @param {string} stdReq - Standard job requirements text.
     * @param {string} hiddenReq - HR hidden / culture fit requirements text.
     * @param {Array<string>} filenames - Candidate JSON filenames to evaluate.
     * @returns {Promise<{job_id: string}>} Id of the started job.
     */
    startEvaluationJob(stdReq, hiddenReq, filenames) {
        return postJson('/api/evaluate_batch/jobs', {
            standard_requirements: stdReq,
            hidden_requirements: hiddenReq,
            resume_filenames: filenames,
            use_existing_rag: true,
            language: 'vietnamese'
        });
    },

    /**
     * Reads a background batch-evaluation job's status.
     * @param {string} jobId - Id returned by startEvaluationJob.
     * @returns {Promise<{state: string, total: number, completed: number, elapsed_seconds: number, result: ?Object, error: ?string}>}
     */
    getEvaluationJob(jobId) {
        return request(`/api/evaluate_batch/jobs/${encodeURIComponent(jobId)}`);
    },

    /**
     * Fetches the expected duration in seconds per operation kind, learned from recent runs.
     * @returns {Promise<{expected_seconds: Object<string, number>}>}
     */
    getExpectedDurations() {
        return request('/api/durations', undefined, 'Không tải được thời lượng dự kiến của thao tác.');
    },

    /**
     * Decomposes HR job requirements into the 5 RAG Categories and hr_rag.txt (Vietnamese output).
     * @param {string} stdReq - Standard job requirements text.
     * @param {string} hiddenReq - HR hidden / culture fit requirements text.
     * @returns {Promise<Object>} Decomposed categories and hr_rag.txt content.
     */
    decomposeRequirements(stdReq, hiddenReq) {
        return postJson('/api/rag/decompose', {
            standard_requirements: stdReq,
            hidden_requirements: hiddenReq,
            language: 'vietnamese'
        });
    },

    /**
     * Scrutinizes HR requirements for Implicit Assumptions, returning Vietnamese Clarification Questions
     * grouped by source field ('standard_requirements', 'hidden_requirements'). Ephemeral —
     * does not touch the RAG store.
     * @param {string} stdReq - Standard job requirements text.
     * @param {string} hiddenReq - HR hidden / culture fit requirements text.
     * @returns {Promise<Object>} { standard_requirements: [{assumption, question}], hidden_requirements: [...] }
     */
    scrutinizeRequirements(stdReq, hiddenReq) {
        return postJson('/api/rag/scrutinize', {
            standard_requirements: stdReq,
            hidden_requirements: hiddenReq,
            language: 'vietnamese'
        });
    },

    /**
     * Updates persistent RAG database with user-edited criteria across 5 dimensions.
     * @param {Object} categories - Map of category names to arrays of Criteria, each {text, importance}.
     * @param {Array<string>} hrCheckItems - HR Check Items: requirements no resume would show, never scored.
     * @param {?string} [stdReq=null] - Standard requirements text; null keeps the stored original.
     * @param {?string} [hiddenReq=null] - Hidden requirements text; null keeps the stored original.
     * @returns {Promise<Object>} Updated RAG summary.
     */
    updateRagCriteria(categories, hrCheckItems, stdReq = null, hiddenReq = null) {
        return postJson('/api/rag/update', {
            categories: categories,
            hr_check_items: hrCheckItems,
            standard_requirements: stdReq,
            hidden_requirements: hiddenReq
        });
    },

    /**
     * Fetches current RAG ChromaDB vector status and 5-dimension criteria breakdown.
     * @returns {Promise<Object>} RAG summary report object.
     */
    getRagInfo() {
        return request('/api/rag', undefined, 'Không tải được trạng thái cơ sở dữ liệu RAG.');
    },

    /**
     * Clears persistent local ChromaDB vector store.
     * @returns {Promise<Object>} Success status message.
     */
    clearRagInfo() {
        return request('/api/rag', { method: 'DELETE' }, 'Không xóa được cơ sở dữ liệu RAG.');
    },

    /**
     * Lists candidate evaluation reports stored in eval_results/.
     * @returns {Promise<{evaluations: Array<Object>}>} Array of candidate evaluation objects.
     */
    getEvalResults() {
        return request('/api/eval_results', undefined, 'Không tải được kết quả đánh giá ứng viên.');
    },

    /**
     * URL of the candidate's original resume PDF, served inline.
     * @param {string} filename - Evaluation report filename.
     * @returns {string} The PDF URL.
     */
    resumePdfUrl(filename) {
        return `/api/eval_results/${encodeURIComponent(filename)}/resume_pdf`;
    },

    /**
     * Developer views of the files behind an evaluation, each opened raw in a new tab.
     * @param {string} filename - Evaluation result file name.
     * @returns {{resumeJson: string, resumeMarkdown: string, evalJson: string}} URLs of the extracted resume JSON,
     *          the extraction markdown and the evaluation report JSON.
     */
    devFileUrls(filename) {
        const base = `/api/eval_results/${encodeURIComponent(filename)}`;
        return { resumeJson: `${base}/resume_json`, resumeMarkdown: `${base}/resume_markdown`, evalJson: base };
    },

    /**
     * Developer details of one evaluated resume: everything its run folder holds for it.
     * @param {string} filename - Evaluation result file name.
     * @returns {Promise<Object>} run_folder, extraction_markdown, extraction_json, evaluation_json,
     *          prompt_logs (grouped by step, then category) and token_usage.
     */
    getDevDetails(filename) {
        return request(`/api/eval_results/${encodeURIComponent(filename)}/dev_details`, undefined, 'Không tải được chi tiết cho nhà phát triển.');
    },

    /**
     * Builds the evaluation report PDF (with the resume PDF appended when stored).
     * @param {string} filename - Evaluation report filename.
     * @returns {Promise<Blob>} The PDF file.
     */
    getReportPdf(filename) {
        return request(`/api/eval_results/${encodeURIComponent(filename)}/report_pdf`, undefined, 'Không tạo được báo cáo PDF.', 'blob');
    }
};
