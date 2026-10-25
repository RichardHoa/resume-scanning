# Fidelity check: stop the false "not found" warnings, keep the real ones

Status: ready-for-agent

## Problem Statement

Every extracted resume carries Fidelity Warnings: values the extractor produced that the fidelity check can't find in the resume's text. A Fidelity Warning is supposed to mean "the model changed or invented this value, look at it". In practice it almost never means that.

The 2026-10-25 consistency runs (CnB and Tech, Combined Extraction, 5 runs per resume) produced 129 distinct Fidelity Warnings across 45 of 88 resumes, so 51% of resumes are flagged. Each warning was checked against the resume's markdown:

- **101 (78%) are false.** The value is in the PDF text, but the check misses it because of:
  - **A stray `<` deletes text.** A bare `<` or `>` in a resume is taken for an HTML tag, and everything between them is removed. In one resume, `< 50 employees … >90%` deleted 1,480 characters.
  - **Underscores stay glued to words.** Italic markdown (`_Managed …_`) never matches, because the underscore is kept as part of the word.
  - **Full-width characters aren't folded.** `２０１０年１１月` and `Ｎ3` don't match the `2010年11月` and `N3` the model writes.
  - **The text layer splits words and URLs.** For example `nguye nducnham180992`, `gmail.co m`.
  - **Values are reassembled.** The model correctly joins pieces that the parser put apart: bullets from two columns, a KPI block merged into responsibilities (the prompt asks for this), a company name interleaved with a sidebar, a date range whose two ends sit on different lines. This is what Combined Extraction is for (ADR 0013).
  - **The allowed language exception is flagged.** ADR 0003 allows naming a language from its certificate (TOEIC → English, JLPT → Japanese), but the check still warns.
- **12 (9%) are real rule breaks**, in 6 resumes:
  - a company name read from a logo;
  - text read from the image because the text layer is garbled;
  - 英語 translated to "English";
  - "present" (現在) replaced by the Reference Date month;
  - a typo silently corrected;
  - an invented "Projects:" label;
  - "in English" dropped from a proficiency line.
- **16 (12%) are correct values that no text-only check can prove.** Examples: Japanese 履歴書 table dates built from a year cell, a month cell and the `年`/`月` column headers; parts of a value far apart in a two-column layout.

With half of all resumes flagged, HR and developers learn to ignore Fidelity Warnings, and the 12 real rule breaks are lost in the noise. ADR 0013 left this open: "loosening the match is a separate decision, made only if the numbers call for it". The numbers call for it.

## Solution

The rule does not change: **every extracted string must come from the PDF's text layer** (ADR 0003, ADR 0013). Only the way the fidelity check looks for a value in the text changes.

The fixed normalisation removes the three bugs: stray angle brackets, underscores and full-width characters. Then five matching rules accept a value if any one of them passes:

1. it appears as a contiguous run;
2. it appears once all spaces are removed, matching whole words;
3. each of its bullets or parts appears;
4. its words appear in order within a short stretch of the text;
5. it is a language named from a certificate for that language.

Guards on rules 2–4 stop short or generic values (a date range, a two-word job title) being pieced together from unrelated parts of the resume.

Simulated on the 2026-10-25 runs:

- flagged resumes drop from 45 (51%) to 12 (14%);
- warnings drop from 129 to 28;
- all 12 real rule breaks are still flagged;
- checking 9,070 values taken from *other* resumes, the new match accepts 13 more (0.14%) than today's check, all short generic strings.

The warning text, the PDF Note and Repaired Extraction entries, and everything that reads the warning list stay the same.

## User Stories

