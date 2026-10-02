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
A question shown to HR naming an Implicit Assumption and asking HR to confirm or correct it. Between 1 and 3 are generated for each non-empty field (Standard, Hidden), none for an empty one. Each names one specific requirement and asks whether it is a must-have or a nice-to-have, and what level is expected. Non-blocking: HR may ignore them entirely and edit the free-text request directly instead of answering. Asked once per pass through requirement intake: after they are shown, HR's next action is decomposition, with no second check. The check runs again only if HR returns from Category review and changes the requirement text.
_Avoid_: assumption question

**Category** (also **Dimension**):
One of five fixed buckets — `seniority_title`, `technical_skills`, `work_experience`, `education_certifications`, `hidden_culture` — that Standard/Hidden Requirements are decomposed into, after HR has reviewed any Clarification Questions.
_Avoid_: criteria type, bucket

**Criterion**:
A single verbatim requirement string assigned to one Category during decomposition, stored in the RAG store.
_Avoid_: requirement item

**Verdict**:
The judgement the LLM gives one Criterion for one candidate: Strong, Partial or No Evidence. The LLM writes its reasoning before it writes the Verdict. The LLM never produces a score; the Category score is derived from the Verdicts.
_Avoid_: score (for the LLM's output), category (collides with Category)

**Review Panel**:
The group of three Panelists that discuss one candidate's evaluation and produce feedback for the HR user. It reads the scores but never changes them.
_Avoid_: summarizer sub-agents, crew

**Panelist**:
One reviewing perspective on the Review Panel: **Leadership** (leadership potential), **Domain Expertise** (the role-specific skills the job needs, technical or not), or **People & Culture** (soft skills and culture fit). These replace the paper's CEO, CTO and HR agents.
_Avoid_: CEO/CTO/HR agent ("HR" here always means the human HR user)

**Rebuttal Round**:
The single round, after each Panelist gives an independent view, in which every Panelist reads the other two views and responds. There is exactly one per Review Panel.
_Avoid_: debate loop, discussion turns

**Coordinator**:
The agent that merges the Panelists' final views into the Candidate Feedback. It is not a Panelist and adds no perspective of its own.
_Avoid_: summarizer (alone), moderator

**Candidate Feedback**:
The Review Panel's output for one evaluated candidate: a short factual summary, exactly three strengths, exactly three weaknesses or missing skills, and each Panelist's final view (kept for developers, collapsed for HR). Written for the HR user and never sent to the candidate. It is produced only for an evaluation with no Failed Evaluation.
_Avoid_: resume feedback, summary (alone), report

**Failed Evaluation**:
An evaluation in which at least one Category could not be scored. The whole candidate is marked as an error that needs a full rerun: its partial score is not ranked or shown as a result, and no Candidate Feedback is produced.
_Avoid_: partial evaluation, partial failure

**Missing Position**:
A resume that states no position the candidate is applying for. It is never evaluated, ranked or given Candidate Feedback; it is shown to HR for preview only, and HR resolves it outside the app. Distinct from a Failed Evaluation, which was attempted and needs a rerun.
_Avoid_: no position, error

**Shuffle Kind**:
One way of reordering the same prompt content in a bias test (e.g. Macro Permutation, Criteria Permutation, Atomic Interleave), used to check whether evaluation scores depend on ordering. The Baseline is not a Shuffle Kind.
_Avoid_: experiment type, permutation group

**Baseline**:
The unshuffled evaluation run in each bias-test iteration; every Shuffle Kind run in that iteration is compared against it.
_Avoid_: control, reference run
