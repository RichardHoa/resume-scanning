# Evaluator consistency on CnB at temperature 0: how unstable the model still is, 2026-11-03

This report reads the CnB run `runs/evaluator-consistency-cnb` (report file dated 2026-11-03 16:45) and records how much the evaluator varies on identical input. It is a reference measurement and the CnB counterpart of `docs/research/evaluator-consistency-tech-2026-11-03.md`. No code or rubric change is proposed or planned.

There is no earlier CnB run to compare with. The comparison in §2.7 is against the Tech run of the same day.

Claims tagged **(verified)** were counted from the report or checked in the code. Claims tagged **(inference)** are my reading and were not measured in this run.

## TL;DR

- **Same resume, same extraction, same HR RAG, every run at T=0, and the result still varies, by about as much as on Tech.**
  - 16 of 35 resumes (46%) got a different Verdict on at least one Criterion across 5 Repeat Evaluations.
  - 20 of 315 (resume, Criterion) Verdicts changed (**6.3%**).
  - 24 of 35 Overall Scores (69%) were not identical across the Repeat Evaluations. Mean spread 2.2 points, median 1.2, largest **10.0**.
- **This run shows real recommendation changes: 4 of 35 resumes (11%).** The CnB HR RAG has no Must-have, so nothing hides the score. Tech showed 0 changes because its Must-have gate fixed 49 of 53 outcomes, and its report estimated 8 of 53 (15%) without the gate. CnB's 11% fits that estimate.
- **The instability is the same kind as on Tech, at a different boundary.** Every flip is between adjacent levels and never No↔Strong. CnB flips are mostly Partial↔Strong (16 of 20), where Tech's are mostly No↔Partial (32 of 42). On CnB the usual question is whether doing the work proves the Criterion, such as whether "100% compliance" proves "nắm vững" the law.
- **The largest swings come from Education & Certifications, which behaves as a single Criterion.** It carries 0.25 of the Overall Score alone, so a change from 0.1 to 0.5 on that one Criterion moved one resume by 10.0 points and across the 85 threshold.
- **New compared with Tech: one resume had Failed Evaluations.** Thai Thi Ny Na failed Technical Skills in evals 4 and 5, so it is compared on 3 evaluations only.

## 1. What was run

| | |
|---|---|
| Resume set | CnB, 38 resumes, of which 35 compared and 3 Scanned Resumes skipped (Doan Thi Anh Tuyet, NGUYEN THANH TRUNG, TRAN THI TUYET TRINH). Combined Extraction, Reference Date 2026-11-03 |
| HR RAG | Chuyên viên C&B / Nhân sự tổng hợp, 9 Criteria, Hidden Requirements none, no Must-have Rejection in any evaluation |
| Design | 1 extraction per resume, then **5 Repeat Evaluations**. Each is a full production evaluation with 5 Category runs per Category (`DEFAULT_NUM_EVALUATIONS`), so 25 Category runs per (resume, Category) |
| Temperature | **0.0 for every Category run** (`src/pipelines/evaluator.py:207`). A retry after a failed attempt samples at `CATEGORY_EVAL_RETRY_TEMPERATURE` = 0.5 |
| Aggregation | Same as the Tech run: Verdict shown = majority of the 5 runs, scores come from the means of the runs (ADR 0009) |
| Model and server | Assumed the same as the Tech run (see its §1). This report file does not record them. See §4 for one code change between the two runs |
| Failed Evaluations | 1 resume, 2 evaluations (Thai Thi Ny Na, evals 4 and 5, Technical Skills, "ran out of retries"). Failed extractions skipped: 0 |

## 2. The numbers

### 2.1 Headline

| Metric | Value |
|---|---|
| Resumes compared | 35 |
| Resumes with every Verdict stable | 19 (54%) |
| Resumes with any Verdict changed | 16 (46%) |
| Verdict change rate | **20 of 315 (6.3%)** |
| Match Recommendation changed | **4 (11%)** |
| Must-have Rejection changed | 0 (none occurred) |
| Overall Score identical in all evaluations | 11 (31%) |
| Overall Score spread, mean / median / max | **2.2 / 1.2 / 10.0** (Bui Thi Thanh Tuyen) |
| Criterion Score spread (0–1), mean / max | 0.03 / 0.4 |

### 2.2 Distribution of Overall Score spread (max − min over the Repeat Evaluations)

