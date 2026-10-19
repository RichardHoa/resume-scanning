# Frontend fix plan (`src/static/`)

Comes from a strict code-quality review of the HTML, CSS and JS. Everything here is a proposal. Nothing has been changed yet.

## Ground rules for the agent doing this

- **Do not commit.** Leave every change uncommitted for the developer to review.
- **Do not add tests and do not open a browser.** Check each change by reading the code: follow every caller, ID and class name you touch.
- **No back-compat.** Old reports and RAG data are wiped whenever something changes, so delete fallbacks that exist only for old data. Don't add new ones.
- Bias runner, consistency scripts and DSPy are out of scope.
- **Keep behaviour the same unless an item says otherwise.** Items marked **BUG** change behaviour on purpose.
- Keep the existing style: ES modules, classes, JSDoc on non-trivial functions, and UI text in Vietnamese.
- Work through the phases in order. Each phase should leave the app working.

---

## Phase 1: Bugs and contradictions (small and safe)

### 1.1 BUG: `index.html` is dead, and it has the accessibility fixes the live page lacks
- `src/api/pages.py` `read_extractor()` serves `extractor.html` and falls back to `index.html` only if `extractor.html` is missing. So `index.html` is never served.
- `index.html` has accessibility fixes that `extractor.html` does not:
  - the skip link `<a href="#main-content" class="sr-only focus-not-sr-only">`;
  - `id="main-content"` on `<main>`;
  - `aria-hidden="true" focusable="false"` on decorative SVGs;
  - `tabindex="0" role="button" aria-label` on `#dropzone`;
  - `.browse-link` as a real `<button type="button">`;
  - `type="button"` on every button;
  - `role="tablist"`/`role="tab"`/`aria-selected`/`aria-controls`/`id` on the tab buttons;
  - the rail title as `<span class="brand-heading">` with the page title as `<h1>`.
- `index.html` **lacks** `#warning-banner`/`#warning-list`, which `extractor.js` `displayResults()` uses.
- **Do:**
  1. Copy all the accessibility changes above into `extractor.html`. Keep its warning banner.
  2. Move the inline styles on `.browse-link` into `.browse-link` in `page-extractor-upload.css`.
  3. Delete `index.html`.
  4. Remove the fallback from `read_extractor()` so it always serves `extractor.html`.
- Tab buttons use `aria-selected`, but `extractor.js` `initEvents` only toggles `.active`. Make the tab click also set `aria-selected` on every tab.
- The dropzone now has `role="button"`, so it needs a keyboard handler: Enter or Space calls `fileInput.click()`.

### 1.2 BUG: page titles lost their styling
- `evaluator.html`, `rag.html` and `candidates.html` use `<h1>` inside `.workbench-title-group`. After 1.1, `extractor.html` will too.
- `css/base.css:141` only styles `.workbench-title-group h2`.
- **Do:** change the selector to `.workbench-title-group h1`.
- Check the rail too: `navbar.css` `.rail-brand-title h1, .rail-brand-title .brand-heading`. After 1.1 no page uses an `h1` in the rail, so drop the `h1` part.

### 1.3 BUG: the Missing Position message tells HR the wrong thing
- `extractor.js:230-233` comments that a Missing Position "is never evaluated" and shows `'⚠️ Không tìm thấy vị trí ứng tuyển — CV này sẽ không được đánh giá'` ("this CV will not be evaluated").
- `candidates.js` and `evaluator.js` (`MISSING_POSITION_MESSAGE`) say it **is** still evaluated and ranked, with this job assumed. That is the real behaviour.
- **Do:**
  1. Fix the comment.
  2. Change the shown text to agree with the others, e.g. `'⚠️ Không tìm thấy vị trí ứng tuyển — hệ thống sẽ mặc định ứng viên ứng tuyển vị trí này'`.
  3. Once Phase 2 exists, use the shared `MISSING_POSITION_LABEL`/`MESSAGE`.
  4. Replace the inline `style.color = '#B91C1C'` with a modifier class.

### 1.4 BUG: match bands disagree with each other (fixed in Phase 2.2)
- Example: a report with `match_recommendation: 'LOW_MATCH'` and score 90.
  - `candidates.js` `matchPill` shows it as Strong.
  - `updateSummaryStats` counts it as Strong.
  - The status filter (`candidates.js:316-319`) lets it through **both** the STRONG_MATCH and LOW_MATCH filters.
