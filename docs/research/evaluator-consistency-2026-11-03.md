# Evaluator consistency at temperature 0: how unstable the model still is, 2026-11-03

This report reads the run `runs/evaluator-consistency-tech` (report file dated 2026-11-03 07:39, made after commit `ec41e52` switched every Category run to temperature 0, ADR 0009) and records how much the evaluator still varies on identical input. It is a reference measurement. No code or rubric change is proposed or planned.

Earlier runs, for comparison: `docs/research/evaluator-consistency-2026-10-31.md` (runs 2–5 sampled at T=0.5, majority-vote scoring) and the 2026-11-02 baseline quoted in ADR 0009.

Claims tagged **(verified)** were counted from the report or checked in the code. Claims tagged **(inference)** are my reading and were not measured in this run.

## TL;DR

- **Same resume, same extraction, same HR RAG, every run at T=0, and the result still varies.**
  - 26 of 53 resumes (49%) got a different Verdict on at least one Criterion across 5 Repeat Evaluations.
  - 42 of 901 (resume, Criterion) Verdicts changed (**4.7%**).
  - 44 of 53 Overall Scores (83%) were not identical across the 5 Repeat Evaluations. Mean spread 2.1 points, median 1.3, largest **9.4**.
- **No Match Recommendation changed, but that mostly says the JLPT N2 Must-have is reliable.** 49 of 53 resumes were Must-have Rejected in all 5 Repeat Evaluations, which hides their score. If the gate were not there, **8 of 53 resumes (15%)** have a score range that crosses a recommendation threshold (55 / 70 / 85), so their recommendation would have changed.
- **Why T=0 is not deterministic here:** vLLM computes each request inside a batch whose size and content change from run to run (`CONCURRENCY=40`, `--max-num-seqs 256`, `--enable-prefix-caching`). In bf16 that changes the logits slightly. Where the model's top two tokens are nearly tied, the greedy pick flips, and the rest of the reasoning, then the Verdict, follows the new path. **(inference, consistent with the evidence in §3)**
- **The instability is narrow, not random.** Every flip is between adjacent levels (No↔Partial 32, Partial↔Strong 10, never No↔Strong). 38 of the 42 flips are on 9 Criteria that need the model to infer evidence from a job title or a combined requirement.
- **Better than before:** Verdict change rate 7.5% (2026-10-31) and 8.9% (2026-11-02) → **4.7%** now. Mean Overall Score spread 3.6 → **2.1**, largest 18.8 → **9.4**.

## 1. What was run

| | |
|---|---|
| Resume set | Tech, 53 resumes, Combined Extraction, Reference Date 2015-12-31 |
| HR RAG | Software Engineer (FDI, Japanese outsourcing), Hidden Requirements none. Must-have: JLPT N2 trở lên |
| Design | 1 extraction per resume, then **5 Repeat Evaluations**. Each is a full production evaluation with 5 Category runs per Category (`DEFAULT_NUM_EVALUATIONS`), so 25 Category runs per (resume, Category) |
| Temperature | **0.0 for every Category run** (`src/pipelines/evaluator.py:207`). A retry after a failed attempt samples at `CATEGORY_EVAL_RETRY_TEMPERATURE` = 0.5 |
| Aggregation | Verdict shown = majority of the 5 runs (Partial without a majority). Criterion Score = mean Verdict score of the 5 runs (Strong 1, Partial ½, No 0). Category and Overall Scores come from the means (ADR 0009) |
| Model | `aisingapore/Qwen-SEA-LION-v4.5-27B-IT`, thinking off (`scripts/lib/model_profiles.sh:110-119`) |
| Server | vLLM, `--max-num-seqs 256 --enable-prefix-caching --enforce-eager`, `CONCURRENCY=40` in-flight requests (`scripts/lib/vllm_utils.sh:133-145`, `src/core/config.py:183-184`) |
| Failed Evaluations | 0. Scanned or failed extractions skipped: 0 |

## 2. The numbers

### 2.1 Headline

| Metric | Value |
|---|---|
| Resumes compared | 53 |
| Resumes with every Verdict stable | 27 (51%) |
| Resumes with any Verdict changed | 26 (49%) |
| Verdict change rate | **42 of 901 (4.7%)** |
| Match Recommendation changed | 0 |
| Must-have Rejection changed | 0 |
| Overall Score identical in all 5 | 9 (17%) |
| Overall Score spread, mean / median / max | **2.1 / 1.3 / 9.4** (Tong That Tung_.Net) |
| Criterion Score spread (0–1), mean / max | 0.025 / 0.5 |