| Spread | Resumes |
|---|---|
| 0 | 11 |
| > 0 to 1 | 6 |
| > 1 to 2 | 6 |
| > 2 to 5 | 6 |
| > 5 to 9 | 5 |
| > 9 | 1 |

The six resumes above 5 points:

| Resume | Overall Scores (eval 1–5) | Spread | Verdicts changed |
|---|---|---|---|
| Bui Thi Thanh Tuyen | 75.5, 85.0, 85.5, 85.5, 85.5 | 10.0 | 1 |
| Le Ba Thuy Hang | 68.8, 61.2, 61.2, 66.8, 65.8 | 7.6 | 2 |
| Do Thi Minh Thu | 82.0, 84.5, 77.0, 79.5, 84.5 | 7.5 | 1 |
| PHAN THI THUY LIEU | 100.0, 100.0, 100.0, 92.5, 100.0 | 7.5 | 1 |
| VO THI HONG TUYET | 0.0, 0.0, 5.0, 5.0, 7.5 | 7.5 | **0** |
| Tran Nu Thanh Danh | 79.2, 85.0, 80.0, 79.2, 84.2 | 5.8 | 1 |

### 2.3 Verdict changes per resume

| Changed Verdicts | Resumes |
|---|---|
| 0 | 19 |
| 1 | 13 |
| 2 | 2 |
| 3 | 1 (VÕ THỊ PHƯƠNG KHÁNH) |

### 2.4 What kind of flips

| | Count |
|---|---|
| Partial Evidence ↔ Strong Evidence | 16 |
| No Evidence ↔ Partial Evidence | 4 |
| No Evidence ↔ Strong Evidence | **0** |
| Split 4-vs-1 across the 5 Repeat Evaluations | 11 |
| Split 3-vs-2 | 8 |
| Split 2-vs-1 (Thai Thi Ny Na, 3 evaluations) | 1 |

| By Importance | Flips |
|---|---|
| Standard | 20 |
| Other | 0 |

| By Category | Flips | Category Score spread where it varied, mean / max |
|---|---|---|
| Technical Skills & Competencies | 17 | 5.0 / 15 (21 resumes) |
| Education & Certifications | 3 | 24.3 / **40** (7 resumes) |
| Position & Seniority Match | 0 | 15.0 / 20 (2 resumes) |
| Work Experience & Project Relevance | 0 | 20.0 / 20 (1 resume) |

### 2.5 Least stable Criteria

| Category | Criterion | Resumes where the Verdict differs | Rate | Flip type |
|---|---|---|---|---|
| Technical Skills | Nắm vững Luật Lao động, BHXH, thuế TNCN | 6 / 35 | **17.1%** | Partial↔Strong |
| Education | Tốt nghiệp Luật hoặc Quản trị nhân lực hoặc Kinh tế lao động hoặc tương đương | 3 / 35 | 8.6% | 2 Partial↔Strong, 1 No↔Partial |
| Technical Skills | Soạn thảo, quản lý HĐLĐ; hồ sơ nhân sự | 3 / 35 | 8.6% | Partial↔Strong |
| Technical Skills | Thành thạo Excel, phần mềm quản lý nhân sự | 3 / 35 | 8.6% | No↔Partial |
| Technical Skills | Tư vấn chính sách lương thưởng, phúc lợi cho nhân viên | 2 / 35 | 5.7% | Partial↔Strong |
| Technical Skills | Xử lý BHXH, BHYT, BHTN; quyết toán thuế TNCN | 2 / 35 | 5.7% | Partial↔Strong |
| Technical Skills | Tính lương, quản lý chấm công, phép năm cho nhân viên | 1 / 35 | 2.9% | Partial↔Strong |

The top Criterion accounts for 6 of the 20 flips (30%). The other 2 of the 9 Criteria never flipped.

### 2.6 How close the variation came to changing a decision

Four resumes changed Match Recommendation. These are all the resumes whose score range crosses a threshold (`MATCH_THRESHOLDS`, `>=`, `src/pipelines/scoring.py:456-463`) **(verified)**:

