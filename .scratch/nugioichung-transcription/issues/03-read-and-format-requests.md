# 03: Read and format requests

**What to build:** Split each Region's or Strip's transcription request into a read request (copy the printed lines exactly, no formatting) and a format request (the same text as Markdown, no letter changed), with a code check that the format request changed no letter. A Footnotes Region is split into Footnotes by code instead of a format request.

See the spec (`.scratch/nugioichung-transcription/spec.md`, Transcription pass) and stories 20a–20c.

**Blocked by:** 02

**Status:** ready-for-agent

- [ ] The read request sends the crop with only the copying rules and answers `lines`, one per printed line, with `starts_mid_paragraph` and `ends_mid_paragraph`.
- [ ] The format request sends the crop and the read lines with only the layout rules and answers `text`; its stamp includes the read lines.
- [ ] Code checks the formatted text has the read lines' letters (ignoring whitespace, Markdown marks, hyphens and dots); if not, or it has no answer, the read lines are joined by code and the dropped log says why.
- [ ] A Footnotes Region's lines are split by code at each "(n)" at a line's start; lines before the first number are Footnote 0.
- [ ] `--pass transcribe` runs read then format; a dry run counts the format requests of cuts that already have a read answer.
- [ ] Read and format requests are saved under `requests/read/` and `requests/format/` and shown under each Region in `inspect.html`.
- [ ] The run summary counts read and format requests by status and the cuts that fell back to their read lines.
