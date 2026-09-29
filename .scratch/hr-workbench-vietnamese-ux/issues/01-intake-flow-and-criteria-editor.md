# 01: Clarify-once intake, full-width Criteria editor, and editable RAG Workbench

**What to build:**

- **Clarify-once intake.** On the HR Evaluator, Clarification Questions are asked once per pass through requirement intake. They appear side by side with the field they refer to: Standard next to Standard, Hidden next to Hidden. After they appear, a single Decompose button moves on.
- **"Use Active RAG" hides while HR types.** The button hides as soon as HR types requirement text.
- **Full-width Criteria editor.** The Verify step and the RAG Workbench share one Criteria editor with full-width, wrapping Category cards.
- **Editable Workbench.** HR can edit, add and delete Criteria on the RAG Workbench and save them back to the RAG. Saving keeps HR's original Standard and Hidden Requirements text in `hr_rag.txt`.

Waiting screens and time estimates are ticket 02. This ticket keeps the existing loader overlay wherever it waits. New UI text may be written in English; ticket 03 translates it.

Spec: `.scratch/hr-workbench-vietnamese-ux/spec.md`. See the sections "Clarify-once intake state", "Use Active RAG visibility", "Side-by-side intake layout", "Stored original requirements" and "Shared Criteria editor".

**Blocked by:** None (can start immediately)

**Status:** ready-for-agent

## Stored original requirements (server)
- [ ] Ingesting criteria (decomposition or manual update) stores HR's original Standard and Hidden Requirements text alongside the RAG, and the RAG info endpoint returns it.
- [ ] The RAG update endpoint accepts requests without requirement text and then reuses the stored originals for `hr_rag.txt`. When requirement text is provided, it replaces the stored originals.
- [ ] Clearing the RAG clears the stored originals.

## Requirement intake
- [ ] The clarification check runs on the first Decompose of a pass.
- [ ] If the check finds no Implicit Assumptions, decomposition proceeds immediately.
- [ ] While Clarification Questions are showing, only the panel's Decompose button is visible. It decomposes the current text directly, even if HR edited it, without a second check.
- [ ] After returning from Category review, the check runs again only if the requirement text changed since it was last checked. Otherwise Decompose goes straight to decomposition.
- [ ] "Use Active RAG & Skip" is visible only when the RAG has stored Criteria and both textareas are empty. It updates live as HR types.
- [ ] Once questions exist, the intake panel shows a two-row grid:
  - Each row has a field's textarea on the left and that field's Clarification Questions (with their Implicit Assumptions) on the right.
  - A field with no questions shows a "no questions" note.
  - Before any questions exist, the panel stays single-column.
  - On narrow screens, each field's questions stack under its textarea.

## Criteria editor and Workbench
- [ ] The Category-card editor is a shared front-end module used by both the Verify step and the RAG Workbench.
  - Cards are stacked full-width, one per row, each with an item count.
  - Each Criterion is an auto-growing, wrapping textarea, and Enter does not insert newlines.
  - Add and delete work in every Category.
- [ ] The RAG Workbench:
  - uses the shared editor;
  - no longer shows the `[type]` tag;
  - has a single "Save to RAG" button that saves the whole set without sending requirement text, then refreshes the summary, item count and `hr_rag.txt` preview. The original requirement text in `hr_rag.txt` is preserved.
- [ ] Criteria edited on the Workbench are what the HR Evaluator loads through "Use Active RAG".

## Verification
- [ ] No automated tests are added and no browser is driven. The implementer checks the logic above by reasoning through the code paths. The developer tests by hand.
