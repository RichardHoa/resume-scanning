# Extraction copies, evaluation judges

The extractor LLM only copies text from the resume into the schema. It never writes, expands, infers or restructures anything. Every judgement about the candidate happens at Category evaluation, which receives the raw resume keys unchanged. So `skills` holds the resume's own skill lines exactly as written, `position_applied.title` is empty unless the resume states the position applied for (it is never inferred from past job titles or the PDF filename), and the evaluator gets no pre-computed summaries of the work history. The old generated `skills_and_specialties` field let the extractor's guesses reach the evaluator looking like resume evidence, and nobody could check it against the source text. Do not add generated or inferred fields back to the extraction schema. Put that reasoning in the evaluator prompt instead.

## Consequences

- A resume with no stated position is flagged as a Missing Position but still evaluated, as if it applied for the job the HR requirement describes. The empty field is never filled in by inference.
- The fidelity check compares every extracted string, `skills` included, against the parser's text (ADR 0002). That text is what counts as verbatim, so changing the parser means re-extracting every resume set in one clean run.
- The only inference that remains is naming a language from its certificate (TOEIC → English). That labels verbatim text and adds no claim about the candidate.
