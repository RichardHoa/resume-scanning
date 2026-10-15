# Next step: Criterion Importance (must-have / standard / nice-to-have)

## Problem

Inside a Category, every Criterion counts the same. `validate_category_evaluation` in
`src/pipelines/evaluator_utils.py` scores a Category as the plain mean of its Verdicts
(STRONG_EVIDENCE = 1, PARTIAL_EVIDENCE = 0.5, NO_EVIDENCE = 0). In real hiring some requirements
matter far more than others. For example, in "Kỹ năng, Công cụ & Chuyên môn" (`technical_skills`), missing the core
language should cost much more than missing a minor tool.

HR already gets asked about this. The Clarification Question prompt (`src/prompts/evaluator_prompts.py`, the
"Force HR to decide importance" rule) asks HR whether each requirement is a must-have or a nice-to-have. But
decomposition stores each Criterion as a plain string, so HR's answer never reaches scoring.

Since ADR 0005, every evaluation runs against the HR RAG that HR set and reviewed on the website beforehand.
HR's review of the Criteria is therefore where Importance gets decided.

## Decisions (already made, do not re-open)

1. **Three Importance levels per Criterion**, each with a fixed weight. Do not use free numeric weights.

   | Importance   | Key            | Weight | Vietnamese label (UI) |
   |--------------|----------------|--------|-----------------------|
   | Must-have    | `must_have`    | 3      | Bắt buộc              |
   | Standard     | `standard`     | 2      | Tiêu chuẩn            |
   | Nice-to-have | `nice_to_have` | 1      | Ưu tiên (điểm cộng)   |

   Put the weights in `src/core/config.py` next to `DIMENSION_WEIGHTS`, e.g. `IMPORTANCE_WEIGHTS`, with
   `DEFAULT_IMPORTANCE = "standard"`.
2. **The Category score becomes a weighted mean:** `Σ(weight × verdict_score) / Σ(weight) × 100`. A Category
   whose Criteria are all Standard keeps exactly today's score.
3. **Importance is set per Criterion, not per Category.** HR Check Items have no Importance. They are never
   scored (ADR 0004).
4. **The decomposer proposes; HR decides.** The decomposer sets an Importance from HR's wording: "bắt buộc",
   "yêu cầu", "phải", "must", "required" → must-have; "ưu tiên", "là lợi thế", "điểm cộng", "preferred",
   "a plus", "nice to have" → nice-to-have; anything else → standard. HR changes it per Criterion in the
   criteria editor before evaluating.
5. **Criterion text stays verbatim (ADR 0003).** Importance is a separate field. It never changes the text.
6. **The evaluator LLM never sees or decides Importance.** It still gives one Verdict per Criterion exactly as
   now. Importance is applied only in the deterministic scoring code. This keeps the bias tests (Shuffle Kinds)
   unaffected.
7. **Missing Must-Have flag.** When a must-have Criterion gets NO_EVIDENCE, record it on the evaluation and
   show it to HR. This does **not** auto-reject the candidate, who is still ranked and gets Candidate Feedback.
   A PARTIAL_EVIDENCE on a must-have only costs weight and raises no flag. Do **not** add a score cap in this
   step.
8. **Backward compatibility:** a stored Criterion with no Importance (old HR RAG, old payloads, plain strings)
   reads as `standard`.

## Implementation steps

### 1. Storage: `src/providers/rag_engine.py`, `src/providers/rag_exporter.py`
- `ingest_decomposed_dict` accepts each item as either a plain string or `{"text": ..., "importance": ...}`.
  Store `importance` in the Chroma metadata and on the in-memory `doc_obj`. Use `standard` when it is missing
  or invalid, and leave it out for HR Check Items.
- `load_from_db` reads `importance` back from the metadata, defaulting to `standard`. The JSON fallback store
  carries it as well.
- Add a method returning `{criterion_text: importance}` for one Category, e.g.
  `get_importance_map(category)`. `retrieve()` keeps returning plain strings, so the bias runner
  (`src/bias/runner.py`) and the prompts are unchanged.
