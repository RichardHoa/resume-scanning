# HR Check Items are set aside at decomposition, not judged

Some requirements HR writes, such as willingness to work overtime, availability to start immediately or expected salary, never appear in an ordinary resume. Judging them gave every candidate NO_EVIDENCE and lowered scores for something the resume could not have shown. So the decomposer sorts these into a separate list of HR Check Items, next to the five Categories. HR Check Items get no weight, no Importance and no Verdict, and the Review Panel never sees them. HR gets them as a note to check by hand. In the criteria editor, HR can move items between a Category and the HR Check Items before saving the HR RAG (ADR 0005).

## Considered Options

- **A fourth Verdict ("cannot be verified from a resume") that scoring ignores.** Rejected: it would change the scoring maths, and the evaluator would make the call again for every candidate. One decision at decomposition is easy for HR to review and correct.

## Consequences

- If every Criterion in a Category becomes an HR Check Item, it is a Not Applicable Category, and its weight is spread over the other Categories as usual.