- `evaluator.js` `renderDashboard` counts it as Low, because it uses only `match_recommendation`.
- The fix is in 2.2: the band is `match_recommendation`, with no score thresholds.

### 1.5 Delete stale header metadata
- Remove every `Line Count: ~N lines (Strict Limit: < 500 lines)` line from the JS file headers. They are wrong: `api.js` says ~100 lines but has 314, and `evaluator.js` admits it breaks its own limit.
- Remove mood words such as "(Harmonious Executive Light Theme)" and "(Fulbright Redesign Edition)" from the headers.

---

## Phase 2: Shared JS modules (large mechanical win)

### 2.1 New `js/modules/html.js`: one place for escaping
- Today `escapeHtml` is copied as a method into `candidates.js`, `evaluator.js`, `extractor.js` and `rag.js`. It doesn't escape `'`.
- Escaping is decided at each call site, and several sites miss it:
  - `evaluator.js:681` puts `data-file="${resItem.filename}"` into an attribute unescaped (the uploaded file name);
  - `rec-${res.match_recommendation}` is used as a class name unescaped;
  - `${recText}` and `${unscored}` go into `innerHTML`.
- **Do:** export:
  - `escapeHtml(value)`: escapes `& < > " '` and turns null/undefined into `''`.
  - `html` tagged template: escapes every `${}` value unless it is a `SafeHtml` (a tiny wrapper class). Arrays are joined, and each item is escaped unless it is `SafeHtml`. Returns `SafeHtml`.
  - `raw(str)`: wraps trusted markup, such as the constant `IMPORTANCE_HELP` strings that contain `<strong>`.
- Move each module to `html` step by step. At minimum, use the shared `escapeHtml` and delete all four method copies. Do 2.1 first so that 2.3 and 3.1 are written with `html` from the start.

### 2.2 New `js/modules/report.js`: the evaluation-report domain model
`candidates.js:14-176` and `evaluator.js:21-96` are near-duplicates. Each call site re-derives the same thing by combining `unscoredLabel()`, `isMustHaveRejection()` and `isScannedResume()`. The real model is one value, the report's **kind**.

```js
export const KIND = { RANKED: 'ranked', REJECTED: 'rejected', FAILED: 'failed', SCANNED: 'scanned' };

export function reportKind(r) {
  if (r.status === 'error') return KIND.FAILED;
  if (r.status === 'scanned') return KIND.SCANNED;
  if (r.match_recommendation === 'MUST_HAVE_REJECTED') return KIND.REJECTED;
  return KIND.RANKED;
}
```

**Move into it:**
- All label and message constants:
  - `FAILED_EVALUATION_LABEL`;
  - `SCANNED_RESUME_LABEL`/`_MESSAGE`;
  - `MISSING_POSITION_LABEL`/`_MESSAGE`;
  - `MUST_HAVE_REJECTION_LABEL`/`_MESSAGE`;
  - section titles: `REJECTED_SECTION_TITLE`, `SCANNED_SECTION_TITLE`;
  - `RECOMMENDATION_LABELS`.
- `isMissingPosition(r)`.
- `mustHaveMisses(r)`: the `must_have_rejection` list when the kind is REJECTED, otherwise `[]`.
- `isScored(r)`: kind is RANKED or REJECTED. This replaces `!unscoredLabel(r)`.
- `unscoredLabel(r)`: keep it, built on the kind.
- `shownCategories(r)` from `evaluator.js:94`. This replaces `isNotApplicableCategory` in `candidates.js`.
- `failedCategoryNames(r)`. Today it is computed in two places: `candidates.js:630` and `evaluator.js:942`.

**Match band (fixes 1.4).** There is one band per report:
```js
export function matchBand(r)  // 'STRONG_MATCH' | 'POTENTIAL_MATCH' | 'LOW_MATCH' | 'REJECT' | 'MUST_HAVE_REJECTED' | 'ERROR'
```
- For an unscored kind it returns `'ERROR'`. Otherwise it returns `r.match_recommendation`.
- **Delete every score-threshold fallback** (`score >= 85/70/55`). The server always writes `match_recommendation`, and old reports are wiped. The places to change:
  - `candidates.js` `matchPill` (line 107);
  - `updateSummaryStats` (270);
  - the filter (309-320);
  - `evaluator.js` KPI (795).
