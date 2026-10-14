# HR Check Items are set aside at decomposition, not judged

Some requirements HR writes (willingness to work overtime, can start immediately, expected salary) never appear in an ordinary resume, so judging them gave every candidate NO_EVIDENCE and lowered scores for something the resume could not have shown. The decomposer now sorts these into a separate list of HR Check Items next to the five Categories. They get no weight and no Verdict, the Review Panel never sees them, and HR gets them as a note to check by hand. HR can move items between a Category and the HR Check Items in the criteria editor before evaluating; the sbatch pipeline has no HR review, so the decomposer's split is final there.

## Considered Options

- A fourth Verdict ("cannot be verified from a resume") that scoring ignores. Rejected: it changes the scoring maths, and the evaluator would make the call again for every candidate, where one decision at decomposition is easy for HR to review and correct.

## Consequences

- A Category whose Criteria all become HR Check Items is a Not Applicable Category, so its weight is spread over the others as usual.