### 2.2 Distribution of Overall Score spread (max − min over 5 Repeat Evaluations)

| Spread | Resumes |
|---|---|
| 0 | 9 |
| > 0 to 1 | 14 |
| > 1 to 2 | 9 |
| > 2 to 5 | 15 |
| > 5 to 9 | 5 |
| > 9 | 1 |

The six resumes above 5 points:

| Resume | Overall Scores (eval 1–5) | Spread | Verdicts changed |
|---|---|---|---|
| Tong That Tung_.Net | 67.8, 74.0, 71.5, 70.2, 77.2 | 9.4 | 2 |
| Mang Vien Tung_Full Stack | 73.0, 70.8, 70.0, 77.0, 75.0 | 7.0 | 2 |
| Nguyen Huy Binh_PHP | 38.2, 34.8, 35.2, 31.5, 36.5 | 6.7 | 2 |
| Le Chanh Dao_NodeJS | 75.8, 69.8, 74.8, 74.5, 71.8 | 6.0 | 3 |
| Bui Minh Duc_Full Stack | 88.0, 86.2, 92.0, 87.5, 90.5 | 5.8 | 2 |
| Le Duc Ngo_PHP | 56.8, 51.0, 56.0, 51.0, 53.5 | 5.8 | **0** |

### 2.3 Verdict changes per resume

| Changed Verdicts | Resumes |
|---|---|
| 0 | 27 |
| 1 | 15 |
| 2 | 7 |
| 3 | 3 |
| 4 | 1 (LY Trung Huy_Javascript) |

### 2.4 What kind of flips

| | Count |
|---|---|
| No Evidence ↔ Partial Evidence | 32 |
| Partial Evidence ↔ Strong Evidence | 10 |
| No Evidence ↔ Strong Evidence | **0** |
| Split 4-vs-1 across the 5 Repeat Evaluations | 20 |
| Split 3-vs-2 | 22 |

| By Importance | Flips |
|---|---|
| Must-have | 0 |
| Standard | 21 |
| Nice-to-have | 21 |

| By Category | Flips | Category Score spread where it varied, mean / max |
|---|---|---|
| Work Experience & Project Relevance | 23 | 10.7 / **38** (30 resumes) |
| Technical Skills & Competencies | 17 | 3.1 / 10 (30 resumes) |
| Position & Seniority Match | 1 | 9.0 / 10 (5 resumes) |
| Education & Certifications | 1 | 20.0 / 20 (2 resumes) |

### 2.5 Least stable Criteria

| Category | Criterion | Resumes where the Verdict differs | Rate |
|---|---|---|---|
| Work Experience | Viết code theo coding convention, tham gia code review | 11 / 53 | **20.8%** |
| Work Experience | Làm việc trực tiếp với BA/PM để phân tích yêu cầu, thiết kế giải pháp kỹ thuật | 7 / 53 | 13.2% |
| Work Experience | (BrSE) Làm cầu nối kỹ thuật giữa team VN và khách hàng Nhật | 5 / 53 | 9.4% |
| Technical Skills | Hiểu framework phổ biến theo stack | 3 / 53 | 5.7% |
| Technical Skills | Phối hợp QA để fix bug, đảm bảo chất lượng trước khi release | 3 / 53 | 5.7% |
| Technical Skills | UML cơ bản | 3 / 53 | 5.7% |
| Technical Skills | Phát triển, kiểm thử và bảo trì ứng dụng web/mobile | 2 / 53 | 3.8% |
| Technical Skills | English level: đọc hiểu tài liệu kỹ thuật | 2 / 53 | 3.8% |
| Technical Skills | Nắm OOP | 2 / 53 | 3.8% |
| Education | Tốt nghiệp CĐ/ĐH ngành CNTT… | 1 / 53 | 1.9% |
| Position | Kinh nghiệm 3 năm trở lên (Junior-Mid) | 1 / 53 | 1.9% |
| Technical Skills | PM tool (Jira/Trello...) | 1 / 53 | 1.9% |
| Technical Skills | Biết sử dụng công cụ quản lý code (Git/SVN) | 1 / 53 | 1.9% |