1. As an HR reviewer, I want a Fidelity Warning to appear only when the extractor changed or invented a value, so that I take the warning seriously when I see one.
2. As an HR reviewer, I want most resumes to carry no Fidelity Warning, so that the flagged ones stand out.
3. As an HR reviewer, I want a company name the model read from a logo to stay flagged, so that I know the value wasn't checked against the resume's text.
4. As an HR reviewer, I want an end date that the model filled in for "present" to stay flagged, so that I don't take the candidate as having left a job they still hold.
5. As an HR reviewer, I want a translated language name to stay flagged, so that I know the value isn't the resume's own words.
6. As an HR reviewer, I want "English" next to a TOEIC or IELTS score not to be flagged, so that I'm not warned about the one inference the system allows.
7. As an HR reviewer, I want "Japanese" next to a JLPT certificate not to be flagged, for the same reason.
8. As an HR reviewer, I want a LinkedIn URL or email address that the PDF splits across two lines not to be flagged, so that I'm not sent to check a value that is correct.
9. As an HR reviewer, I want a company name pulled correctly out of a two-column layout not to be flagged, so that Combined Extraction's layout help doesn't generate noise.
10. As an HR reviewer, I want a work history whose bullets come from several places on the page not to be flagged when every bullet is in the resume, so that long responsibility fields aren't flagged by default.
11. As an HR reviewer, I want italic or bold text in the resume not to cause a warning, so that formatting never looks like an extraction error.
12. As an HR reviewer, I want a resume containing "< 50 employees" or ">90%" not to lose text from the check, so that one symbol doesn't flag half the work history.
13. As an HR reviewer, I want full-width Japanese digits and letters to match their ASCII form, so that Japanese resumes aren't flagged for every date.
14. As an HR reviewer, I want a date range made of two years that don't belong together to stay flagged, so that a wrong pairing of dates isn't hidden.
15. As an HR reviewer, I want a short job title or skill that the resume doesn't contain to stay flagged, even if its words are scattered across the resume, so that invented titles aren't accepted.
16. As an HR reviewer, I want a typo that the model silently "fixed" to stay flagged, so that I see the resume as written.
17. As an HR reviewer, I want a label the model invented ("Projects:") to stay flagged, so that I know the text isn't the candidate's.
18. As a developer, I want the warning text and prefix unchanged, so that the consistency check, the website and the stored extractions keep working without changes.
19. As a developer, I want the fidelity check to keep the same entry point and arguments, so that no caller changes.
20. As a developer, I want the matching thresholds (window spread, minimum length for the window rule, what counts as a short segment) as named constants, so that I can retune them after the next consistency run.
21. As a developer, I want the list of language certificates per language in one place, so that I can add one (e.g. TOPIK, HSK) without touching the matching code.
22. As a developer, I want text-only extraction to use the same fidelity check, so that both modes are judged by one rule.
23. As a developer, I want a rerun of the extractor consistency check to show the drop in "With errors" counts, so that I can confirm the change on real data without new tooling.
24. As a developer, I want the real rule breaks found on 2026-10-25 still listed after the change, so that I can confirm nothing real was hidden.
25. As a developer, I want ADR 0013's consequence about loosening the match updated, so that the decision record matches the code.
26. As a maintainer, I want the fidelity check to remain a check of where a value came from, not of where it was placed, so that its meaning stays narrow and clear.

## Implementation Decisions

- **One module changes: the fidelity check inside the extractor pipeline.** Its public entry point stays as it is: it takes an extraction and its markdown, and returns the list of Fidelity Warning strings. The prefix and the message format stay the same. No caller changes: the batch extractor, the web extraction API and the extractor consistency check all read the warning strings as they are.
- **One tokeniser replaces the two current normalisers and the current matcher.** The markdown is tokenised once per extraction. Each value is tokenised and checked with its field path, which rule 5 needs.
- **Normalisation, applied to both value and markdown, in this order:**
  1. HTML-entity decode.
  2. Unicode **NFKC**, replacing NFC. This folds full-width characters.
  3. Remove only real HTML tags: `<`, optional `/`, a letter, a tag name, optional attributes of bounded length with no angle brackets, `>`. A bare `<` or `>` is ordinary punctuation.
  4. Unwrap markdown links to their text, as today.
  5. Lowercase. Every non-word character **and the underscore** becomes a space.
  6. Every CJK character (kana, CJK ideographs, Hangul) becomes its own token.
  7. Split on whitespace.
- **Matching rules**, tried in order. The first that passes accepts the value; if none passes, the value gets a Fidelity Warning:
  1. **Contiguous.** The value's tokens appear as a contiguous run of markdown tokens.
  2. **Spaceless.** The value's tokens, joined without spaces, equal a run of *whole* markdown tokens joined without spaces. The match must start and end on token boundaries, so a short value can't match inside a longer word.
  3. **Segments.** The value is split at line breaks, bullet markers (`- `, `+ `, `• `), ` / ` and spaced range dashes (` - `, ` – `, ` — `). There must be at least two non-empty segments, and each must pass rule 1 or 2. **If any segment is short (fewer than 3 tokens), all the value's tokens must also pass the ordered window**, with the base spread. This keeps a date range from being built out of two unrelated years.
  4. **Ordered window.** Only for values of **at least 5 tokens**. All the value's tokens appear in order, counting from a match of the first token, within (value length + max(value length, 10)) markdown tokens.
  5. **Language from certificate.** Only for a language-name field inside the languages list. The value is a known language, and the markdown names a certificate for it:
     - English: TOEIC, IELTS, TOEFL, Cambridge, APTIS, VSTEP;
     - Japanese: JLPT, 日本語能力試験;
     - Chinese: HSK, TOCFL;
     - Korean: TOPIK.

     Anything else, including a language name translated from the resume's own words, stays a warning.
