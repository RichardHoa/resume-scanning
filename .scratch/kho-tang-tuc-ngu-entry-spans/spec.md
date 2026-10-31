Status: ready-for-agent

# Kho tàng tục ngữ người Việt: read each page one Entry Span at a time

Grilled 2026-10-31. Changes `.scratch/kho-tang-tuc-ngu-proverbs/` ("One request per PDF page", "no layout pass") and adds to the review server of `.scratch/kho-tang-tuc-ngu-review-editing/`. Vocabulary: `vsc-project/khoTangTucNguoiNguoiViet/GLOSSARY.md` (new: Line Number, Entry Span). Decision record: `vsc-project/khoTangTucNguoiNguoiViet/docs/adr/0001-entry-spans-from-numbered-lines.md`.

## Problem Statement

The pipeline sends the vision model a whole PDF page and asks it to copy every Proverb Entry on it as Blocks in one answer: about a dozen entries, with their Citations, Variants, notes, Corrections and See-alsos. That is a lot to read in one pass, and a misread digit ("A 4" for "A 14" on PDF page 38) or a dropped entry is easy to make among so much text. The developer wants the model to find where each entry is first, then read each entry on its own, zoomed in, and wants to see in the review server how the model split each page.

## Solution

Each PDF page is read in two steps.

1. **Layout.** Code finds the printed lines of the page and writes a red Line Number ("L1", "L2", ...) beside each, in a white strip added on the right of the page. The model sees this numbered page and answers the printed book page number, the first line below the Running Head, and the Line Number where each Proverb Entry and each letter heading starts.
2. **Entry Spans.** Code cuts the page at those lines into Entry Spans: from one start line to the line before the next. Lines between the Running Head and the first start are the page's Leading span. Each Entry Span is cut from the 300 dpi scan with a generous margin and copied as Blocks in its own request, under the same copying rules as today.

The Blocks of a page's Entry Spans, joined in order, with the layout's printed page number, make the same page answer as now. Assembly, Fixes, Warnings and the review server's entries work unchanged. The review server also draws each Entry Span's rectangle on the scan, and can show the numbered page the model saw.

Every request's first attempt is at temperature 0.

## User Stories