The top 3 Criteria account for 23 of the 42 flips (55%).

### 2.6 How close the variation came to changing a decision

The Must-have gate fixed the outcome for 49 of 53 resumes, whatever their score. The 4 resumes that were ranked kept their recommendation: Nguyen Chi Nhan (STRONG_MATCH, 89.5–89.8), Nguyen Anh Tho (POTENTIAL_MATCH, 73.0–73.5), Tran Vinh Trung (POTENTIAL_MATCH, 70.8 in all 5) and Le Xuan Hien (REJECT, 46.8 in all 5).

Without the gate, these 8 resumes have a score range that crosses a threshold (`MATCH_THRESHOLDS`, `>=`, `src/pipelines/scoring.py:457-464`) **(verified)**:

| Resume | Score range | Threshold crossed |
|---|---|---|
| Tong That Tung_.Net | 67.8–77.2 | 70 (LOW ↔ POTENTIAL) |
| Le Chanh Dao_NodeJS | 69.8–75.8 | 70 |
| Bach Van Tuan_NodeJS | 69.2–71.8 | 70 |
| Le Duc Ngo_PHP | 51.0–56.8 | 55 (REJECT ↔ LOW) |
| Ninh Huu Nam_IOS | 80.0–85.0 | 85 (POTENTIAL ↔ STRONG) |
| Lam Kim Tinh_BrSE | 82.5–85.8 | 85 |
| Duong Hoang Nhut_NodeJS | 84.2–86.8 | 85 |
| Nguyen Thanh_NodeJS | 84.0–86.2 | 85 |

So "0 Match Recommendations changed" should not be read as "the score is stable enough to rank on". For a resume that passes the gate and scores within a few points of a threshold, re-running can change its recommendation.

### 2.7 Compared with earlier runs (same 53 Tech resumes)

| Run | Category runs | Scoring | Verdict change rate | Stable resumes | Overall spread mean / max | Recommendation changed |
|---|---|---|---|---|---|---|
| 2026-10-31 | run 1 T=0, runs 2–5 T=0.5 | majority Verdict | 7.5% (68/901) | 14 | 3.6 / 18.8 | 1 |
| 2026-11-02 (ADR 0009 baseline) | run 1 T=0, runs 2–5 T=0.5 | mean | 8.9% | — | — | — |
| **2026-11-03 (this run)** | **all T=0** | **mean** | **4.7% (42/901)** | **27** | **2.1 / 9.4** | **0** |

Making every run greedy roughly halved the flips. What is left is the variation T=0 cannot remove.

## 3. Why temperature 0 does not make it deterministic

### 3.1 Temperature only removes sampling

At T=0 vLLM takes the highest-scoring token at each step (greedy decoding). That is deterministic only if the logits are bit-identical every time, and on this server they are not **(inference, from how vLLM batches)**:

- **Batch composition changes every run.** Up to 40 requests are in flight at once (`CONCURRENCY=40`), and vLLM's continuous batching packs whatever is waiting into each step (`--max-num-seqs 256`). The same prompt is computed alongside different requests, in a batch of a different size, each time.
- **GPU kernels are not batch-invariant.** Matmul and attention kernels pick their tiling and reduction order by batch shape. Floating-point addition is not associative, so a different order gives slightly different results, and bf16 has few bits to absorb that. Thinking Machines got 80 distinct completions from 1,000 T=0 runs of one Qwen3 prompt for this reason [Thinking Machines].
- **Prefix caching adds another path.** With `--enable-prefix-caching`, a prompt whose prefix is already cached skips part of the prefill, and the cached and freshly computed KV values can differ in the last bits.
- **The fix is not available for this model.** vLLM's batch-invariant mode (`VLLM_BATCH_INVARIANT=1`) is rejected for the Gated DeltaNet layers that this Qwen3.6-based model uses, and the PR adding support is still open (see the 2026-10-31 report, §2.2 and R6) [vLLM #42960, #45819].

### 3.2 One flipped token changes the whole reply

The schema has the model write evidence → reasoning → Verdict. Once one token in the reasoning changes, everything after it is a different generation, and the Verdict is decided by that new reasoning. The paired reasonings in the report look like this: they start from the same facts and split at one word choice.

