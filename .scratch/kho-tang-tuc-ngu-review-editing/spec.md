Status: ready-for-agent

# Kho tàng tục ngữ người Việt: review page as an editor, not a checklist

Grilled 2026-10-31. Follows `.scratch/kho-tang-tuc-ngu-proverbs/` (issue 02, the review server; issue 03, the export). Vocabulary: `vsc-project/khoTangTucNguoiNguoiViet/GLOSSARY.md`.

## Problem Statement

The review page (`src/khotangtucngu/web/`) asks the developer to mark every Proverb Entry checked. With ~16 000 entries that will never happen. The right side is hard to read:
- Citations render as `,[object HTMLSpanElement]`;
- a Citation shows only its abbreviation, so you can't tell which of the 63 Sources it is, or whether it matched one at all;
- Warnings are stacked apart from their entries;
- every card carries two large buttons.

A Fix is raw JSON keyed by the model's entry name. That is ambiguous when the model prints a number twice (two "A 4"s on PDF pages 36 and 38), and it breaks when the Fix renumbers the entry. "VC I 11 bk VD" raises a false "Citation with no pages" Warning.

## Decisions

### No checking
- Remove the "Mark checked" and "Mark every entry on this page checked" buttons, `check` records, the "N of M checked" progress, the "unchecked" counts in the page picker, and the "next unchecked" jump (`u`).
- The progress line reads "N entries edited (M stale)". A "next edited" jump is added beside "next Warning".
- Old `check` lines in review.jsonl are ignored. There is no migration.

### A Fix is a page's corrected Blocks
- A Fix replaces the model's Blocks of one PDF page (and its `printed_page`). It records the answer hash of that page and is stale once the page's answer changes. A stale Fix is shown but not applied, until it is saved again or dropped (as today).
- Review record: `{"type": "fix", "page": <PDF page>, "answer_sha1": "<sha1>", "printed_page", "blocks": [...]}`, with `"blocks": null` to drop it. The latest record for a page wins. The Blocks have the shape of the model's answer (`kind`, `number`, `text`, `citations`).
- You still edit one entry at a time on the right. The editor holds that entry's Blocks on the current page, and saving splices them back into the page's Block list. An entry over a page break is edited on each page separately, as printed.
- An edit may change any Block's text, number or kind. It may add, delete or reorder Blocks: adding a proverb Block splits off a new entry, and deleting every Block removes an entry. The page's `printed_page` can be edited too, for the Page number Warning.

### Re-assembly from answers plus Fixes
- `cli.py` copies `assembly.py` and `citations.py` (standard library only; `assembly.py` must stop importing `src.providers.vlm_requests` or get its `sha1` another way) into the store beside `serve.py`.
- `serve.py` re-assembles from the answers plus the Fixes that are not stale. It serves the result, so the Warnings reflect the edits: renumbering A 4 → A 14 clears the "Duplicate number" and "Number gap" Warnings.
- `entries.json` stays the model's assembly, for the "as transcribed" view and the diff.
- `export.py` assembles the same way, from the answers plus the Fixes, instead of swapping in whole entries. `fixed` on a record means its Blocks on some page came from a Fix.

### Recording changes
- Every save is appended to review.jsonl with its time (as today). Nothing is rebuilt or deleted.
- An edited entry carries an "Edited" marker, an "as transcribed" toggle, and a word-level diff against the model's version.
- An "Edits" list shows every Fix of the Part (applied and stale), each linking to its page.
- There is no viewer for earlier versions of a Fix; the log keeps them.

### The edit form
- One row per Block:
  - a kind dropdown;
  - a number field (proverbs only);
  - one text field holding the printed text, with italics between `*asterisks*` and Citations typed as printed ("HT 63 NL 7 TNLG II 7, 25");
  - a second field for a Variant's Citations;
  - buttons to add, delete and move the row.
- A live preview underneath shows the entry as it would read, with its expanded Citations and any Warning the edit raises (the splitter's problems at least, computed by the server or a port of the split).
- No JSON editing.

### Citations expanded
- `cli.py` writes `sources.json` into the store, using the same code as `export.py`'s `sources()`: title, author, kind, year.
- Under each proverb and each Variant, the Citations are listed one per line: `VD · 12 — <title>, <author> (<year>)`. A Citation outside the 63 is shown in red as "not among the 63 Sources".

### Variant Citation ("bk")
- In a Citations text, a lowercase `bk` marks the one Citation right after it as a Variant Citation: `{"abbreviation": "VD", "pages": "", "variant": true}`. Pages are kept if printed ("bk VD 12").
- A Variant Citation with no pages raises no Warning. "VC I 11 bk VD" splits into VC I "11" and VD (bản khác), not VC I "11 bk".
- The review page and the website show it as "VD · bản khác (no page)".

### The right side
- Fix the bug: `h()` flattens its children only one level, so `citeLine()`'s nested `[" ", <span>]` arrays are appended as strings. Flatten fully.
- Lay each entry out as printed: proverb, the Citations line, BK and its Variants, notes, Sửa lại, Xem thêm, then the expanded Citations.
- A Warning sits only on the entry it concerns. Page-level Warnings (page number, missing page, Leading Block with no owner) stay as one compact strip at the top.
- The edit button appears on hover or focus of a card, not as a large button on every card.

### Not doing
- No bounding boxes and no highlighting on the scan. The schema stays without coordinates while the model transcribes well.

## Glossary changes (made)
- **Fix** is redefined as a PDF page's corrected Blocks, made where the developer sees something wrong.
- **Variant Citation** is added.

## Verification
By reasoning over the code (no tests, no browser), then the developer's own use of the page on a real store.
