# 03: Translate the whole web app into Vietnamese

**What to build:** Every page of the web app shows its fixed text in Vietnamese: the CV Extractor, HR Evaluator, RAG Workbench, Candidate Pool and the home page. That includes text added by tickets 01 and 02, such as the intake grid, the shared Criteria editor, the Workbench save and the waiting screen. Translation is direct, in place: no translation layer, dictionary or language toggle. See the "Vietnamese interface" section of the spec, `.scratch/hr-workbench-vietnamese-ux/spec.md`.

**Blocked by:** 01 (Clarify-once intake, full-width Criteria editor, and editable RAG Workbench) and 02 (Shared waiting screen with time estimates and live batch-evaluation progress). The translation runs after both so strings are translated once, in their final place.

**Status:** ready-for-agent

- [x] All fixed UI text on every page is in Vietnamese: headings, labels, buttons, placeholders, step names, table headers, tier titles, badges, empty and error states, `alert()` messages, and waiting-screen titles, descriptions and countdown text.
- [x] Placeholder examples in the requirement textareas are written in Vietnamese.
- [x] The five Category labels are Vietnamese only, with no English part, on both the Verify step and the RAG Workbench. The Category keys are unchanged.
- [x] Technical product names ("RAG", "ChromaDB", `hr_rag.txt`) are left untranslated.
- [x] Every page declares Vietnamese as its document language.
- [x] Every front-end call that accepts a `language` field (scrutiny, decomposition, extraction) sends `vietnamese` explicitly.
- [x] LLM prompt templates, logs, CLI output and files on disk are not translated.
- [x] No automated tests are added and no browser is driven. The implementer checks that no English UI strings remain by reasoning over the markup and controllers. The developer tests by hand.