- The status filter becomes `matchBand(r) === filter`, plus `MUST_HAVE_REJECTED` also matching `REJECT`. That keeps today's rule that a Must-have Rejection is listed under "Loại".
- `recommendationLabel(r)` replaces `RECOMMENDATION_LABELS[rec] || rec`, and returns the unscored label for unscored kinds.

**Score band for numbers and bars (0-100):**
- `scoreBand(score)` returns `'high' | 'mid' | 'low' | 'reject'` using the 85/70/55 thresholds. Category scores and bar fills still need it, because category scores have no recommendation.
- Define it once. Today it is repeated in:
  - `candidates.js:466-471` (`fill-emerald…`);
  - `candidates.js:589-593` (`fill-high…`);
  - `candidates.js` `scoreColor` (hex values in JS).
- In CSS (Phase 4) it becomes one modifier class.

**Tiers and sections:**
- `tierLabels(tier, techMode)`. This replaces the copies in:
  - `candidates.js:127`;
  - `evaluator.js:642-650` (scanned list titles, which use slightly different wording);
  - `evaluator.js:808-815` (dashboard titles, which ignore techMode; that is a bug, so make them use techMode).
  - Settle on one wording.
- `tierRank(r)` from `candidates.js:140`. `evaluator.js:677` computes it again inline.
- `groupIntoSections(reports, techMode)` returns `[{key, title, badge, badgeClass, items}]` in display order: tier 1, 2, 3, then rejected, then scanned. Empty sections are dropped. Rules:
  - SCANNED goes to `scanned`;
  - REJECTED goes to `rejected`;
  - everything else goes to `tier || 3`.
- This replaces the hand-built dicts in `candidates.js:385-432` and `evaluator.js:808-829`.
- `evaluator.js` `renderScannedList` (the pre-evaluation resume list) uses only tiers 1-3, and its items are not reports. Use `tierLabels` there and leave the sections out.

**Identity:**
- `candidateIdentity(r)` from `candidates.js:166`. Simplify it now that old data is gone:
  - drop `cand.email`;
  - drop the `rawEmail === 'N/A'` check, unless the server still writes `'N/A'`; grep `src/` for it before deleting;
  - drop the `identifier.includes('@')` guess, unless the server needs it; check the same way.
- `evaluator.js` shows `res.candidate_email || res.candidate_identifier`. Switch it to `candidateIdentity`.

**Then** delete all of the above from `candidates.js` and `evaluator.js` and import them instead. Every `if (unscored) … else if (rejected) …` ladder should become a `switch (reportKind(r))` or a lookup.

### 2.3 `api.js`: one request helper
- The five-line `if (!res.ok) { errData … errMsg … throw }` block is pasted six times. Other methods throw a generic message and drop the server's `detail`.
- **Do:** add a private `async function request(url, init, fallbackMessage, as = 'json')`. It should:
  - throw `errData.detail || errData.error || errData.message || fallbackMessage || 'Máy chủ trả về mã lỗi HTTP ' + status`;
  - return `res.json()` or `res.blob()`.
- Add `postJson(url, body, fallback)` on top of it.
- Every method then becomes a single line that calls one of these. `extractCv` still needs the `X-Extraction-Time` header, so it can call `fetch` directly but should use the same error path.
- **Delete unused methods:** `evaluateBatch`, `getEvaluationOrder`. Grep `src/static` to confirm they are unused. `deleteEvalResult` looks unused in the JS too: confirm before deleting, and leave the server endpoint alone.
- **Remove parameters that never change:**
  - `startEvaluationJob(…, useExistingRag = false, language)`: the only caller passes `true, 'vietnamese'`. Hard-code `use_existing_rag: true, language: 'vietnamese'` in the body.
  - Do the same for `language` in `extractCv`, `decomposeRequirements` and `scrutinizeRequirements`. Every caller passes `'vietnamese'`.
- Fix the JSDoc on `evaluateBatch`/`startEvaluationJob`, which refer to each other.

### 2.4 DOM boilerplate: delete the null guards and use `hidden`
- **Null guards.** Every controller only runs on its own page, whose HTML contains the elements, yet there are about 80 `if (this.x) this.x.…` guards. They only hide mistyped IDs.
  - Add `export function byId(id)` in a new `js/modules/dom.js`. It throws `Error('Missing #' + id)` when the element is absent.
  - Use it in each `initDOMElements` and delete the guards.