| Resume | Score range | Threshold crossed | Evaluations on the minority side | Main source of the swing |
|---|---|---|---|---|
| Bui Thi Thanh Tuyen | 75.5–85.5 | 85 (POTENTIAL ↔ STRONG) | eval 1 is POTENTIAL | Education 10 vs 50 |
| Tran Nu Thanh Danh | 79.2–85.0 | 85 (POTENTIAL ↔ STRONG) | eval 2 is STRONG, at exactly 85.0 | Education 30 vs 50, Technical Skills 87 vs 90 |
| VÕ THỊ PHƯƠNG KHÁNH | 66.2–70.0 | 70 (LOW ↔ POTENTIAL) | eval 3 is POTENTIAL, at exactly 70.0 | Technical Skills 65 to 80 |
| Nguyen Tram | 69.2–70.8 | 70 (POTENTIAL ↔ LOW) | eval 5 is LOW | Technical Skills 77 to 83 |

Five more resumes varied and came within 1.2 points of a threshold without crossing it: Do Thi Minh Thu (up to 84.5), Thái Kim Hoàng (down to 70.5), Nguyen Ho Mi Sa (down to 70.8), Le Ba Thuy Hang (up to 68.8) and Pham Thi Khanh Ly (down to 56.2).

Every change is in one step, and none reaches REJECT. All four are a single evaluation out of five, so a single production run has a real chance of giving the less common result for a resume near a threshold.

### 2.7 Compared with the Tech run of the same day

| | Tech (53 resumes) | CnB (35 resumes) |
|---|---|---|
| Verdict change rate | 4.7% (42/901) | **6.3% (20/315)** |
| Resumes with every Verdict stable | 51% | 54% |
| Overall Score identical | 17% | 31% |
| Overall spread, mean / median / max | 2.1 / 1.3 / 9.4 | **2.2 / 1.2 / 10.0** |
| Criterion Score spread max | 0.5 | 0.4 |
| Partial↔Strong / No↔Partial / No↔Strong | 10 / 32 / 0 | **16 / 4 / 0** |
| Flips on Standard / Nice-to-have | 21 / 21 | 20 / 0 |
| Category with the most flips | Work Experience (23) | Technical Skills (17) |
| Largest Category Score spread | Work Experience, 38 | Education, 40 |
| Must-have Rejected in all evaluations | 49 of 53 | 0 |
| Recommendation changed | 0 shown, 8 (15%) without the gate | **4 (11%) shown** |
| Failed Evaluations | 0 | 2, on 1 resume |

The overall size matches closely, while the location differs. That fits one cause acting on whichever Criteria are close to undecided in each HR RAG **(inference)**.

## 3. Why temperature 0 does not make it deterministic

### 3.1 Temperature only removes sampling

The explanation is the one in §3.1 of the Tech report: at T=0 vLLM takes the highest-scoring token, but batch composition and prefix caching can change the logits slightly, so a near-tie can flip **(inference, not isolated in either run)**.

### 3.2 One flipped token changes the whole reply

The paired reasonings look the same as on Tech. They start from the same facts and split at one judgement.

PHAN THI THUY LIEU, Education: both sides cite the blank field of study and two HR certificates and both call that strong proof of "tương đương".

- **Strong Evidence** (evals 1, 2, 3, 5): "…cung cấp bằng chứng mạnh mẽ cho thấy nền tảng học vấn và kỹ năng của ứng viên là 'tương đương'…"
- **Partial Evidence** (eval 4): "…cung cấp bằng chứng mạnh mẽ về năng lực chuyên môn tương đương…"

Only the label differs.

Nguyen Tram, "Nắm vững Luật Lao động…": the Strong reasoning (evals 1–4) argues both ways inside one reply: "…có thể coi là một phần… Ở đây, tôi đánh giá là Strong…". That shows how close to undecided this Criterion is for this resume.

### 3.3 Why only some Criteria flip

Flips sit where the resume gives no direct statement and the model must decide whether what it does show is enough **(verified in the report reasonings)**:

