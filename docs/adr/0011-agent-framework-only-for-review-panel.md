# Microsoft Agent Framework only for the Review Panel

The Review Panel that writes Candidate Feedback is built on Microsoft Agent Framework (`agent-framework`). The extractor, requirement scrutiny, decomposition and Category evaluation all stay on the hand-rolled `src/providers/vllm_client.py`. The bias and consistency checks measure scoring through that exact call path, with the temperatures in ADR 0009 and schema-enforced `structured_outputs` (ADR 0007). Moving scoring onto a framework would change that path and gain nothing for scoring. The panel is the only multi-agent conversation in the pipeline (three Panelists, one Rebuttal Round, a Coordinator), so it is the one place an orchestration framework earns its keep. Do not "unify" the scoring calls onto Agent Framework without re-running both checks.

## Consequences

- Both clients talk to the same vLLM server and share one process-wide limit on in-flight requests, so the panel and Category evaluation never oversubscribe the server together.
- The Review Panel runs only for candidates that are fully scored and not rejected (ADR 0008). It never changes a score.
