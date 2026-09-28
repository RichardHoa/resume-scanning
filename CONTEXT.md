# Resume Scanning

Domain vocabulary for the HR requirement intake, decomposition, and candidate evaluation pipeline.

## Language

**Standard Requirements**:
The hard/objective hiring criteria HR provides as free text (e.g. seniority, skills, experience, education). Source field: `standard_requirements`.
_Avoid_: job description, requirements (alone)

**Hidden Requirements**:
HR's own explicitly-stated soft or culture-fit criteria (e.g. "collaborative", "fast-paced"), written by HR themselves — distinct from an Implicit Assumption, which HR never wrote down. Source field: `hidden_requirements`.
_Avoid_: soft requirements, culture fit (alone)

**Implicit Assumption**:
An unstated premise the LLM infers behind a vague phrase in HR's Standard or Hidden Requirements (e.g. assuming "senior" means "5+ years" without HR saying so). Surfaced to HR as a Clarification Question before decomposition.
_Avoid_: hidden assumption (collides with Hidden Requirements)

**Clarification Question**:
A question shown to HR naming an Implicit Assumption and asking HR to confirm or correct it. Up to 5 are generated per field (Standard, Hidden). Non-blocking: HR may ignore them entirely and edit the free-text request directly instead of answering.
_Avoid_: assumption question

**Category** (also **Dimension**):
One of five fixed buckets — `seniority_title`, `technical_skills`, `work_experience`, `education_certifications`, `hidden_culture` — that Standard/Hidden Requirements are decomposed into, after HR has reviewed any Clarification Questions.
_Avoid_: criteria type, bucket

**Criterion**:
A single verbatim requirement string assigned to one Category during decomposition, stored in the RAG store.
_Avoid_: requirement item