- **Named constants.** Short-segment threshold 3 tokens, window base spread 10 tokens, minimum length for the window rule 5 tokens, and the certificate table, all kept beside the Fidelity Warning prefix. These values were chosen by measurement. A minimum of 4 tokens cleared 1 more real-data warning but accepted 10 more foreign values in CnB. A minimum of 8 cleared 5 fewer with no gain in safety.
- **Values that stay Fidelity Warnings on purpose:**
  - anything read only from a page image;
  - a translation, a reworded or invented label, a corrected typo, a value inferred or filled in (for example a date in place of "present").
- **Accepted remaining false warnings:**
  - Japanese table dates that join cells with column-header units;
  - values whose parts are further apart than the window.

  Both are rare and HR can open the PDF. They are not special-cased.
- **ADR and glossary.**
  - ADR 0013's consequence "loosening the match is a separate decision" is replaced by a line saying the match was loosened under this spec, and that the rule (values only from the text layer) is unchanged.
  - The glossary entry for Fidelity Warning keeps its meaning and needs no change.

## Testing Decisions

- **Seam:** the fidelity check's existing public entry point (an extraction plus its markdown in, a list of Fidelity Warning strings out). It is the only seam, and it already exists. Good checks exercise only this behaviour: given this markdown and this extracted value, is a warning produced? They don't check which internal rule matched.
- **No automated tests are added.** This project tests by reasoning and by manual runs, not with a test suite.
- **Manual verification on real data:**
  1. Rerun the extractor consistency check for both resume sets with the default model.
  2. Extraction is unchanged, so field differences should stay the same.
  3. "With errors" should drop from 24 to about 6 resumes (CnB) and from 21 to about 6 (Tech).
  4. These 12 real rule breaks must still appear:
     - Hoang Tan Tai: company from the logo;
     - Tran Ngoc Thien Trang: 4 values read through a garbled text layer;
     - Pham Truong Hoai Tram: corrected typo;
     - Nguyen Anh Tho: translated "English", and "2015/12" in place of 現在;
     - Tong That Tung: 3 invented "Project(s):" labels;
     - Nguyen Trong Lam: shortened proficiency.
- **Prior art:** the 2026-10-25 simulation, which ran the proposed rules over the stored markdown and extraction JSON of both runs. It measured warnings cleared (101 of 129) and false acceptance: values taken from 3 other resumes in the same set, 9,070 in all, of which 13 were accepted beyond today's check. Repeating the false-acceptance measurement after a rerun is the safety check for any later retuning. The full numbers are in the research note on the 2026-10-25 consistency runs.

## Out of Scope

- **Changing the extractor.** No prompt or schema changes. Prompt fixes for the 12 real rule breaks (never replace "present" with a date, never translate a language name, never add a label, never fix a typo) are a separate change.
- **Checking where a value went.** A real value placed in the wrong field or the wrong job entry passes any text check. One run put project names into job titles. Measuring placement needs hand-checked gold extractions and is a separate effort.
- **Detecting values that were dropped.**
- **A repair pass** that asks the model to fix flagged values (already dropped in the extractor consistency spec).
- **Showing which rule matched,** or giving warnings a severity.
- The bias suite, DSPy and evaluation consistency.
- **PDF parsing.** Whether PyMuPDF4LLM's built-in RapidOCR should be turned off is an open question below, not part of this change.

## Further Notes

- **Open question:** the consistency job log shows PyMuPDF4LLM running RapidOCR on some pages (176 log lines in the CnB run). If OCR text reaches the markdown, the fidelity check can no longer tell values from the text layer apart from values read from pixels, which weakens ADR 0007 and ADR 0013. Check whether the parser should be called with OCR off.
- **Where to find the data:** the full analysis, with every warning sorted by cause and every field difference listed, is in the research note on the 2026-10-25 extractor consistency runs under the docs research folder. The run folders it used are rewritten on every consistency job, so the note is the lasting record.