Tong That Tung_.Net, "Làm việc trực tiếp với BA/PM…":

- **No Evidence** (evals 1, 3, 4): "…Theo quy tắc đánh giá, ngữ cảnh (chức danh) mà không có mô tả hoạt động cụ thể được coi là không có bằng chứng."
- **Partial Evidence** (evals 2, 5): "…Chức danh 'Analyst' có thể là một hoạt động liên quan (related activity)…"

Nguyen Huy Binh_PHP, "Viết code theo coding convention, tham gia code review": the Partial reasoning (evals 1, 3, 5) and the No Evidence reasoning (evals 2, 4) say the same thing, that the resume "hoàn toàn không nhắc đến" coding convention or code review. Only the label differs.

### 3.3 Why only some Criteria flip

Numeric noise only changes the result where the model is close to undecided. The flips sit on Criteria where the resume gives no direct evidence and the model has to decide whether a job title or a nearby activity counts **(verified in the report reasonings)**:

- **Inference from a title.** "Team Leader" for code review, "Analyst" or "Designer" for working with a BA/PM. The rubric's "title without an activity is No Evidence" and "related activity is Partial" rules both seem to apply.
- **Combined requirements.** "coding convention **and** code review", "BA/PM **and** analysis **and** design", "develop, test **and** maintain". When only part is shown, either adjacent level can be argued.

That is why flips never jump No↔Strong (0 of 42), why the Must-have (JLPT N2, an explicit certificate) never flipped, and why clear-cut Criteria such as Git/SVN almost never flip (1 of 53).

### 3.4 Why one flip can move the score a lot

- **Small Categories.** Each of the 4 scored Categories carries 0.25 of the Overall Score (0.22 plus a share of the absent hidden_culture 0.12, `src/core/config.py:104-110`). Work Experience has only a few Criteria, so one changed Verdict is a large share of it. Tong That Tung's Work Experience scored 0, 25, 15, 12 and 38, a 38-point spread, which is about 9.5 Overall points. That is almost all of the 9.4 spread.
- **The 5 runs inside one evaluation also disagree.** A Criterion Score of 0.1 or 0.2 means 1 or 2 of the 5 greedy runs gave Partial and the rest No. For the same Criterion, Tong That Tung had Criterion Scores 0.0, 0.2, 0.2, 0.1 and 0.5. The shown Verdict only changes when the majority moves, but the score moves with every run.
- **So the Verdict change rate understates the variation.** 19 of the 27 resumes with no changed Verdict still have a different Overall Score between evaluations, up to 5.8 points (Le Duc Ngo_PHP: Education & Certifications scored 70, 50, 70, 50, 60 with the same voted Verdicts).

## 4. Caveats

- **Retries may add some sampled runs.** A run that fails validation is retried at T=0.5 (`src/pipelines/evaluator.py:207`). The report does not count retries, so a small part of the 4.7% may be sampling rather than numeric noise. The `[Eval Retry]` lines and broken-JSON logs on the compute machine would show it.
- **The batch-noise explanation is inferred, not measured.** It was not isolated by re-running at `CONCURRENCY=1` or without prefix caching. The 2026-10-31 report, §4 step 1, describes that test.
- **One job and one resume set.** 53 Tech resumes, one HR RAG, one model. Other Job Families or a different HR RAG with fewer inferential Criteria may vary less, or more.
- **Consistency is not accuracy.** This measures whether the evaluator repeats itself, not whether its Verdicts are right.

## 5. Sources

- Run report: `runs/evaluator-consistency-tech/evaluator_consistency_report.md` (counts in §2 re-derived from it by script).
- `docs/adr/0009-evaluation-runs-and-temperatures.md`; `docs/research/evaluator-consistency-2026-10-31.md`.
- [Thinking Machines] Horace He et al., "Defeating Nondeterminism in LLM Inference", Thinking Machines Lab, 2025. https://thinkingmachines.ai/blog/defeating-nondeterminism-in-llm-inference/
- [vLLM #42960] "VLLM batch_invariant mode is not supported for GDN_ATTN", GitHub issue. https://github.com/vllm-project/vllm/issues/42960
- [vLLM #45819] "[Feature] Add batch invariance support to GDN_ATTN backend", GitHub PR (open as of 2026-10-25). https://github.com/vllm-project/vllm/pull/45819
