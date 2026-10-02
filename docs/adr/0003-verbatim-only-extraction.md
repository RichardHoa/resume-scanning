# Extraction copies, evaluation judges

The extractor LLM only copies text from the resume into the schema; it never writes, expands, infers or restructures. Every judgement about the candidate happens at Category evaluation, which receives raw resume keys unchanged. So `skills` holds the resume's own skill lines exactly as written (no "- skill: 3-sentence explanation" expansion), `position_applied.title` is empty unless the resume states the position applied for (never inferred from past job titles or the PDF filename), and the evaluator gets no pre-computed summaries of the work history. The old generated `skills_and_specialties` field let the extractor's guesses reach the evaluator looking like resume evidence, and could not be checked against the source text. Do not add generated or inferred fields back to the extraction schema; put that reasoning in the evaluator prompt instead.

## Consequences

- A resume with no stated position is a Missing Position and is never evaluated; HR resolves it outside the app.
- The fidelity check covers every extracted string, `skills` included.
- The only inference that remains is naming a language from its certificate (TOEIC → English), which labels verbatim text and adds no claim about the candidate.