1. As the developer, I want each page split into Entry Spans by the model, so that each Proverb Entry is read on its own instead of among a dozen others.
2. As the developer, I want the model to place the splits by reading printed Line Numbers, not by guessing pixel coordinates, so that a cut never falls inside a line.
3. As the developer, I want code to find only lines of ink and never decide where an entry begins, so that the varied layouts of entries (indented Variants, long notes, Leading Blocks) are judged by the model.
4. As the developer, I want the Line Numbers drawn in red in a white strip on the right, so that they are never confused with the printed entry numbers on the left.
5. As the developer, I want a short tick from each Line Number to its line, so that the model sees which line each label names.
6. As the developer, I want the layout page sent whole at 300 dpi, so that the model sees the bold entry numbers and Line Numbers sharply.
7. As the developer, I want the Running Head's lines numbered too and the model to name the first line below it, so that code drops the Running Head without guessing its height.
8. As the developer, I want the layout request to give the printed book page number, so that it is read from the whole page, since no Entry Span shows the Running Head.
9. As the developer, I want every line below the Running Head to fall in exactly one Entry Span, so that no text is dropped and none is copied twice.
10. As the developer, I want each letter heading to start its own Entry Span, copied as a `letter` Block, so that a letter is never merged into a proverb.
11. As the developer, I want the lines above the first start line to be the page's Leading span, so that a Leading Block continuing the previous page is still copied.
12. As the developer, I want the Leading span's request told that it continues the last Proverb Entry of the page before and holds no proverb, so that the model does not invent a `proverb` Block for it.
13. As the developer, I want a missed start line to make one Entry Span of two Proverb Entries that is still copied whole, so that a layout mistake costs zoom, not text.
14. As the developer, I want an Entry Span's crop to reach across the whole gap above and below it, to just short of the neighbouring line's ink, so that tone marks and dots under letters are never clipped and no neighbour's letters come in.
15. As the developer, I want an Entry Span's crop to reach well past the furthest ink of the page's lines on the left and right, so that indented Variants and long Citation lines are never cut off.
16. As the developer, I want each Entry Span cut from the 300 dpi grayscale scan, so that it is read at the detail the page is read at today.
17. As the developer, I want a tall Entry Span sent whole, not cut into Strips, so that an entry is always read in one piece.
18. As the developer, I want the page answer to keep its shape (printed page number, Blocks in reading order), so that assembly, Fixes, stale marking and the review server's entries need no change.
19. As the developer, I want a layout answer whose start lines are outside the page's lines, not increasing, or above the first line below the Running Head treated as a failed request and retried, so that a bad split is never used.
20. As the developer, I want a page with no answer if any of its Entry Spans' requests fails on every attempt, with a missing-page Warning naming that Entry Span, so that a page is never assembled with a hole in it.
21. As the developer, I want a Warning on a page where the line finder sees ink outside every line it found, so that faint text the line finder missed is not lost silently.
22. As the developer, I want every request's first attempt at temperature 0, so that the answers are as repeatable as the model allows.
23. As the developer, I want retries to sample at the existing retry temperature, so that a retry does not fail the same way as the identical first attempt.
24. As the developer, I want the layout request capped at 512 tokens and each Entry Span request at 2048, so that a runaway answer stops early.
25. As the developer, I want the layout answers and the Entry Span answers saved in the store and stamped like today's page answers, so that a rerun only redoes what is missing, failed or made from other input.
26. As the developer, I want an Entry Span's answer stamped with its start and end lines and its crop, so that it is redone when the layout answer changes.
27. As the developer, I want the old whole-page answers redone, not migrated, so that the store holds one kind of answer.
28. As the developer, I want the numbered layout image of each page saved in the store, so that I can see exactly what the model was shown.
29. As the developer, I want each Entry Span drawn as a rectangle on the page scan in the review server, exactly as cropped, so that I see how the model split the page.
30. As the developer, I want each rectangle labelled with its start Line Number and what it became (the entry's name such as "A 14", "Leading", or the letter), so that I can match a span to its entry.
31. As the developer, I want proverb Entry Spans, the Leading span and letter-heading spans in different colours, so that I tell them apart at a glance.
32. As the developer, I want to turn the Entry Span rectangles on and off, on by default, so that they don't hide the scan when I read it.
33. As the developer, I want to switch the scan for the numbered layout image, so that I check the model's start lines against the labels it read.
34. As the developer, I want the rectangles placed as fractions of the page, so that they scale with the page image in the review server.
35. As the developer, I want the rectangles to keep showing the model's spans when a page has a Fix, so that I always see how the model read the page.
36. As the developer, I want the dry run to count the prompt tokens of the layout requests, so that I check the numbered 300 dpi page fits the context window before a run.
37. As the developer, I want the end-of-run summary to count the layout and Entry Span requests apart, so that I see where time and tokens went.
38. As the developer, I want the line finder shared with Nữ Giới Chung, so that the two pipelines depend on shared infrastructure, not on each other.
39. As the developer, I want Nữ Giới Chung to behave exactly as before after the line finder moves, so that its transcriptions don't change.

## Implementation Decisions

- **Shared line finder.** Nữ Giới Chung's printed-line finder (ink bands, tone marks and under-dots merged into their line, touching lines cut at valleys, rules ignored) and the helpers it needs move into the shared page-image module. Nữ Giới Chung imports them from there, unchanged in behaviour. Kho tàng tục ngữ runs it over the whole page.
- **Layout image.** The page at 300 dpi, in colour for this request only. A white strip is added on the right; each found line gets a red "L<n>" label in it, numbered from 1 at the top, with a short tick to the line's right end. The Running Head's lines are numbered like any other.
- **Layout request and schema.** One per PDF page. It answers `printed_page` (string, "" if none printed), `body_start` (the Line Number of the first line below the Running Head) and `starts`: the Line Numbers where each Proverb Entry or letter heading begins, in order. The prompt explains what a Proverb Entry's start looks like (its printed number and bold proverb, or a letter heading in a shaded box), that Citations, Variants, notes, Corrections and See-alsos belong to the entry above them, and that lines above the first start are a Leading span. Max tokens 512.
- **Layout check.** A layout answer is invalid, and treated as a failed attempt and retried, if a start is outside 1…N, the starts do not increase, or `body_start` is after the first start. Lines from `body_start` to the line before the first start, if any, are the Leading span.
- **Entry Span crop.** From the scan at 300 dpi grayscale. Top edge: 2 px below the bottom of the line above the span's first line; at `body_start`, no further up than half the side margin (30 px) above it, so the Running Head's rule stays out; 60 px above line 1 when it starts a span. Bottom edge: 2 px above the top of the line after its last line, or 60 px below the last line of the page. Left and right: 60 px beyond the furthest ink of any found line on the page, held inside the page.
- **Entry Span request.** One per Entry Span, with the same copying rules and Block schema as today's page request, reworded for one Entry Span: it may be one Proverb Entry, a letter heading, or (rarely) two entries. The Leading span's user text says it continues the last Proverb Entry of the page before and has no proverb. Max tokens 2048. The page's `printed_page` comes from the layout answer, not from the Entry Span requests.
- **Temperature.** Every first attempt, layout and Entry Span, runs at temperature 0, as the shared request runner already does. Retries keep the existing retry temperature (0.3).
- **Page answer.** Code joins the Entry Spans' Blocks in span order with the layout's `printed_page` into the existing per-page answer. Assembly, Fixes (keyed by PDF page, stale when the page's answer changes), Warnings and `answers.json` are unchanged.
- **Failure.** If the layout request fails, or any Entry Span's request fails on every attempt, the page has no answer and gets the existing missing-page Warning, naming the failing request.
- **Line-finder Warning.** A new Warning kind for a page where ink below the Running Head lies outside every found line.
- **Store.** The layout answers and Entry Span answers each get their own folder of saved requests, stamped as today (PDF hash, image settings, prompt hash, per-request user text); an Entry Span's stamp also holds its start and end lines and its crop rectangle. The numbered layout images are kept per page for the review server. Old whole-page answers are not migrated: they no longer match the stamp and are redone.
- **Review data.** Each page in the entries file gains its Entry Spans: the crop rectangle as fractions of the page image, the start Line Number, the kind (proverb, Leading, letter) and the label (the entry's name, "Leading", or the letter), and the path of its numbered layout image.
- **Review server.** Draws each Entry Span's rectangle on the page scan, coloured by kind and labelled with its start Line Number and label, from the model's answer even when the page has a Fix. A toggle turns the rectangles on and off (on by default); another switches between the scan and the numbered layout image. This reverses the review-editing spec's "No bounding boxes and no highlighting on the scan" for Entry Spans only.
- **Dry run.** Counts the layout requests' prompt tokens. Entry Span requests depend on layout answers, so they are not counted.

## Testing Decisions

- No tests are added and nothing is checked in a browser: the change is verified by reasoning through the code.
- Nữ Giới Chung's behaviour after the line finder moves is verified by reading that the moved code is unchanged and only its import changed.

## Out of Scope

- Model-drawn coordinates, and code moving or correcting the model's splits.
- Cutting tall Entry Spans into Strips.
- Showing neighbouring entries in an Entry Span's crop.
- Any change to assembly, Fixes, Expansions, the export or the website.
- Parts 2–4 (added to settings when they are run).
- A trial of the whole-page pipeline before this change.

## Further Notes

- The default model, Qwen-SEA-LION-v4.5-27B-IT (built on Qwen3.6-27B), answers only integers in the layout request, so its native box-coordinate convention does not matter here.
- About 1 + 12 requests per page instead of 1; the trial pages ran 650–1100 completion tokens per whole page, so each Entry Span is expected well under its 2048 cap.
- The review server's web code (`app.js`) has uncommitted changes at the time of writing; build on them.
