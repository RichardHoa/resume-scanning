# HR sets the HR RAG; evaluation only reads it

Every evaluation reads the stored HR RAG as it is, and stops with an error if there is none. HR sets the HR RAG on the website's RAG page before submitting a run: scrutiny, decomposition, then a review of the Criteria, their Importance and the HR Check Items. No run builds, changes or deletes the HR RAG. The batch jobs used to wipe `rag/` and decompose `hr-requirement.txt` themselves, so the Criteria were whatever the decomposer produced on that run, and nobody had reviewed them. Now HR controls exactly what is judged, which is also how the tool is used in practice.

## Considered Options

- **Decompose in the batch job when the store is empty.** Rejected: an unreviewed decomposition would silently decide what counts, and an empty store left by a mistake would go unnoticed.

## Consequences

- The requirement text written into each report comes from the HR RAG's stored originals. There are no `--job-req`, `--hr-req` or `--force-reingest` flags.
- Only one HR RAG is stored at a time, so switching between resume sets (CnB and Tech) means setting the HR RAG for that job first.
- The shell jobs check for the HR RAG before starting the vLLM server, so a missing one fails in seconds rather than after extraction.