- **Shared elements.** Elements that exist on only some pages, such as `#val-model`/`#val-mode` in `app.js`, which no page currently has, should stay optional or be deleted.
  - `fetchServerConfig` in `app.js` writes to `#val-model`/`#val-mode`. Grep the HTML: if no page has them, delete `fetchServerConfig` and `API.fetchConfig`.
- **Visibility.** Today it is `style.display = 'none' | 'block' | 'flex' | 'inline-flex'`, which forces the JS to know each element's layout. Use the `hidden` attribute instead:
  - in the HTML, replace `style="display: none;"` with `hidden`;
  - in base.css, add `[hidden] { display: none !important; }` so that component `display:` rules cannot override it;
  - in the JS, use `el.hidden = bool` / `el.toggleAttribute('hidden', bool)`.
- **Places to change:**
  - `goToStage`, which becomes a loop over `[stageReq, stageRagVerify, stageCandidates, stageResults]`;
  - `switchRagTab`;
  - scrutiny panel show/hide;
  - `updateUseExistingRagVisibility`;
  - extractor `handleFileSelect`/`resetFileInput`/`displayResults`/`resetView`/`toggleViewMode`;
  - `WaitingScreen` overlay and count;
  - the candidate modal;
  - `#candidate-detail-view`.
- **`updateSummaryStats`** (`candidates.js:291-296`) calls `getElementById` twice for each stat. Store the stat elements once in `initDOMElements`.

---

## Phase 3: Merge the two candidate detail views

### 3.1 New `js/modules/candidate-report-view.js`
- The evaluator's dossier inspector (`evaluator.js:914-1012`, `evaluator.html:308-352`) and the candidate-pool modal (`candidates.js:546-1031` plus `candidates.html:150-169`) show the same report.
- The evaluator copy is out of date. It lacks:
  - per-criterion verdicts;
  - Must-have tags and points;
  - Review Panel feedback;
  - HR Check Items;
  - PDF download;
  - resume view;
  - the developer panel.
- **Do:** move the modal into its own class, `CandidateReportView`. Give it:
  - `open(report, triggerEl)` and `close()`;
  - all the `render*` helpers;
  - the resume toggle, PDF download, developer-panel lazy load, focus restore and Escape/overlay-click close.
- **Markup:** the modal's markup (`#cand-detail-modal …`) is needed on both pages. Build it in JS when the view is created, or put it in the shared layout from Phase 5. Don't copy it into `evaluator.html`.
- **`candidates.js`:** keep the pool (stats, filter, sort, cards, sections) and call `this.reportView.open(cand, card)`. It should end up well under 500 lines.
- **`evaluator.js`:** the "Xem hồ sơ" button in `renderDashboard` calls `this.reportView.open(res, button)`.
  - Delete `renderCandidateDetail`.
  - Delete the auto-inspect-first logic (`inspectSet`).
  - Delete the dossier markup in `evaluator.html`.
  - Delete the `det-*` IDs and `dimensions-container`.
- **Backend change needed:** batch results (`src/api/evaluation.py` `_evaluate_single_candidate`, around lines 162-204) do **not** include `filename` or `has_resume_pdf`. `/api/eval_results` adds both in `list_eval_results`. The view needs them for the PDF and dev-details URLs.
  - Add `eval_result["filename"] = <basename of the saved report JSON>` and `eval_result["has_resume_pdf"] = find_resume_pdf(...) is not None` to the success path, matching `list_eval_results`.
  - Check how `evaluate_resume` names its output file in `EVALUATION_JSON_DIR` so that `filename` resolves through `find_eval_file`.
  - The error path returns `resume_name: fname` with `.json` and `match_recommendation: "ERROR"`. Leave `filename` unset there. The view already hides the PDF and dev buttons when `filename` is missing (`renderDevDetails` returns `''`, and `showModalResume` shows the missing message). The download button should also be hidden or disabled when there is no `filename`.

### 3.2 CSS that goes away after 3.1
- In `page-evaluator.css`, delete: `.dossier-*`, `.score-circle-outer`, `.score-number`, `.score-max`, `.executive-summary-box`, `.exec-summary-*`, `.strengths-gaps-split`, `.sg-*`, `.dimensions-grid`, `.dimension-card`, `.dim-header`, `.dim-score`, `.dim-progress-*`, `.dim-reasoning-box`, `.dim-list`.
- Before deleting, grep for each class to confirm that nothing else uses it.
- Rename `page-candidates-modal.css` to `components-candidate-report.css`, since it now serves two pages.

