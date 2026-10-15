# Evaluation never builds or changes the HR RAG

The batch runs (extract then evaluate, evaluate alone, the consistency and bias checks) used to build the HR RAG themselves: the extract-and-evaluate job wiped `rag/` and the evaluator decomposed `hr-requirement.txt` when the store was empty. The Criteria were then whatever the decomposer produced on that run, which nobody had reviewed. Now every evaluation reads the HR RAG as it is stored and stops with an error if there is none. HR sets it on the website's RAG page (decompose, then review the Criteria and HR Check Items) before submitting a run, and no run deletes it. HR controls exactly what is judged, which is also how the tool is used in practice.

## Considered Options

- Keep decomposing in the batch job when the store is empty. Rejected: an unreviewed decomposition silently decides what counts, and an empty store from a mistake would go unnoticed.

## Consequences

- The `--job-req`, `--hidden-req`, `--hr-req` and `--force-reingest` flags are gone. The requirement text written into each report comes from the HR RAG's stored originals.
- One HR RAG is stored at a time, so switching between resume sets (e.g. CnB and `--tech`) means setting the HR RAG for that job first.
- The shell jobs check for the HR RAG before starting the vLLM server, so a missing one fails in seconds instead of after extraction.
