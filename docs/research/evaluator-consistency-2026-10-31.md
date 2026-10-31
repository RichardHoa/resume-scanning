# Evaluator consistency: why Verdicts still flip, and what would fix it, 2026-10-31

This report reads the run `runs/evaluator-consistency-tech` (made by `sbatch scripts/checks/evaluator_consistency.sh --tech`, design in `.scratch/evaluator-consistency/spec.md`) against the evaluator code and primary sources. It builds on `docs/research/reasoning-and-position-bias.md` and does not repeat it. The extractor side is in `docs/research/extractor-consistency-2026-10-25.md`.

No code was changed for this report. Claims tagged **(verified)** were checked in the repo or in the cited source. Claims tagged **(inference)** are my reading and still need a test.

A correction to the brief: the model is **not** Gemma-3-based. Profile `sea-lion-v4.5-27b` serves `aisingapore/Qwen-SEA-LION-v4.5-27B-IT` (`scripts/lib/model_profiles.sh:110-119`). Its model card says it is "built upon the Qwen3.6-27B dense architecture", with "a hybrid Linear and Full Attention design" [SEA-LION card]. The Qwen3.6-27B card gives the layout as `16 × (3 × (Gated DeltaNet → FFN) → 1 × (Gated Attention → FFN))` [Qwen3.6 card]. This matters for remedy R6.

## TL;DR

**Root causes, most likely first:**

1. **Most flips come from sampling we added on purpose, not from vLLM noise.** **(verified in code)**
   - Each Repeat Evaluation runs every Category 5 times. Run 1 is greedy and runs 2–5 sample at T=0.5, top-p 0.95, with no seed (`src/pipelines/evaluator.py:203`, `src/core/config.py:154-155`, `src/pipelines/evaluator_backend.py:46`, `src/providers/vllm_client.py:202-218`).
   - HR sees the **majority** of those 5 Verdicts (`src/pipelines/scoring.py:267-270`).
   - A majority vote is a step function, so it does not average away borderline uncertainty. It turns that uncertainty into a flip. If a sampled run gives the minority Verdict only 20% of the time, the voted Verdict still differs somewhere across 5 Repeat Evaluations about 13% of the time. At 30% it is 35% (binomial model, section 2.4) **(inference from arithmetic)**.
2. **The rubric leaves the boundary cases undefined.** **(verified in report + prompt)**
   - 66 of the 68 flips are between adjacent levels: 33 Partial↔Strong and 33 No↔Partial.
   - In the flipped pairs, both sides usually cite the **same facts** in nearly the **same words** and differ only in the label.
   - The system prompt defines Partial as "partial or related match" (`src/prompts/evaluator_prompts.py:128`). It does not say how to treat implied evidence ("uses Java, so knows OOP"), a compound Criterion with some parts met, or whether an internship counts as experience.
3. **Compound Criteria.** The least stable Criterion, "Phát triển, kiểm thử và bảo trì ứng dụng web/mobile" (22.6%, 11 of its 12 flips Partial↔Strong), is the textbook Combined Requirement. Our own scrutiny prompt uses it as the example of one (`src/prompts/evaluator_prompts.py:236`), but this HR RAG still holds it as one Criterion. **(verified)**
4. **Arithmetic and rule-following inside the LLM.** **(verified in report)**
   - The largest score spread (Vo Tan Vuong, 18.8) is one Criterion going STRONG↔NO, decided by whether the run counted a 6-month internship toward "3 năm".
   - Cao Ba Loc got PARTIAL for "2 năm 9 tháng" although the prompt says a minimum not reached is always NO_EVIDENCE (`evaluator_prompts.py:131`).