---

## Phase 4: CSS

### 4.1 One owner for each badge or pill component
All CSS loads on every page through `style.css`, so `page-*.css` is not page-scoped, and the import order quietly decides which duplicate wins:

| Selector | Copies | Today |
|---|---|---|
| `.tier-badge`, `.tier-badge-1..3` | `page-evaluator.css:275-305`, `page-candidates-pool.css:276-289` | Tier 1 is green in one copy and indigo in the other; the pool copy wins, but the evaluator's `gap`/`text-transform` leak into it |
| `.match-pill`, `.match-strong/potential/low/reject/error` | `components-buttons.css:160-202`, `page-candidates-pool.css:233-274` | Two palettes |
| `.dim-progress-track`, `.dim-progress-fill` | `page-evaluator.css:485-497`, `page-candidates-pool.css:342-353` | Height and radius merge by accident |

**Do:**
- Create `css/components-badges.css`, imported right after `components-buttons.css`.
- Move into it one copy each of:
  - `.match-pill` (also used as `.badge-rec`);
  - the band modifiers;
  - `.tier-badge` and its levels;
  - `.tier-rank-badge`;
  - `.badge-ocr-review` (rename it `.badge-warning`; it is not OCR-specific);
  - `.badge-success`;
  - the progress bar.
- Delete the other copies. For tier 1, keep the current visible result: indigo, which is the pool copy that wins today.
- **Merge the two band vocabularies** `.rec-STRONG_MATCH…` and `.match-strong…` into one, keyed by `matchBand()`. For example `.band-STRONG_MATCH`, or lowercase keys mapped in `report.js`. Keep `rec-MUST_HAVE_REJECTED` styled like REJECT.
  - `rag.js:85` uses `'badge-rec rec-LOW_MATCH'` only to get amber. Give it a semantic class such as `.badge-warning`.
- **Score colour.** Replace `scoreColor()` hex values in JS and the inline `style="color:…"` with `.score--high/mid/low/reject/muted`, and the fill classes with `.bar-fill--high/…`. The class comes from `scoreBand()`. Must-have Rejection and unscored scores use `--muted`.

### 4.2 Tokens
- `css/variables.css` has four alias layers (`--color-*`, `--brand-*`, `--accent-*`, `--bg-*`). **31 tokens are never used:** `--accent-*` (all of them), `--bg-input`, `--bg-reasoning`, `--border-hover`, `--brand-light-bg`, `--brand-sky`, `--brand-surface`, `--color-card-foreground`, `--color-muted`, `--color-on-*`, `--danger-glow/-light`, `--success-glow/-light`, `--warning-glow/-light`, `--header-height`, `--radius-xl`, `--shadow-glow`, `--transition-bounce`.
- Meanwhile about 240 hex literals are hard-coded in the component and page files.
- **Do:**
  1. Delete the unused tokens. Re-run the usage count (below) after each step.
  2. Pick one name per concept and rewrite the remaining aliases to it. For example, `--brand-legacy-blue` becomes `--color-primary` and `--brand-azure` becomes `--color-secondary`. Then delete the alias.
  3. Add band tokens: `--band-strong-bg/-fg/-border`, `--band-potential-*`, `--band-low-*`, `--band-reject-*`, `--band-neutral-*`, plus `--tier-1-*`, `--tier-2-*`, `--tier-3-*`, `--warning-*`. Use them in `components-badges.css`, the tier block borders and the stat or KPI number colours.
  4. Replace hex literals that already have a token, such as `#FFFFFF`, `#CBD5E1`, `#F8FAFC`, `#0F172A`, `#334155` and `#475569`.
- Token usage count:
  ```sh
  cd src/static && for v in $(grep -oE '^\s+--[a-z0-9-]+' css/variables.css | tr -d ' '); do echo "$(grep -rhoE "var\($v\)" css js *.html | wc -l) $v"; done | sort -n
  ```