- **Proof of mastery from practice.** "Nắm vững Luật Lao động, BHXH, thuế TNCN" is the clearest case. The rubric's IMPLIED rule says implied evidence is Partial, and Strong needs the skill named or "a task that is that skill" (`src/prompts/evaluator_prompts.py:130`). Whether "100% compliance", "zero tax penalties" or filing tax is a task that is that skill can be argued either way. Tech has few Criteria of this kind, which would explain its smaller share of Partial↔Strong flips **(inference)**.
- **Several required parts.** "Xử lý BHXH, BHYT, BHTN; quyết toán thuế TNCN", "Tính lương, quản lý chấm công, phép năm", "Soạn thảo, quản lý HĐLĐ; hồ sơ nhân sự". The SEVERAL REQUIRED PARTS rule says some parts shown is Partial (`evaluator_prompts.py:131`), but some Strong reasonings accept a missing part. Thái Kim Hoàng's Strong side notes that BHTN and "quyết toán" are not mentioned, then counts them as covered by BHXH and tax work. The Partial side on the same resume treats the same gap as decisive.
- **"Hoặc tương đương".** The rubric treats "hoặc" alternatives as "one shown fully meets it", but it does not say which majors count as equivalent. Quản trị kinh doanh or Kinh tế và Quản lý công plus HR certificates are judged No, Partial or Strong across resumes and evaluations.
- **A vague skill line.** "Thành thạo Excel, phần mềm quản lý nhân sự" flips only No↔Partial. All 3 cases are resumes that show no HR software and at most general computer skills or Excel used for other work.

As on Tech, flips never jump No↔Strong, because numeric noise only decides between levels that are already close **(inference)**.

### 3.4 Why one flip can move the score a lot

- **Education behaves as a single Criterion.** In every listed case its Category Score equals the Criterion Score × 100 (Bui: 0.1 → 10, 0.5 → 50; Do Thi Minh Thu: 0.5 to 0.8 → 50 to 80) **(verified)**. With 4 scored Categories at 0.25 each, 40 Category points are exactly 10 Overall points. That is Bui's whole 10.0 spread, and it explains Do Thi Minh Thu's and Phan Thi Thuy Lieu's 7.5 (30 points).
- **The 5 runs inside one evaluation also disagree.** Do Thi Minh Thu's Education Criterion Score is 0.7, 0.8, 0.5, 0.6 and 0.8. The shown Verdict changes only when the majority moves, but the score moves with every run.
- **So the Verdict change rate understates the variation.** 8 of the 19 resumes with no changed Verdict still have a different Overall Score, up to 7.5 points (VO THI HONG TUYET: Education 0 or 20, Position 0 or 10). In the same way, Tran Nu Thanh Danh's change of recommendation owes 5.0 of its 5.8 spread to Education moving from 30 to 50, with no flipped Education Verdict.

### 3.5 The Failed Evaluations

Thai Thi Ny Na failed Technical Skills in evals 4 and 5 with "ran out of retries", so even the retries at T=0.5 did not rescue it. The other 34 resumes had none. Tech's 2026-10-31 run also had one resume failing repeatedly, so it may be resume-specific, but this report does not record why the replies were rejected **(inference)**. The broken-JSON logs on the compute machine would show it.

## 4. Caveats

- **The code may differ slightly from the Tech run.** Commit `0b1bb06` (2026-11-03 07:51), after the Tech report file (07:39) and before this one (16:45), added `disable_any_whitespace` to the structured output settings in `src/providers/vllm_client.py`. If the CnB run used that commit, the two runs differ in this setting. The report does not record its commit, and a file date can be the copy time rather than the run time, so this was not confirmed. That limits §2.7, including the Failed Evaluations row.
- **Different resume sets and HR RAGs.** CnB has 35 resumes and 9 Criteria per resume, and Tech has 53 and 17. With 20 flips, one Criterion moves CnB's rates by a visible amount. The gap between 6.3% and 4.7% should not be read as CnB being less stable.
- **Retries may add some sampled runs.** A failed attempt is retried at T=0.5. The report does not count retries, so a small part of the 6.3% may be sampling rather than numeric noise.
- **The batch-noise explanation is inferred, not measured,** as in the Tech report.
- **The set is not purely CnB.** One compared resume is named "HR - Pham Thi Khanh Ly".
- **Consistency is not accuracy.** This measures whether the evaluator repeats itself, not whether its Verdicts are right.

## 5. Sources

- Run report: `runs/evaluator-consistency-cnb/evaluator_consistency_report.md` (counts in §2 re-derived from it by script; the same script reproduces the Tech report's §2 counts from the Tech run).
- `docs/research/evaluator-consistency-tech-2026-11-03.md`, including its §5 sources on T=0 nondeterminism.
- `docs/adr/0009-evaluation-runs-and-temperatures.md`; `docs/adr/0012-anchored-verdict-boundaries.md`.
- `src/prompts/evaluator_prompts.py:125-136`; `src/pipelines/scoring.py:456-463`; `src/pipelines/evaluator.py:207`.