- `get_stored_rag_summary` (`rag_exporter.py`) already returns category items as `{text, type}`. Add
  `importance`.
- `export_hr_rag_file`: show the level next to each item in `hr_rag.txt`, e.g. `1. [BẮT BUỘC] ...`.

### 2. Decomposition: `src/prompts/evaluator_prompts.py`, `src/pipelines/evaluator_backend.py`
- In `get_requirements_decomposition_system_prompt`, change the JSON shape for the 5 Categories to a list of
  `{"text": "<exact verbatim requirement>", "importance": "must_have|standard|nice_to_have"}`, and add the
  wording rules from decision 4. `hr_check_items` stays a list of strings. Keep every verbatim directive.
- `decompose_requirements_with_llm` (around line 104 in `evaluator_backend.py`) currently normalises each
  Category to a list of strings. It must accept both objects and plain strings (plain → `standard`), and it
  must keep the header-parsing fallback working (that fallback gives `standard`).

### 3. Scoring: `src/pipelines/evaluator_utils.py`, `src/pipelines/evaluator.py`
- `validate_category_evaluation(parsed, importance_map=None)` gives each criterion its weight. To find a
  criterion's Importance, match the LLM's echoed `criterion` text against `importance_map`:
  1. exact match after stripping whitespace and normalising case;
  2. otherwise the closest key by `difflib.SequenceMatcher` ratio when ≥ 0.85;
  3. otherwise `standard`.

  Do not match by position, because the Criteria Permutation bias test reorders the Criteria.
- Write `importance` onto each entry of `cleaned_criteria`. The `score` per criterion stays the Verdict value.
- Find every caller of `validate_category_evaluation`. `evaluate_category` in `evaluator.py` /
  `evaluator_backend.py` is the main one. Pass it the map from `self.rag.get_importance_map(cat_key)`. Callers
  without a map (e.g. DSPy, mocks) keep today's unweighted behaviour.
- The median-of-runs logic in `_evaluate_single_category` is unchanged.

### 4. Missing Must-Have flag
- In `evaluate_resume` (`src/pipelines/evaluator.py`), after aggregation, collect every Criterion across the
  Categories with `importance == "must_have"` and `verdict == "NO_EVIDENCE"` from the reported
  `criteria_evaluations`. Store them as `"missing_must_haves": [{"category": ..., "criterion": ...}]` on the
  evaluation output. Store an empty list when there are none.
- Review Panel (`src/pipelines/review_panel.py`, `src/prompts/review_panel_prompts.py`): give the Panelists the
  list so a missing must-have shows up among the weaknesses.
- `src/cli/backfill_feedback.py`: older reports have no `missing_must_haves`. Treat that as an empty list.

### 5. API: `src/api/rag.py`
- `UpdateRagCriteriaRequest.categories` becomes `Dict[str, List[Union[str, CriterionItem]]]`, where
  `CriterionItem` is a pydantic model `{text: str, importance: Literal["must_have","standard","nice_to_have"] = "standard"}`.
  Plain strings must still be accepted.
- `GET /api/rag` and `POST /api/rag/decompose` return items with `importance` (through the summary).

### 6. Criteria editor UI: `src/static/js/modules/criteria-editor.js`, `src/static/css/components-criteria-editor.css`
- Hold items as `{text, importance}` internally. `setCategories` accepts strings or objects (strings →
  `standard`). `getCategories()` returns `{category_key: [{text, importance}]}`. `getHrCheckItems()` stays a
  list of strings.
- On each Criterion row in the five Category cards (not the HR Check Items card), add an Importance
  control. Use a compact 3-option segmented control (`Bắt buộc` / `Tiêu chuẩn` / `Ưu tiên`), or a `<select>`
  styled like the existing `.criteria-item-move`, whichever fits the row. Add `aria-label="Mức độ quan trọng"`.
  Colour the must-have state distinctly (the design system is in `design-system/fulbright-resume-matrix/MASTER.md`;
  use its tokens from `src/static/css/variables.css`, not raw colours).