### 4.3 Dead selectors to delete
- `page-rag.css`: `.rag-category-card`, `.rag-category-header`, `.rag-category-title`, `.rag-item-pill`.
- `page-evaluator.css`: `.eval-layout` (and its `@media` block), `.leaderboard-card`.
- `base.css`: `.icon-svg-lg`, `.text-success`, `.text-danger`, `.text-accent`.
- `components-criteria-editor.css`: `.criteria-col-head` and `.criteria-cell-label` each have several separate rule blocks (lines 77/139/149 and 78/207). Merge each into one block.
- After Phases 3-4, re-run the dead-class scan:
  ```sh
  cd src/static && python3 - <<'EOF'
  import re,glob,os
  css={}
  for f in sorted(glob.glob('css/*.css')):
      for m in re.finditer(r'\.([a-zA-Z][\w-]*)', re.sub(r'/\*.*?\*/','',open(f).read(),flags=re.S)):
          css.setdefault(m.group(1),set()).add(os.path.basename(f))
  src=''.join(open(f).read() for f in glob.glob('*.html')+glob.glob('js/**/*.js',recursive=True))
  for c,fs in sorted(css.items()):
      if not re.search(r'(?<![\w-])'+re.escape(c)+r'(?![\w-])',src): print(c, sorted(fs))
  EOF
  ```
  Classes built from a prefix, such as `rec-${…}`, `tier-${n}-block` and `fill-…`, show up as false positives. Check those by hand.

### 4.4 Inline styles to classes
- `evaluator.js` `renderScannedList`:
  - the order banner (`cssText` plus per-state background, border and colour, lines 624-638) becomes `.order-banner` with `.order-banner--active` and `.order-banner--missing`;
  - the tier block header styles (666-670) move into a class.
- `evaluator.js` `renderDashboard`: every `style="…"` in the table and header template moves into a class. For example, `.leaderboard-name`, `.leaderboard-email`, `.leaderboard-score`, `.leaderboard-score--muted`, `.leaderboard-tally`.
- `candidates.js`:
  - the empty state (373-379) uses the existing `.empty-state`/`.empty-icon` plus a modifier;
  - the tier count `<span style>` (424);
  - `tierBlock.style.gridColumn` (416) moves into `.cand-tier-block`.
- `extractor.js:351-352`: the project card inline styles move into `.proj-name`/`.proj-duration`/`.proj-desc`.
- HTML: move repeated inline styles into classes.
  - `rag.html:91-100` has the status-label `<span style>` three times.
  - Button rows such as `style="display:flex; gap…"` in `evaluator.html` 149, 203, 207, 260, 279 and `rag.html:78` become one `.action-row` (with a `--split` modifier for `space-between`).
  - The heading `style="margin…"` in the extractor tabs.
  - The rail `KHO VECTOR` value.

---

## Phase 5: HTML shell

### 5.1 One layout for all four pages
- The nav rail (about 40 lines with SVGs), the font links, the skip link and the loader overlay are copied verbatim into every page. The active link and `aria-current` are edited by hand in each copy.
- `Jinja2==3.1.6` is already in `requirements.txt`.
- **Do:**
  1. Add `src/static/templates/base.html` (or `src/templates/`) with blocks for `title`, `heading` (icon plus h1 plus description) and `content`. Use a variable `active_page` to set `.active`/`aria-current` in the rail loop.
  2. Turn each page into `{% extends "base.html" %}`.
  3. In `src/api/pages.py`, use `fastapi.templating.Jinja2Templates`. Each route passes `{"request": request, "active_page": "extractor"}`.
- **Loader overlay:** put it in the base, **without** per-page default title and description text, because `WaitingScreen` always sets both.
- **Candidate report modal:** after Phase 3 it is needed on candidates and evaluator. Put it in a `{% block modals %}` or a `{% include %}` used by both pages, or build it in JS (see 3.1). Choose one approach and use it on both pages.
- **Page detection:** set `<body data-page="{{ active_page }}">`.
  - Rewrite `app.js` `initCurrentPage` as a map: `{ extractor: () => new ExtractorController(), evaluator: …, rag: …, candidates: … }[document.body.dataset.page]?.()`.
  - Delete the ID probing (`dropzone || page-extractor`, …).
  - Have each controller call its own initial load in its constructor, as `EvaluatorController` already does with `checkExistingRag`. Then `app.js` doesn't need to know `loadScannedResumes`, `loadRagKnowledgeBase` or `loadCandidatePool`.

