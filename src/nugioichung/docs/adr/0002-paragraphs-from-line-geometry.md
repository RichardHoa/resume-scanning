# Paragraph breaks come from the scan's line geometry, and the Format request refines them

The Read request's lines carry no position, and the model kept printed line breaks or guessed paragraph breaks badly. So code now finds each printed line of a Region or Strip on the bilevel scan (from the blank gaps between lines, as Strip cuts already are), matches them in order to the Read lines, and joins the lines into paragraphs itself: a new paragraph at an indented line or after a line that stops short, a centred line on its own, every other line carried on (no space after an end hyphen). The same geometry decides whether a paragraph runs on across a Strip or Region boundary. The Format request is kept as it is, still writing the whole text as Markdown with code checking its letters, but it is given these code-joined paragraphs instead of the raw lines, so it only has to correct the breaks it disagrees with and add the Markdown marks. The line boxes also let the review viewer highlight each line of the transcription on the page.

## Considered Options

- **Format request returns an edit list** (split paragraph N before a word, join N and N+1, mark a heading or verse), applied by code so no letter can change: rejected for now. Tables and the Table of Contents don't fit split/join edits and would need the full-text request anyway, and the full-text request with its letter check already guarantees no letter changes.
- **Model's own flags and line breaks only** (as before): replaced, as they were unreliable.

## Consequences

- A Region or Strip whose printed lines can't be matched to its Read lines (count differs: Hán characters, pictures, large type) gets a Warning and falls back to the old joining: the hyphen rule only, the model's `starts_mid_paragraph`/`ends_mid_paragraph` across boundaries, and the Format request deciding the breaks. In the viewer it highlights as a whole Cut, not line by line.
- Formatted text is mapped back to printed lines by walking its letters against the Read lines' letters, which the letter check makes possible.