- New Criteria added through the add box start as `standard`.
- Moving a Criterion to another Category keeps its Importance. Moving it to the HR Check Items drops it;
  moving it back gives `standard`.
- Add a short line under each Category card header explaining the levels, e.g. "Bắt buộc ×3 · Tiêu chuẩn ×2 ·
  Ưu tiên ×1 trong điểm của chiều này". The UI copy is Vietnamese.
- Callers: `src/static/js/modules/evaluator.js` (~line 505) and `src/static/js/modules/rag.js` (~line 107) pass
  `getCategories()` to `API.updateRagCriteria` in `src/static/js/modules/api.js` (~line 192). Check that the new
  item shape goes through unchanged, and update the editor's header comment.

### 7. Showing results: `src/static/js/modules/candidates.js`, `src/reports/candidate_report.py`
- In the candidate modal's met / not-met criterion lists (~lines 647–670), tag must-have Criteria (e.g. a small
  "Bắt buộc" tag like the existing `modal-partial-tag`).
- Show `missing_must_haves` prominently in the candidate modal, and as a marker on the candidate's card in the
  pool. Text e.g. "Thiếu yêu cầu bắt buộc: …". Do the same in the PDF candidate report.
- Older evaluations have no `importance` / `missing_must_haves`. Render them as today.

### 8. Docs
- `CONTEXT.md`: add **Importance** (the per-Criterion level and its weight, set by HR in the HR RAG; _Avoid_:
  priority, weight (alone)) and **Missing Must-Have** (the flag: informs HR and never rejects; _Avoid_:
  dealbreaker, auto-reject). Update **Criterion** and **HR RAG** to mention Importance.
- Add ADR `docs/adr/0006-criterion-importance.md`. Cover the decisions above and the rejected options:
  - LLM-assigned numeric weights: unstable, and HR can't review them.
  - The evaluator judging importance per candidate: a single decision per job belongs at decomposition (same
    argument as ADR 0004).
  - Bonus-only nice-to-haves: breaks the 0–100 scale and the `MATCH_THRESHOLDS`.
  - Auto-reject on a missing must-have: resumes omit things, so HR decides.

## Out of scope (possible later steps)
- Score cap: the overall match can't reach STRONG while a must-have is missing.
- HR-adjustable Category weights (`DIMENSION_WEIGHTS`, currently fixed 22/22/22/22/12) in the criteria editor.
- Carrying HR's replies to the Clarification Questions straight into Importance. For now, HR applies them by
  editing the levels in the criteria editor.

## Done when
- A Category with Criteria of mixed Importance scores as the weighted mean. Example: one must-have STRONG
  plus one nice-to-have NO_EVIDENCE gives 75 (3 / 4 × 100). An all-Standard Category scores the same as before.
- HR can see and change each Criterion's Importance in the criteria editor (Verify step and RAG page). The
  choice survives saving and reloading the RAG page, and appears in `hr_rag.txt`.
- An old HR RAG, or a plain-string payload, still loads and evaluates, with every Criterion `standard`.
- A must-have with NO_EVIDENCE appears in `missing_must_haves`, in the candidate modal / card / PDF report and
  in the Review Panel's input. The candidate is still ranked.
- The batch CLI (`src/cli/evaluate.py`) and the bias / consistency scripts run unchanged against an HR RAG with
  Importance set.

## Project rules for the implementer
- Do not add tests and do not check things in a browser. Verify by reasoning through the code paths (and
  `python3 -m py_compile` / `bash -n` for syntax).
- Never run `git commit`. Leave the changes uncommitted for the developers.
- Never add pip auto-install steps; new dependencies go only in `requirements.txt` (none should be needed:
  `difflib` is in the standard library).
- `evaluation_order.txt` and `hr-requirement.txt` exist only on the compute machine. Their absence locally is
  expected.