### 5.2 Smaller HTML fixes
- Add `type="button"` to every `<button>` that lacks it, e.g. `evaluator.html` `#btn-run-eval` and `#btn-modify-criteria`.
- Every SVG that is not decorative-hidden needs `aria-hidden="true" focusable="false"`. Several in `evaluator.html` lack it (lines 154, 209, 224, 265).
- `evaluator.html` stepped bar: `aria-current="step"` sits on step 1 and never moves. `updateStepIndicator` should move it to the active step.
- `candidates.html` sort `<select>`: `date_asc` is handled in JS but has no `<option>`. Either add the option or delete the `case`.
- `candidates.js:495` uses `onclick="event.stopPropagation()"` inline. Attach it with `addEventListener` like everything else.

---

## Phase 6: Smaller JS cleanups

- **`evaluator.js` `runEvaluation`** (724-766):
  - use `readRequirementText()` instead of repeating it;
  - collapse the second `try` and the nested `if`s into early returns.
- **`evaluator.js` `processRagSummaryData` and `saveModifiedCriteria`** both set `currentHrRagText` and the preview text.
  - Make one `setHrRagText(text)`.
  - `currentHrRagText` is written but never read: delete the field.
- **`evaluator.js` `updateActiveRagBanner`:** the "5 chiều" (5 dimensions) text is hard-coded. Use `Object.keys(CATEGORY_NAMES).length`, or drop the number.
- **`evaluator.js` `loadScannedResumes`:** `orderPath` is stored and never read. Delete it.
- **`renderDashboard` rank column:** Failed Evaluations get a rank number while Scanned and Rejected show `—`. Use `report.js`: only `KIND.RANKED` gets a rank. That is a small **behaviour fix**: failed reports are "never ranked" by definition.
- **`candidates.js` `applyCandidateFiltersAndSort`:** the sort comparator computes every key for both sides on every comparison (`candidateIdentity` twice, `new Date` twice, …). Use a `SORTERS = { score_desc: (a,b)=>…, … }` table that computes only what each sort needs. Keep the "unranked last" rule for the score sorts, using `KIND`.
- **Back-compat fallbacks to delete** (the data is wiped; confirm each against the server's report writer before removing):
  - `d.weight || 0.2`;
  - `d.category_name` fallback;
  - `tier_order !== undefined ? … : 9999`, and `< 9999` in `tierRank`;
  - "Reports saved before … render nothing" comments and their `|| []` guards, where the server always writes the field;
  - `criteria-editor.js` `setCategories` accepting plain-string criteria (`typeof it === 'object'` …), *if* `/api/rag` always returns `{text, importance}`. Check `src/providers/rag_engine.py` / `src/api/rag.py`. Update the file-header JSDoc and the `api.js` `updateRagCriteria` JSDoc to match.
- **`extractor.js` `renderParsedData`** (227-357): split it into `renderProfile`, `renderExperience`, `renderEducation`, `renderCertifications`, `renderSkills`, `renderProjects`, plus one `renderList(el, items, emptyText, renderItem)` helper. That removes the five copies of `innerHTML=''; if (!items.length) … else forEach`.
- **`extractor.js` `downloadJson`:** use a `Blob` plus `URL.createObjectURL`, as `candidates.js` `downloadModalReportPdf` does. Put one `downloadBlob(blob, filename)` in `dom.js` and use it in both places.
- **`rag.js` `clearRagDatabase`:** `const data =` is unused; drop it.

---

## How to check the work (by reading, not running)

After each phase:
1. **IDs.** Grep every `getElementById`/`byId`/`querySelector('#…')` in the JS and confirm the ID exists in the HTML (or template) of the page that controller runs on.
2. **Classes.** Grep every class you renamed or deleted across `css/`, `js/` and the HTML. Re-run the dead-class scan in 4.3.
3. **Imports.** Every `import { X }` resolves to an `export`, and no module still declares a local copy of something now in `report.js`/`html.js`/`dom.js`.
4. **Escaping.** Every value that reaches `innerHTML` either goes through `html`/`escapeHtml` or is a module constant.
5. **Visibility.** Each element whose `style.display` code you removed has a `hidden` attribute in its initial HTML where it used to be `display:none`.
6. **Size.** `wc -l src/static/js/modules/*.js`: no file over 500 lines.
7. Leave everything uncommitted. List the files changed and any item you skipped, with the reason.
