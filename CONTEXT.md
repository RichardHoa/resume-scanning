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
An unstated premise the LLM infers behind a vague phrase in HR's Standard or Hidden Requirements (e.g. assuming "senior" means "5+ years" without HR saying so), or behind something HR left out entirely. Seniority and education are always probed in the Standard Requirements: if HR wrote nothing about them, the unstated expectation itself is the Implicit Assumption. Surfaced to HR as a Clarification Question before decomposition; HR sees only the question, never the inferred premise.
_Avoid_: hidden assumption (collides with Hidden Requirements)

**Clarification Question**:
A question shown to HR naming an Implicit Assumption and asking HR to confirm or correct it. Between 1 and 5 are generated for each non-empty field (Standard, Hidden), none for an empty one, without padding. Each names one specific requirement and asks what it means in practice: the expected level or scope, and what may substitute for it (e.g. experience in place of a degree). It never asks whether a requirement is a must-have or a nice-to-have: that is the Criterion's Importance, which HR sets when reviewing the HR RAG. Non-blocking: HR may ignore them entirely and edit the free-text request directly instead of answering. Asked once per pass through requirement intake: after they are shown, HR's next action is decomposition, with no second check. The check runs again only if HR returns from Category review and changes the requirement text.
_Avoid_: assumption question

**Category** (also **Dimension**):
One of five fixed buckets — `seniority_title`, `technical_skills`, `work_experience`, `education_certifications`, `hidden_culture` — that Standard/Hidden Requirements are decomposed into, after HR has reviewed any Clarification Questions.
_Avoid_: criteria type, bucket

**Not Applicable Category**:
A Category that HR's requirements gave no Criterion. It carries no weight and is not judged, so it is never shown to HR. Distinct from a Category that could not be scored, which makes a Failed Evaluation.
_Avoid_: missing category, empty category

**HR Check Item**:
A requirement HR wrote, in the Standard or Hidden Requirements, that no ordinary resume would show (e.g. willingness to work overtime, can start immediately, expected salary). It is set aside during decomposition, belongs to no Category, carries no weight, never gets a Verdict, and is handed to HR as a note to check manually. Anything a typical resume could plausibly show stays a Criterion. HR may move items between a Category and the HR Check Items before evaluating; a run with no HR review keeps the decomposer's split as is.
_Avoid_: unverifiable criterion, manual check, note (alone)

**Reference Date**:
The date treated as "today" when reading and judging a resume set, e.g. for turning "2013 – present" into years of experience. It is the real current date unless the resume set is old: the Tech resume set uses December 2015.
_Avoid_: current date (alone), now

**Criterion**:
A single verbatim requirement string assigned to one Category during decomposition, stored in the RAG store with its Importance, which is kept apart from the text and never changes it.
_Avoid_: requirement item

**Importance**:
How much one Criterion counts inside its Category: Must-have (weight 2), Standard (2) or Nice-to-have (1). The Category score is the mean of its Verdicts weighted by Importance, so a Category of only Standard Criteria scores as a plain mean. A Must-have weighs the same as a Standard; what sets it apart is that lacking it makes a Must-have Rejection. Only HR sets it, per Criterion, when reviewing the HR RAG: the decomposer proposes none, so every Criterion starts as Standard. The evaluator LLM never sees it. HR Check Items have none. A Criterion stored without one reads as Standard.
_Avoid_: priority, weight (alone)

**Must-have Rejection**:
An evaluation in which at least one Must-have Criterion got No Evidence in most of its Category's runs; it names which ones, and its match recommendation is `MUST_HAVE_REJECTED`. The candidate is out: still scored in every Category so HR can see the scores, but never ranked and given no Candidate Feedback, and listed apart from the ranked candidates. A Must-have with Partial evidence never rejects. HR un-rejects a candidate only by changing that Criterion's Importance and re-evaluating. A Failed Evaluation is never a Must-have Rejection: it needs a rerun first.
_Avoid_: Missing Must-Have, dealbreaker

**HR RAG**:
The stored set of Criteria (each with its Importance) and HR Check Items for one job, with HR's original requirement text. HR sets it on the website's RAG page (decompose, then review the Criteria and their Importance) before any evaluation. Evaluation only reads it: no run builds, changes or deletes it, and a run with no HR RAG stops with an error. The one exception is a one-time reset: an HR RAG saved while the decomposer still proposed Importance has every Criterion set back to Standard the first time it is loaded.
_Avoid_: RAG store (alone), vector DB

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
The Review Panel's output for one evaluated candidate: a short factual summary, exactly three strengths, exactly three weaknesses or missing skills, and each Panelist's final view (kept for developers, collapsed for HR). Written for the HR user and never sent to the candidate. It is produced only for a fully scored evaluation that is not a Must-have Rejection.
_Avoid_: resume feedback, summary (alone), report

**Failed Evaluation**:
An evaluation in which at least one Category could not be scored. The whole candidate is marked as an error that needs a full rerun: its partial score is not ranked or shown as a result, and no Candidate Feedback is produced.
_Avoid_: partial evaluation, partial failure

**Scanned Resume**:
A resume PDF in which no page has text the system can read, only pictures of text. It is rejected before extraction: never extracted, evaluated or ranked, because resumes can be in any language and the system does not read text from images. It still appears in the results list, unranked and marked as scanned, so HR can ask the candidate for a PDF with selectable text. Distinct from a Failed Evaluation, which a rerun can fix; a Scanned Resume needs a new file from the candidate. A resume where only some pages lack text (e.g. a scanned certificate attached) is not a Scanned Resume: its text pages are read and HR is warned to check the others by hand.
_Avoid_: OCR resume, image PDF, unreadable resume

**Combined Extraction**:
Extraction in which the model sees each page's image as well as the PyMuPDF text, turned on with `--combined`. The images show only the layout (columns, table rows, which entry a date or company belongs to); every value is still copied from the PDF's text, and the fidelity check rejects anything read only from an image. It needs a model that can see images, and never applies to a Scanned Resume.
_Avoid_: vision extraction, OCR extraction

**Missing Position**:
A flag on a resume that states no position the candidate is applying for. The resume is still evaluated, ranked and given Candidate Feedback like any other, as if applying for the job the HR requirement describes (every resume in a run is assumed to be for that one job); the flag only tells HR, on the website, that the position was missing. Having no stated position is not evidence against the candidate.
_Avoid_: no position, error, unevaluated

**Evaluation Order**:
A secret, ranked list of candidates (by email) that HR supplies per resume set, used on the website to group and order candidates into tiers. The Tech resume set lists only its top 10 in rank order, shown with their rank (#1–#10); every other candidate falls into one "rest" section. Each resume set is ranked only by its own list.
_Avoid_: answer key, tier file

**Shuffle Kind**:
One way of reordering the same prompt content in a bias test (e.g. Macro Permutation, Criteria Permutation, Atomic Interleave), used to check whether evaluation scores depend on ordering. The Baseline is not a Shuffle Kind.
_Avoid_: experiment type, permutation group

**Baseline**:
The unshuffled evaluation run in each bias-test iteration; every Shuffle Kind run in that iteration is compared against it.
_Avoid_: control, reference run