5. **Small Categories magnify each flip.** **(verified in code)** Position & Seniority Match has 2 Criteria. One STRONG↔NO flip there moves the Category 50 points and the Overall Score about 12.5 points: weight 0.22 plus a 0.03 share of the absent hidden_culture weight (`src/core/config.py:104-110`, `src/pipelines/scoring.py` weight redistribution).
6. **vLLM batch nondeterminism exists but is a minor term.** **(inference)** It can only affect run 1, the one greedy run of five. It is unmeasured in our data (section 4, step 0 measures it for free). The fix the brief suggested, batch-invariant mode, is **not available for this model today**: vLLM rejects it for Gated DeltaNet layers (`VLLM batch_invariant mode is not supported for GDN_ATTN`), and the PR adding support is still open [vLLM #42960, #45819].

Ruled out or weak:

- **Long prompts.** The 11-Criterion Technical Skills call flips at 7.0% per Criterion, no worse than the 3-Criterion Work Experience call (11.9%) or the 2-Criterion Position call (6.6%).
- **Verdict before reasoning.** Already fixed: the schema forces evidence → reasoning → verdict (`evaluator_prompts.py:133, 162-185`).
- **Repetition penalty biasing the label.** All three labels appear in the system prompt, so vLLM's presence-based penalty hits them equally (section 2.3).

**Top 3 recommendations:**

1. **Score each Criterion by its expected Verdict, not its majority Verdict.** Use the mean of the 5 runs' Verdict scores (Strong 1, Partial ½, No 0), or the probabilities read from token logprobs. Keep the majority rule only for the Must-have gate.
   - Cost: ~0 tokens.
   - Effect: a 3-vs-2 split moves the score by 0.1 instead of flipping it by 0.5.
   - Evidence: the mean of the judgment distribution beat the mode in 42 of 48 settings [Wang, Zhang & Choi 2025]. G-Eval's probability weighting exists to fix the "one score dominates, many ties" failure of discrete scoring [Liu et al. 2023].
   - Touches `src/pipelines/scoring.py` (`_vote_verdict`, `_vote_criteria`, `_score_criteria`), ADR 0009 and GLOSSARY "Category Score".
2. **Anchor the rubric where the flips are.** Add explicit rules to `get_evaluator_system_prompt` (`src/prompts/evaluator_prompts.py:126-132`):
   - **implied evidence** (skill implied only by a language, tool or title) gives one fixed level;
   - **compound Criteria**: all parts shown is Strong, some parts is Partial, none is No;
   - **"related"** must name the related activity, and surrounding context is No;
   - **experience years** are computed by code from the extraction, with HR deciding whether internships count.

   Evidence: checklist decomposition raised agreement across 12 judge models by 0.45 and cut score variance [CheckEval]. Generated checklists raised LLM–human exact agreement from 46.4% to 52.2% [TICK].
3. **Split the Combined Requirements in the Tech HR RAG.** This is an HR action with no code: "Phát triển, kiểm thử và bảo trì…", "Viết code theo coding convention, tham gia code review", "Làm việc trực tiếp với BA/PM để phân tích yêu cầu, thiết kế giải pháp kỹ thuật". If HR wants to keep the lines, a later code option is a per-part checklist inside the schema, so the Verdict is computed from the parts.

Before building any of these, run **step 0 of the experiment plan**. It needs no GPU: it reads the per-run replies already saved in the run's prompt logs on the compute machine, and it separates engine noise from sampling and rubric noise.

---

## 1. What we tested

| | |
|---|---|
| Resume set | Tech, 53 resumes, Combined Extraction, Reference Date 2015-12-31 |
| Design | 1 extraction per resume, then **5 Repeat Evaluations**, each a full production `evaluate_resume` with `DEFAULT_NUM_EVALUATIONS` = 5 Category runs (`scripts/checks/evaluator_consistency.py:36, 85-89`) |
| Category runs | run 1 at T=0.0, runs 2–5 at `CATEGORY_EVAL_SAMPLE_TEMPERATURE` = 0.5, retries at 0.5 (`src/core/config.py:150-155`, `src/pipelines/evaluator.py:203-209`) |
| Other sampling | top-p 0.95 (`evaluator_backend.py:46`), `repetition_penalty` 1.05, **no `seed`**, `max_tokens` 8192, thinking off (`vllm_client.py:202-213`, `config.py:147, 194`; profile sets `VLLM_ENABLE_THINKING=0`) |
| Output constraint | vLLM `structured_outputs` JSON schema; `criterion` is an enum of the Category's exact texts, `minItems` = `maxItems` = number of Criteria; key order evidence → reasoning → verdict (`evaluator_prompts.py:162-210`, `vllm_client.py:214-218`) |
| Aggregation | per Criterion, the Verdict more than half the runs gave, else Partial (`scoring.py:267-270`); Category score from voted Verdicts (`scoring.py:283-319`) |
| Server | vLLM 0.30.0 (`requirements.txt`), `--max-num-seqs 256 --enable-prefix-caching --enforce-eager` (eager is the default, `VLLM_ENFORCE_EAGER` unset), `--max-model-len 32768`, vision on for this job (`scripts/lib/vllm_utils.sh:129-144`, `scripts/checks/evaluator_consistency.sh:116-117`) |
| Concurrency | `CONCURRENCY=40` caps in-flight requests through one semaphore (`vllm_client.py:29`, `config.py:184-185`). The script runs up to 40 Repeat Evaluations at once (`evaluator_consistency.py:48, 419`). Each resume fans out 5 Categories × 5 runs (`evaluator.py:275-277, 311-315`), so a Category's 5 runs share batches with up to 39 unrelated requests. |
| GPU | 1 × RTX PRO 6000 Blackwell 96 GB (`evaluator_consistency.sh:8`) |

## 2. Diagnosis

### 2.1 What the report shows

From `runs/evaluator-consistency-tech/evaluator_consistency_report.json` (counts re-derived by script):

| | |
|---|---|
| Resumes compared | 53 |
| Stable in all 5 Repeat Evaluations | 14 (26%) |
| Any Verdict changed | 38 (72%) |
| Verdict change rate | **68 of 901 (7.5%)** (resume, Criterion) pairs |
| Match Recommendation changed | 1 (Nguyen Anh Tho: POTENTIAL_MATCH ×4, LOW_MATCH ×1) |
| Must-have Rejected in all 5 | 48 of 53. The Tech HR RAG has "JLPT N2 trở lên" as a Must-have, so only 5 resumes are ranked at all. |
| Overall Score spread | mean 3.6, max 18.8 (Vo Tan Vuong_BrSE) |
| Failed Evaluation | Le Duy Hoang_BrSE: Technical Skills ran out of retries in evals 1, 2, 5. The previous run failed the same resume in evals 2, 3, 5, so it is resume-specific, not random. |

**Compared with the previous run** (`runs/evaluator_consistency_report.md`, 3 Category runs per evaluation): 98 flipped (resume, Criterion) pairs → 68, resumes with a change 43 → 38, mean spread 4.4 → 3.6. Going from 3 to 5 voted runs (ADR 0009) cut flips by about 30%, but did not remove them.

**Flip types** (each flipped pair, by the set of Verdicts seen across the 5 evaluations):

| Verdicts seen | Pairs |
|---|---|
| No ↔ Partial | 33 |
| Partial ↔ Strong | 33 |
| No ↔ Strong | 1 (Vo Tan Vuong, "Kinh nghiệm 3 năm") |
| No, Partial and Strong | 1 |

**How the 5 evaluations split:** 4-vs-1 in 35 pairs, 3-vs-2 in 32, 2-2-1 in 1. **None** of the reasonings shown for the flips is the no-majority fallback text (`scoring.py:273-280`), so the "Partial when no majority" rule is not what drives the flips.

**By Importance:** standard 40, nice_to_have 27, must_have 1.

**Per Criterion** (flip types, from the JSON):

| Criterion | Rate | Flip type | What the two sides disagree on |
|---|---|---|---|
| Phát triển, kiểm thử và bảo trì ứng dụng web/mobile | 22.6% | 11 Partial↔Strong, 1 No↔Partial | whether "develop web + build mobile" is enough when testing or maintenance is not stated (LY Trung Huy: Partial "không đề cập… kiểm thử… bảo trì" vs Strong "ngụ ý việc bảo trì") |
| Nắm OOP | 17.0% | 8 Partial↔Strong | whether using an OO language implies OOP. Both sides say "ngụ ý", i.e. implied (Lam Kim Tinh: Strong "bằng chứng gián tiếp nhưng mạnh mẽ" vs Partial "không nêu rõ… tường minh") |
| Phối hợp QA để fix bug… | 13.2% | 7 No↔Partial | whether "wrote test scripts" is a related match. In Nguyen Anh Tho, the No and Partial reasonings are **the same sentence** with one word changed. |
| Làm việc trực tiếp với BA/PM… | 13.2% | 4 Partial↔Strong, 3 No↔Partial | whether writing SRS/SDD as a team leader counts without a named BA/PM |
| Viết code theo coding convention, tham gia code review | 13.2% | 5 No↔Partial, 2 Partial↔Strong | whether "uses Git/SVN" or "responsible for coding" is related evidence |
| Kinh nghiệm 3 năm trở lên | 5.7% | No↔Strong, No↔Partial, Partial↔Strong | date arithmetic and whether an internship counts (Vo Tan Vuong); PARTIAL given against the stated-minimum rule (Cao Ba Loc) |

**Score-spread outliers** are one or two flips in a small Category:

- **Vo Tan Vuong (18.8):** Position 100↔50 (one Strong↔No out of 2 Criteria) plus Work Experience 0↔25.
- **Duong Nguyen Khanh Cuong and Nguyen Hoai Bao (12.6):** one flip in a 3-Criterion and a 1-Criterion Category.
- **Cao Ba Loc (12.4):** the same pattern.

### 2.2 Candidate 1: sampling and the inference engine

- **Temperature > 0: yes, by design.** Runs 2–5 sample at 0.5 (ADR 0009, `evaluator.py:203`). The consistency check goes through production code, so it measures "the spread of sampled judgements, not only vLLM's run-to-run noise" (ADR 0009, Consequences). **(verified)**
- **Seed: none per request.** `vllm_client.chat` sends no `seed` (`vllm_client.py:202-213`). vLLM V1 sets an engine seed (default 0), but the docs promise reproducibility only offline: "In online mode, you can only enable [batch invariance]" [vLLM Reproducibility]. vLLM's `SamplingParams.seed` is the per-request "Random seed to use for the generation" [vLLM SamplingParams]. **(verified)**
- **Batch nondeterminism at T=0: real in general.** Thinking Machines sampled Qwen3-235B 1,000 times at T=0 and got **80 distinct completions**, diverging at token 103. They trace it to kernels that are not batch-invariant, because "the load (and thus batch-size) nondeterministically varies". Prefix caching and chunked prefill also change the attention reduction order unless the kernels are written for it [Thinking Machines]. Our server runs with prefix caching on and 40 concurrent requests (`vllm_utils.sh:137-138`). Run 1 is therefore probably not bit-identical across Repeat Evaluations **(inference)**. It is one vote of five, though. Engine noise can only matter where the 4 sampled runs are split nearly evenly, and those are the cases sampling already makes unstable **(inference)**.
- **Batch-invariant mode is not an option for this model today.**
  - What it is: `VLLM_BATCH_INVARIANT=1` is in beta, needs NVIDIA compute capability ≥ 8.0, and is validated on listed families (Qwen3, Qwen2.5, Qwen3-VL, Llama 3, GPT-OSS…). Qwen3.5/3.6 are not on the list [vLLM Batch Invariance].
  - Why we can't use it: users report `RuntimeError: VLLM batch_invariant mode is not supported for GDN_ATTN` on Qwen3.6-35B-A3B (vLLM 0.21) and on Qwen3.8-27B (0.28) [vLLM #42960]. PR #45819, "Add batch invariance support to GDN_ATTN backend", is still **open** with a `needs-rebase` label (2026-10-25). Its latest commit reports bs=1 vs bs=16 logprobs bitwise identical for only **15 of 16** prompts [vLLM #45819].
  - Our model is a Qwen3.6-27B fine-tune with Gated DeltaNet layers [SEA-LION card, Qwen3.6 card]. I did not verify whether vLLM 0.30.0 includes the PR. Starting the server once with the flag would settle it.
  - Cost where it works: 26 s → 42–55 s for 1,000 short Qwen3-8B sequences [Thinking Machines].
- **Sampling settings vs the model card.** **(verified)**
  - Qwen3.6-27B non-thinking settings: T 0.7, top-p 0.80, top-k 20, presence penalty 1.5, repetition penalty 1.0 [Qwen3.6 card]. The SEA-LION example uses T 0.7, top-p 0.80, top-k 20, repetition penalty 1.1 [SEA-LION card].
  - Ours for runs 2–5: T 0.5 with top-p 0.95 and no top-k, which keeps a wider tail than the card's top-p 0.8 / top-k 20. That makes a minority Verdict token easier to sample **(inference)**.

### 2.3 Candidate 2: structured output and reasoning order

- **Reasoning comes before the Verdict.** The schema key order is `criterion, evidence_quotes, reasoning, verdict` and the prompt says "REASON BEFORE THE VERDICT" (`evaluator_prompts.py:133, 158-185`). This is the evidence-first fix recommended in `reasoning-and-position-bias.md` §4, and it is **already applied**. **(verified)**
- **The Verdict does not always follow from the reasoning.**
  - In the flip examples, near-identical reasoning ends in different labels (Nguyen Anh Tho QA: No vs Partial; Gia Duong Duc Minh OOP: Strong vs Partial).
  - With the reasoning held fixed, the label token is drawn from a distribution that is close to evenly split between two adjacent levels. That is a property of the rubric boundary, not of decoding order **(inference)**.
  - Format restrictions are reported to hurt LLM reasoning [Tam et al. 2024]. Our reasoning is free text inside a JSON string and the enum only constrains the label, so I don't expect much effect here **(inference, untested)**.
- **Repetition penalty: ruled out as a label bias.**
  - vLLM's `repetition_penalty` "penalizes new tokens based on whether they appear in the prompt and the generated text so far" [vLLM SamplingParams]. All three labels are in the system prompt, so all three are penalized alike from the first Criterion on **(inference from the definition)**.
  - Side note: it does penalize copying resume tokens into `evidence_quotes`, which the prompt wants verbatim, and the Qwen3.6 card uses 1.0.

### 2.4 Candidate 3: rubric ambiguity, and how the vote amplifies it

The Verdict definitions (`evaluator_prompts.py:126-132`) anchor only two cases: a stated minimum not reached, and context without the activity. Every observed boundary falls outside them:

- **implied evidence:** OOP from Java or C#; maintenance from "team lead";
- **compound Criteria with some parts met:** develop, test and maintain; code convention and review;
- **"related" activity:** test scripts → QA coordination; Git → code review;
- **counting rules:** internships, overlapping jobs.

**(verified)**

**Why a 5-run majority still flips.** Model: run 1 is greedy and gives the same Verdict A every time, and each sampled run independently gives B with probability p. The probability that the voted Verdict is not the same in all 5 Repeat Evaluations is:

| p (sampled run gives the other Verdict) | greedy = majority side | greedy = minority side |
|---|---|---|
| 0.1 | 1.8% | 23.6% |
| 0.2 | 12.9% | 63.1% |
| 0.3 | 35.4% | 87.7% |
| 0.5 | 84.3% | 84.3% |

So any (resume, Criterion) pair where a T=0.5 run disagrees with the greedy run even 1 time in 5 shows up as unstable fairly often. The check's "differs in any of 5" metric is strict, which is right for HR. This is an arithmetic model, not a measurement. Step 0 of section 4 measures p from the saved replies.

Majority voting is the self-consistency recipe [Wang et al. 2022]. There it was built to make an answer more accurate when one answer is clearly most likely, not to give a stable output when the evidence is truly borderline. Rating Roulette found LLM judges' intra-rater Krippendorff α low across runs (MT-Bench: Llama 3.1 0.265, DeepSeek-R1 0.507, Qwen 3 0.563, sampled at T 0.6). Raising runs from 3 to 5 or 10 made "no significant difference in self-reliability" [Haldar & Hockenmaier 2025]. They also found that turning sampling off lowered accuracy (Qwen 3 balanced accuracy 79.2 greedy vs 80.6 majority vote).

### 2.5 Candidate 4: long prompts and many Criteria per call

Not supported by the data. Flip rate per Criterion by Category:

| Category | Criteria | Rate |
|---|---|---|
| Technical Skills (one call) | 11 | 41 / 583 = 7.0% |
| Work Experience | 3 | 19 / 159 = 11.9% |
| Position | 2 | 7 / 106 = 6.6% |
| Education | 1 | 1 / 53 = 1.9% |

The bigger call is not worse per Criterion. The vaguer Criteria are. **(verified count; causal reading is inference)** The resume snippets are small (the Le Duy Hoang extraction is 5.6 KB), so context length is not a plausible driver here.

### 2.6 Other findings in the code

- **The 5 runs of a Category are sent at the same moment** (`evaluator.py:275-277`) and share one prefix-cached prompt, so they are batched together. vLLM's prefix caching changes the prefill path, but that only affects the greedy run's numerics, and those effects are small **(inference)**.
- **The Must-have gate is still a majority of No Evidence** (`scoring.py:192-206`). It is stable here because 48 of 53 resumes clearly lack JLPT N2. A borderline Must-have would flip a rejection, which is worse than a 0.5-point flip. Any change to scoring should keep the gate on a clear rule (recommendation R1).
- **The free text** (strengths, gaps, summary) comes from the run that agrees most with the vote (`scoring.py:300-303`), so it can mention a Verdict the vote overturned (ADR 0009). This is unrelated to flips.
- **Failed Evaluation:** Le Duy Hoang fails Technical Skills in 3 of 5 evaluations in both runs, and retries at T=0.5 do not rescue it. `score_run` rejects a reply unless every Criterion gets exactly one Verdict (`scoring.py:46-48, 72-84`). With the schema enforcing `minItems`/`maxItems` and the enum, the likely causes are a reply cut at 8,192 tokens (`finish_reason=length`) or the enum not deduplicating the same Criterion twice. `maxItems` does not forbid repeats. **(inference)** The broken-JSON logs on the compute machine will say which; they are not in this checkout.

## 3. Remedies, ranked by expected impact per cost

### R1. Expected-Verdict scoring instead of majority Verdict (high impact, ~zero cost)

**What it is.** Score each Criterion by the mean of its runs' Verdict scores instead of the score of the majority Verdict. Five runs saying 3 Strong / 2 Partial gives 0.8, not 1.0. A shift to 2 Strong / 3 Partial gives 0.7, not 0.5.

A variant reads the distribution from token logprobs. Ask vLLM for `logprobs: true, top_logprobs: 5` and, at the Verdict token position, renormalize the probabilities of the three label-start tokens. Then score Σ p(v)·score(v), which is G-Eval's formula `score = Σ p(sᵢ) × sᵢ` [Liu et al. 2023].

**Evidence.**

- G-Eval adopted probability weighting because with direct scoring "one digit usually dominates the distribution" and models output integers, giving many ties. With weighting, Spearman on SummEval was 0.514, vs 0.502 without [Liu et al. 2023].
- Taking the mean of the judgment distribution beat the mode (greedy) in **42 of 48** settings. Example: Llama-3.1-8B pointwise on RewardBench, 72.2 → 79.3 without CoT [Wang, Zhang & Choi 2025].
- Rating Roulette recommends aggregating runs rather than removing sampling [Haldar & Hockenmaier 2025].

**Expected effect (inference).** Take a Criterion whose runs split evenly between Strong and Partial. Under the vote, its score is 1.0 or 0.5, so the standard deviation (SD) between re-evaluations is 0.25. Under the mean of 5 runs, the SD is about 0.25/√5 ≈ 0.11. Category scores still move, but in small steps, and a single Criterion can no longer swing Vo Tan Vuong's Overall by 12.5.

With logprobs from the greedy run, the value is nearly deterministic, since engine noise only perturbs probabilities slightly. Caveat: CoT before the label sharpens the distribution (pointwise judgment SD .039 with CoT vs .103 without, GPT-4o) [Wang, Zhang & Choi 2025]. After our reasoning field, the label probability may sit near 0 or 1, and the reasoning itself still varies by run. So the logprob variant is a complement to averaging runs, not a replacement, until step 0 shows how peaked the distribution is.

**Cost.**

- Mean of runs: no extra tokens.
- Logprobs: no extra tokens, a slightly larger response. vLLM's default `--logprobs-mode` is `raw_logprobs`, i.e. before logit processors and temperature [vLLM engine args]. So the probabilities are not truncated by the grammar mask and must be renormalized over the three labels **(inference about the interaction with structured outputs; verify)**.

**Where it goes.**

- `src/pipelines/scoring.py`: replace `_vote_verdict` (267-270) with a per-Criterion expected score in `_vote_criteria` (283-319), and have `_score_criteria` (54-69) take a fractional score.
- Keep a displayed Verdict for HR: the majority Verdict, labeled with the split, e.g. "Mạnh (3/5)".
- Keep the Must-have Rejection as a majority of No Evidence (`scoring.py:192-206`).
- For logprobs: `src/providers/vllm_client.py` `chat()` (add `logprobs`/`top_logprobs`, return `choice["logprobs"]`), then `LLMReply` in `src/pipelines/evaluator_backend.py:27-51`, and a token-position lookup for each `"verdict": "` in `evaluator.py:205-216`.
- This changes ADR 0009's vote and GLOSSARY "Category Score"/"Criterion Points". Per the no-migration rule, old reports are simply re-run.

### R2. Anchor the rubric at the observed boundaries (high impact, low cost)

**What it is.** Add one rule per observed ambiguity to `get_evaluator_system_prompt` (`src/prompts/evaluator_prompts.py:126-132`), next to the existing two "always NO_EVIDENCE" rules. Each rule must say which level applies. The exact level is HR's choice; the point is that there is only one.

1. **Implied evidence.** If a skill is only implied by a language, framework, tool or job title (C# → OOP, "Developer" → testing), it is PARTIAL_EVIDENCE. STRONG needs the skill named, or a described task that is that skill.
2. **Compound Criteria.** For a Criterion that joins required parts, judge each part. All parts shown is STRONG, some is PARTIAL, none is NO.
3. **"Related match" for PARTIAL.** It must be a described activity of the same kind (e.g. "wrote unit tests" for "phối hợp QA"). Tools, or a process the activity usually involves (Git → code review), are context and count as NO_EVIDENCE.
4. **Counting rules for years.** Whether internships, part-time and overlapping jobs count. Better: compute months of experience in code from `work_experience[*].duration` and the Reference Date, and hand the model the number. The Vo Tan Vuong and Cao Ba Loc flips are date arithmetic and rule application, which code does deterministically.

**Evidence.**

- Decomposing criteria into binary checklist questions raised average agreement across 12 judge models by **0.45** and "reduces the score variance" [CheckEval, Lee et al. 2024].
- Checklists raised LLM–human exact agreement **46.4% → 52.2%** and human–human agreement 0.194 → 0.256 [TICK, Cook et al. 2024].
- Prometheus shows open judges matching GPT-4 (Pearson 0.897 vs 0.882) "when the appropriate reference materials (reference answer, score rubric) are accompanied" [Kim et al. 2023].
- Rating Roulette found few-shot and CoT did *not* improve self-reliability [Haldar & Hockenmaier 2025]. That points to the rubric content, not prompting style.

**Cost.** A few hundred prompt tokens per call, mostly prefix-cached. The years computation is a small deterministic function plus one line in the seniority prompt.

**Where it goes.**

- `src/prompts/evaluator_prompts.py:126-132`.
- Years: a helper in `src/pipelines/evaluator_utils.py`, feeding `extract_relevant_resume_field` for `seniority_title` (`evaluator_utils.py:28-34, 61-67`) and using `src/core/reference_date.py`.
- GLOSSARY "Verdict" lists the always-No cases, so it changes with the rules.
- The Requirement scrutiny prompt already asks HR "what counts as relevant" for years (`evaluator_prompts.py:227`). HR's answer should become the counting rule.

### R3. Split Combined Requirements, or judge their parts in the schema (high impact on the top Criteria, zero to low cost)

**What it is.**

- **Zero-code option.** HR applies the scrutiny step's split suggestions to the Tech HR RAG. The three unstable compound lines are all of the kind our prompt flags (`evaluator_prompts.py:236`, GLOSSARY "Combined Requirement").
- **Code option (if HR keeps the lines).** Give each Criterion item an optional `parts` array of `{part, evidence_quotes, met: bool}` before `reasoning`, and derive the Verdict in `score_run` from the met count. Then the model answers binary questions and the 3-level label is computed.

**Evidence.** Same as R2 [CheckEval; TICK]. Binary questions have one boundary instead of two. Wang, Zhang & Choi found Likert-2 scored best overall (Llama, mean, RewardBench 74.2 at Likert-2 vs 70.0 at Likert-5) [Wang, Zhang & Choi 2025].

**Cost.** HR's time, or slightly more output tokens per compound Criterion. Splitting also changes Importance weights, because each part becomes its own Criterion (ADR 0007).

**Where it goes.** HR RAG on the website. Code option: `CATEGORY_EVALUATION_SCHEMA` (`evaluator_prompts.py:162-185`) and `score_run` (`scoring.py:72+`).

### R4. Bring sampling settings in line with the model card, and seed each run (medium impact, zero cost)

**What it is.**

- For runs 2–5, use the card's top-p 0.80 and top-k 20 [Qwen3.6 card; SEA-LION card] instead of top-p 0.95 with no top-k. Optionally lower `CATEGORY_EVAL_SAMPLE_TEMPERATURE`.
- Drop `repetition_penalty` to the card's 1.0 for the evaluator.
- Pass a per-request `seed` (e.g. a hash of resume, Category and run index) [vLLM SamplingParams].
- Do **not** adopt presence penalty 1.5 for the judge, because it would push against repeating labels and quotes **(inference)**.

**Evidence and caveat.**

- Narrower nucleus sampling cuts the tail in which a minority Verdict lives (by definition of top-p/top-k).
- A fixed seed makes re-evaluation repeat the same sampled runs, as long as the logits don't move enough to cross a sampling threshold. Batch nondeterminism makes this only approximate **(inference)**. Seeding makes the check look stable without making the judge less uncertain, so it belongs *after* R1–R3, not instead of them.
- Lower temperature trades accuracy for stability [Haldar & Hockenmaier 2025]. ADR 0009 rejected all-greedy for this reason.

**Where it goes.** `src/providers/vllm_client.py:202-213` (`seed`, `top_k`, `repetition_penalty`), `src/pipelines/evaluator_backend.py:46` (`top_p`), `src/core/config.py:150-155`.

### R5. Make small Categories less fragile (medium impact, design decision)

**What it is.** Either have the decomposer or HR ensure each scored Category has enough Criteria, or report the Overall Score with an uncertainty band built from R1's per-Criterion means.

**Evidence.** Arithmetic from section 2.1: with 2 Criteria, one flip is 50 Category points.

**Where it goes.** HR RAG review; `src/pipelines/scoring.py` weight redistribution. Mostly addressed by R1.

### R6. Batch-invariant inference (low impact here, blocked)

**What it is.** `VLLM_BATCH_INVARIANT=1` makes outputs independent of batch composition [vLLM Batch Invariance; Thinking Machines].

**Why low.**

- It only stabilizes run 1, and runs 2–5 sample on purpose.
- It is not supported for the GDN layers in our Qwen3.6-based model [vLLM #42960]. The fix is still an open PR that is not yet fully invariant [vLLM #45819].
- It costs about 1.6–2.1× time where it works [Thinking Machines].

A cheaper way to remove most engine variance from run 1 is to send it alone or disable prefix caching. That is an experiment control, not a production setting (section 4).

**Where it goes.** `scripts/lib/vllm_utils.sh` (env var / `--enable-prefix-caching`), once vLLM supports GDN.

### Considered and not recommended now

- **Thinking mode on.** `reasoning-and-position-bias.md` covers why it is untested and off-label at T=0. Wang, Zhang & Choi add that CoT collapses the judgment distribution and often hurts [Wang, Zhang & Choi 2025].
- **More runs (7, 9…).** Rating Roulette saw no reliability gain from 3 → 5 → 10 runs [Haldar & Hockenmaier 2025]. Our 3 → 5 change cut flips by about 30%, at 5/3 the cost. R1 gets more for nothing.
- **Reference-guided judging** [Zheng et al. 2023]: the math failure rate fell 70% → 15% when the judge first solved the problem. There is no reference answer for "does this resume show OOP". The analogue here is the HR-written anchors in R2.

## 4. Experiment plan: engine nondeterminism vs sampling vs rubric

**Step 0: no GPU, from the saved run.** The prompt logs on the compute machine (`runs/evaluator-consistency-tech/prompt_logs/eval-<n>/<resume>/`) hold every Category run's raw reply.

- **(a) Engine noise.** For each (resume, Category), diff the **run-1** (T=0) replies across eval-1…5. Any difference is vLLM nondeterminism under CONCURRENCY=40 with prefix caching. Count the run-1 Verdicts that differ.
- **(b) Sampling spread.** Per (resume, Criterion), collect all 25 per-run Verdicts (5 evaluations × 5 runs). Estimate p for each flipped pair and check it against the table in §2.4.
- **(c) Simulate R1.** Recompute Category and Overall scores from the same 25 Verdicts with mean scoring, and compare the spreads with the current 3.6 / 18.8.
- **(d)** Read the Le Duy Hoang broken-JSON logs for `finish_reason` and repeated Criteria.

**Step 1: engine noise floor.** This needs a flag the check does not have yet, because the run count is fixed by the spec.

- Run Category evaluation greedy only (`num_evaluations=1`, T=0), 5 repeats, in three conditions: (i) CONCURRENCY=40 as in production; (ii) CONCURRENCY=1; (iii) CONCURRENCY=40 without `--enable-prefix-caching`.
- Try (iv) `VLLM_BATCH_INVARIANT=1` once. If the server refuses to start with the GDN_ATTN error, record that and skip it.
- Reading: flips in (i) but not (ii) mean the batch or engine is the cause. Flips in both mean the greedy decision itself is fragile, so the prompt or rubric is the cause.

**Step 2: sampling.** Production settings vs top-p 0.8 / top-k 20, and vs seeded runs, measured on the 15 resumes with flips plus 10 stable ones.

**Step 3: rubric.** Prompt with R2's anchors vs current, at production settings, on the same resumes. The main metric is the flip rate on the top 6 Criteria of §2.1.

**Validity guard.** Hand-label about 40 (resume, Criterion) Verdicts on the unstable Criteria, using the same anchors given to HR. Report agreement for each condition. Lower flip rate is worth having only if agreement holds [Haldar & Hockenmaier 2025].

**Metrics, per condition:**

- Verdict change rate, as now;
- Krippendorff's α across Repeat Evaluations, as Rating Roulette does;
- Overall Score spread, mean and max;
- for R1, the SD of the per-Criterion expected score.

Use paired comparisons on the same (resume, Criterion) with bootstrap confidence intervals over resumes.

**Decision rule.**

- If step 0(a) shows run-1 differences below about 1% of Verdicts, drop engine work (R6) entirely.
- Adopt R1 if 0(c) shows a lower spread. That needs no new run.
- Adopt R2/R3 if step 3 cuts flips on the target Criteria without losing labeled agreement.

## 5. Sources

**vLLM and the model**

- [vLLM Reproducibility] vLLM docs, "Reproducibility". https://docs.vllm.ai/en/latest/usage/reproducibility.html
- [vLLM Batch Invariance] vLLM docs, "Batch invariance". https://docs.vllm.ai/en/latest/features/batch_invariance.html
- [vLLM SamplingParams] vLLM API docs, `vllm.sampling_params`. https://docs.vllm.ai/en/latest/api/vllm/sampling_params/
- [vLLM engine args] vLLM docs, "Engine Arguments" (`--logprobs-mode`). https://docs.vllm.ai/en/latest/configuration/engine_args/
- [vLLM #42960] "VLLM batch_invariant mode is not supported for GDN_ATTN", GitHub issue (open). https://github.com/vllm-project/vllm/issues/42960
- [vLLM #45819] "[Feature] Add batch invariance support to GDN_ATTN backend", GitHub PR (open, needs-rebase as of 2026-10-25). https://github.com/vllm-project/vllm/pull/45819
- [Thinking Machines] He et al., "Defeating Nondeterminism in LLM Inference", Thinking Machines Lab, 2025. https://thinkingmachines.ai/blog/defeating-nondeterminism-in-llm-inference/
- [SEA-LION card] AI Singapore, Qwen-SEA-LION-v4.5-27B-IT model card. https://huggingface.co/aisingapore/Qwen-SEA-LION-v4.5-27B-IT
- [Qwen3.6 card] Qwen Team, Qwen3.6-27B model card. https://huggingface.co/Qwen/Qwen3.6-27B

**LLM-as-a-judge papers**

- [Wang et al. 2022] Wang, Wei, Schuurmans, Le, Chi, Narang, Chowdhery, Zhou, "Self-Consistency Improves Chain of Thought Reasoning in Language Models". https://arxiv.org/abs/2203.11171
- [Liu et al. 2023] Liu, Iter, Xu, Wang, Xu, Zhu, "G-Eval: NLG Evaluation using GPT-4 with Better Human Alignment". https://arxiv.org/abs/2303.16634 (scoring-function details read from https://ar5iv.labs.arxiv.org/html/2303.16634)
- [Wang, Zhang & Choi 2025] V. Wang, M. J. Q. Zhang, E. Choi, "Improving LLM-as-a-Judge Inference with the Judgment Distribution". https://arxiv.org/abs/2503.03064
- [CheckEval] Lee, Kim, Kim, Cho, Kang, Kang, Kim, "CheckEval: A reliable LLM-as-a-Judge framework for evaluating text generation using checklists". https://arxiv.org/abs/2403.18771
- [TICK] Cook, Rocktäschel, Foerster, Aumiller, Wang, "TICKing All the Boxes: Generated Checklists Improve LLM Evaluation and Generation". https://arxiv.org/abs/2410.03608
- [Kim et al. 2023] Kim et al., "Prometheus: Inducing Fine-grained Evaluation Capability in Language Models" (ICLR 2024). https://arxiv.org/abs/2310.08491
- [Zheng et al. 2023] Zheng et al., "Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena". https://arxiv.org/abs/2306.05685
- [Haldar & Hockenmaier 2025] "Rating Roulette: Self-Inconsistency in LLM-As-A-Judge Frameworks", Findings of EMNLP 2025. https://arxiv.org/abs/2510.27106
- [Tam et al. 2024] Tam, Wu, Tsai, Lin, Lee, Chen, "Let Me Speak Freely? A Study on the Impact of Format Restrictions on Performance of Large Language Models". https://arxiv.org/abs/2408.02442

**In the repo**

- `runs/evaluator-consistency-tech/evaluator_consistency_report.md` / `.json`
- `runs/evaluator_consistency_report.md` (previous run, 3 Category runs)
- `docs/adr/0007-*`, `docs/adr/0009-*`, `GLOSSARY.md` ("Verdict", "Category Score", "Combined Requirement")
