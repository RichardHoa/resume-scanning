# Does turning on reasoning lower position bias in an LLM judge?

Researched 2026-10-05. Question from the bias suite (`src/bias/`, `scripts/checks/evaluator_bias.py`): if we set `VLLM_ENABLE_THINKING=1`, would score changes under criterion and resume-item shuffles shrink?

## Bottom line

**No published study answers this for our setup, and the closest evidence points both ways.** We have one pointwise, multi-criterion rubric judge, we shuffle criteria and resume items, and we decode at temperature 0.

- In **pairwise** judging, one controlled study found that turning on Qwen3 thinking *raised* swap consistency: 83.4% to 91.3% for Qwen3-4B. Other work shows reasoning models are still position-biased, sometimes in the *opposite* direction (they prefer the last option).
- In **multiple-choice**, reasoning cuts position bias when the model's direct-answer bias is large. When the direct-answer bias is already small (the Qwen case), reasoning raises it slightly. Inside a reasoning model, **longer reasoning traces go with more position bias**.
- In the one **rubric/pointwise** study that varied reasoning effort (GPT-OSS), the bias was **non-monotone in effort and model-specific**.
- **Thinking at temperature 0 is off-label for every model we would toggle.** Their cards recommend sampling at T=0.6–1.0, and Qwen3 says "DO NOT use greedy decoding". Long traces also magnify numerical non-determinism. A thinking-on run could therefore show *more* score movement under shuffles even if the true order effect fell, unless we measure the same-order noise floor separately.

Practical reading: treat "reasoning lowers our position bias" as an **untested hypothesis**, with a plausible upside for models whose non-thinking order bias is large. Permutation averaging and evidence-first output are better-evidenced ways to cut order sensitivity, and they don't depend on that hypothesis. The experiment in the last section would settle it.

---

## 1. Direct comparisons: reasoning on vs. off, position bias measured

### 1a. Pairwise LLM-as-a-judge

- **Thinking improved swap consistency for Qwen3-4B on RewardBench.** Flipping the A/B order, position consistency averaged 83.36 without thinking and 91.27 with it. By category: Chat 95.25→95.25, Chat-Hard 72.81→80.04, Safety 88.92→93.38, Reasoning 76.44→96.40 (Table 2). This was one model (4B), pairwise, 1000 sampled items, and the authors used **sampled decoding** (non-thinking T=0.7/top-p 0.8, thinking T=0.6/top-p 0.95), not greedy. — *Explicit Reasoning Makes Better Judges: A Systematic Study on Accuracy, Efficiency, and Robustness*, Jayarao, Gupta, Varshney, Dwivedi, 2025, https://arxiv.org/abs/2509.13332
- **Reasoning models are still position-biased, and they lean to the *last* position.** Comparing DeepSeek-R1 and R1-70B with GPT-4o, Llama-3.3-70B and DeepSeek-V3 on preference (DPO) data and MMLU-Pro facts, the authors report "LRMs consistently favor options presented in the last position". The non-reasoning models in the same tables tended to favor the first position (e.g., GPT-4o accuracy 0.84 with the correct answer in A vs 0.70 in B on preference data). LRMs were more robust on factual items than on preference items. They also found a "superficial reflection bias": inserting text like "wait, let me think about it" shifts LRM preference toward later content. Decoding T=0.7. — *Assessing Judging Bias in Large Reasoning Models: An Empirical Study*, Q. Wang, Lou, Tang, Chen, Zhao, W. Zhang, Song, He, 2025, https://arxiv.org/abs/2504.09946
- **Thinking alone did not remove position inconsistency even in an RL-trained thinking judge.** Even with both-order training data and consistency rewards, the authors write: "our best Pairwise-J1 model still suffers from a significant fraction of inconsistencies (up to 20%)". Their **pointwise** J1 variant had far fewer (ties "as low as 9%"). — *J1: Incentivizing Thinking in LLM-as-a-Judge via Reinforcement Learning*, Whitehouse, T. Wang, Yu, Li, Weston, Kulikov, Saha, 2025, https://arxiv.org/abs/2505.10320
- **Paired reasoning/non-reasoning judges, no direct position test.** The authors compared DeepSeek-V3 vs R1, Qwen2.5-32B-Instruct vs QwQ-32B, and Qwen3-30B-A3B Instruct vs Thinking. Reasoning judges were more accurate overall but more swayed by "superficial quality" cues such as length and concreteness. The paper's bias measurements come from BiasBench/LLMBar, and the page we read did not show a separate position-bias metric. Relevant because Qwen2.5-32B (no thinking mode) is one of our models. — *Reasoning Model Is Superior LLM-Judge, Yet Suffers from Biases*, Huang, Wu, Yang, Arase, 2026, https://arxiv.org/abs/2601.03630

### 1b. Multiple-choice (closest analogue to a fixed label set)

- **Whether reasoning helps depends on the baseline bias, and longer traces mean more bias.** The metric was the Position Bias Score (L2 distance of the answer distribution from uniform over 4 cyclic option permutations), under **greedy decoding**. On MMLU:
  - Llama-3.1-8B-Instruct: direct 0.404, CoT 0.237, R1-distill-Llama-8B 0.218. Reasoning **reduced** bias.
  - Qwen2.5-7B-Instruct: direct 0.177, CoT 0.180, R1-distill-Qwen-7B 0.214. Reasoning **slightly increased** bias.
  - DeepSeek-R1-671B: 0.019.

  Within reasoning configurations, 12 of 13 showed a positive partial correlation between trace length and PBS (0.11–0.41). Truncation probes shifted R1-Qwen-7B 16–32% toward position-preferred options. The authors' limitation: "Generalization to open-ended evaluation, pairwise judging, and ranking tasks is untested." Single author, preprint. — *More Thinking, More Bias: Length-Driven Position Bias in Reasoning Models*, X. Wang, 2026, https://arxiv.org/abs/2605.06672
- Background: option-order sensitivity in MCQ is large (13%–75% performance gaps). The authors attribute it to uncertainty between the top 2–3 choices. CoT was not tested. — *Large Language Models Sensitivity to the Order of Options in Multiple-Choice Questions*, Pezeshkpour, Hruschka, 2023, https://arxiv.org/abs/2308.11483

### 1c. Rubric / pointwise judging (closest to our task)

- **Criterion order alone moves pointwise scores. Reasoning effort did not reliably help.** This is the only study we found on *multi-criterion pointwise rubric* scoring. Judges were GPT-OSS-20B/120B, Qwen3.5-9B/27B and Gemma-3-12B/27B, on MT-Bench, Vicuna-Bench, HANNA and SummEval.
  - Criterion ordering shifted mean scores by up to 0.80 points on a 5-point scale (Qwen3.5-9B on SummEval). It flipped the top-1 candidate on 15–41% of prompts.
  - Qwen3.5 was run with **reasoning disabled**.
  - For GPT-OSS they swept reasoning effort low/medium/high. Bias was "non-monotone in effort" (e.g., GPT-OSS-20B on HANNA: χ² ≈151 at low effort, ≈43 at medium, ≈58 at high), and "more effort does not consistently improve" human correlation. They conclude both effects are model-specific.
  - A temperature sweep (0.0–1.0) left the bias roughly flat.

  — *Am I More Pointwise or Pairwise? Revealing Position Bias in Rubric-Based LLM-as-a-Judge*, Xu, Hirasawa, Kozuno, Ushiku, 2026, https://arxiv.org/abs/2602.02219
- **Résumé comparison: reasoning models were not exempt.** Twenty-two LLMs, including o1-mini, o3-mini, gemini-2.0-flash-thinking and DeepSeek-R1, chose between two CVs. Overall they picked the first-listed candidate 63.5% of the time, and 21 of 22 models showed a significant first-position preference. The exception was the reasoning model gemini-2.0-flash-thinking, which preferred the *second* candidate. No reasoning-on/off toggle within one model. — *Gender and Positional Biases in LLM-Based Hiring Decisions: Evidence from Comparative CV/Résumé Evaluations*, Rozado, 2025, https://arxiv.org/abs/2505.17049

### 1d. Explanation-first prompting (older "CoT-lite" evidence)

- **Removing the "explain first" instruction lowered swap consistency slightly.** In MT-Bench Table 9, the "short" prompt drops "Begin your evaluation … provide a short explanation" along with other lines. Consistency moved GPT-4 65.0%→62.5%, GPT-3.5 46.2%→38.8%, Claude-v1 23.8%→22.5%. This is confounded, because the short prompt removes more than the explanation. The paper's math CoT judge was not evaluated for position bias, and the authors note GPT-4's CoT "can be significantly influenced by the given answers". — *Judging LLM-as-a-Judge with MT-Bench and Chatbot Arena*, Zheng et al., 2023, https://arxiv.org/abs/2306.05685
- **Evidence-first improved agreement with humans.** Asking for evidence *before* the score ("EC, k=1") raised accuracy against human labels: GPT-4 52.7%→56.5%, ChatGPT 44.4%→52.6%. Adding order-swapping (BPC) helped further: MEC(k=3)+BPC(k=3) beat MEC(k=6), 62.5% vs 60.9% for GPT-4. The paper measures human agreement, not order sensitivity, after EC. — *Large Language Models are not Fair Evaluators*, P. Wang et al., 2023, https://arxiv.org/abs/2305.17926
- **A recent multi-strategy comparison found CoT helped accuracy for some judges.** For example, Claude Sonnet 4 gained +7.3 pp on MT-Bench. Position bias there was ≤0.04 for all five frontier judges, so position-bias reduction from CoT could not be meaningfully measured. — *Judging the Judges: A Systematic Evaluation of Bias Mitigation Strategies in LLM-as-a-Judge Pipelines*, Soumik, 2026, https://arxiv.org/abs/2604.23178

### 1e. Position-bias work that did **not** test reasoning (context only)

- Position bias in pairwise judges is systematic rather than random. It depends mostly on the judge, the task and the **quality gap** between answers, and only weakly on prompt length. — *Judging the Judges: A Systematic Study of Position Bias in LLM-as-a-Judge*, Shi, Ma, Liang, Ma, Vosoughi, 2024, https://arxiv.org/abs/2406.07791
- Pairwise position robustness varies by judge (e.g., ChatGPT 0.566 to Claude-3.5 0.832). CoT was studied as an accuracy factor, not as a position-bias moderator. — *Justice or Prejudice? Quantifying Biases in LLM-as-a-Judge*, Ye et al., 2024, https://arxiv.org/abs/2410.02736
- Long-context retrieval follows a U-shape: information in the middle is used worst. Relevant to resume items buried mid-prompt; no reasoning condition was tested. — *Lost in the Middle: How Language Models Use Long Contexts*, Liu, Lin, Hewitt, Paranjape, Bevilacqua, Petroni, Liang, 2023, https://arxiv.org/abs/2307.03172

## 2. Reasoning, temperature 0, and output variance

- **Model cards advise against greedy decoding with thinking on.**
  - Qwen3: "**DO NOT use greedy decoding**, as it can lead to performance degradation and endless repetitions". Recommended thinking settings are T=0.6, top-p 0.95, top-k 20. — Qwen3-8B model card, Qwen Team, https://huggingface.co/Qwen/Qwen3-8B
  - Qwen3.5: thinking is on by default and disabled via `chat_template_kwargs: {"enable_thinking": false}`. Recommended thinking settings for general tasks are T=1.0, top-p 0.95, presence_penalty 1.5. — Qwen3.5-27B model card, https://huggingface.co/Qwen/Qwen3.5-27B
  - Gemma 4: thinking is toggled by the `<|think|>` token in the system prompt. Recommended "across all use cases" are T=1.0, top-p 0.95, top-k 64. — Gemma 4 model card, Google, https://ai.google.dev/gemma/docs/core/model_card_4
  - GLM-4.7-Flash: default evaluation settings T=1.0, top-p 0.95. T=0 is used only for τ²-Bench. — GLM-4.7-Flash model card, Z.ai, https://huggingface.co/zai-org/GLM-4.7-Flash

  We did not verify the Qwen3.6/3.8, SEA-LION v4.5 or Muse-Glimmer cards. Our profiles note SEA-LION v4.5 is a Qwen3.6 fine-tune and Muse-Glimmer cannot disable reasoning. Qwen2.5-32B-Instruct has no thinking mode, so it cannot be part of an on/off comparison.
- **Long reasoning traces amplify numerical non-determinism under greedy decoding.** DeepSeek-R1-Distill-Qwen-7B in bf16 with greedy decoding showed up to 9% accuracy variation and up to 9,000-token differences in response length when only batch size, GPU count or GPU type changed. The authors trace this to floating-point non-associativity compounding over long generations. — *Understanding and Mitigating Numerical Sources of Nondeterminism in LLM Inference*, Yuan et al., 2025, https://arxiv.org/abs/2506.09501
- **"Deterministic" settings are not deterministic even without reasoning.** Across five LLMs, eight tasks and 10 runs, accuracy varied by up to 15%. — *Non-Determinism of "Deterministic" LLM Settings*, Atil et al., 2024, https://arxiv.org/abs/2408.04667

**Implication:** vLLM with continuous batching at concurrency 15–200 changes batch composition between requests. So with thinking on, part of any score change between two orderings could be run-to-run noise rather than an order effect. This is an inference from the two papers above; none of them measured it on our models.

## 3. Mitigations that do not depend on reasoning

- **Swap-and-check:** call twice with the order swapped and declare a tie if the results disagree. — Zheng et al. 2023 (above).
- **Permutation averaging:**
  - Balanced Position Calibration averages scores across orders. — P. Wang et al. 2023 (above).
  - Permutation self-consistency for listwise ranking aggregates shuffled rankings, with gains of up to 7–18% (GPT-3.5) and 8–16% (LLaMA-2-70B). — *Found in the Middle: Permutation Self-Consistency Improves Listwise Ranking in Large Language Models*, Tang, Zhang, Ma, Lin, Ture, 2023, https://arxiv.org/abs/2310.07712
  - For rubric judges, balanced cyclic permutation with only 3 orderings recovered about 70% of the gain from 10. However, "Permutation helps human agreement only when the judge is strongly biased to begin with." — Xu et al. 2026 (above).
- **Removing order by construction**, e.g. scoring each criterion or option in its own call. This cut MCQ flip rate roughly in half for GPT-4.1-mini but *lowered* accuracy. Lower order sensitivity does not by itself mean better judgments. — *Accuracy and Order Sensitivity Diverge Under Label-Free Strategies*, Hanna, Feng, 2026, https://arxiv.org/abs/2608.11947
- **Pointwise over pairwise:** pointwise J1 was far more position-consistent than pairwise J1. — Whitehouse et al. 2025 (above).

## 4. How well this applies to our repo

| Our setup | Literature | Fit |
|---|---|---|
| Pointwise, many criteria in one prompt, 3-level verdict per criterion, score = mean | Mostly pairwise (1a) or 4-option MCQ (1b). Only Xu et al. 2026 is multi-criterion pointwise. | **Weak.** The one close study did not toggle thinking on Qwen3.5; it only swept GPT-OSS effort. |
| We shuffle criteria **and** resume items | Studies shuffle answers or options, not evidence inside the evaluated document. "Lost in the Middle" is the nearest analogue for resume items. | **Weak.** |
| Temperature 0, top-p 0.95, vLLM batching | Pro-reasoning judge result (Jayarao et al.) used T=0.6/0.7. MCQ length result (X. Wang) used greedy. Model cards advise against greedy with thinking. | **Mismatch.** A thinking-on, T=0 condition is off-label. |
| Models: Qwen3.5/3.6/3.8, Gemma 4, GLM-4.7-Flash, SEA-LION v4.5 (togglable); Qwen2.5-32B (no thinking); Muse-Glimmer (always reasons) | Closest are Qwen3-4B (thinking helped pairwise consistency) and Qwen2.5-7B → R1-distill (reasoning slightly hurt MCQ PBS). | Partial. Direction may differ per model family, as with Llama vs Qwen in X. Wang 2026. |
| Output schema in `src/prompts/evaluator_prompts.py` emits `verdict` **before** `evidence_quote`, and `reasoning_summary` last | P. Wang et al. 2023 found that putting the conclusion first ("VANILLA") was worse than evidence-first. | **Directly relevant.** Reordering fields to evidence → verdict is a cheap CoT-like variant that doesn't need thinking mode. |

Speculation, labeled as such: thinking makes the model enumerate criteria in its own order and re-read the resume, so it *might* dampen first/last-position effects. The MCQ length result and the LRM "last-position" result suggest it could also add a recency effect tied to what the trace looked at last.

## 5. Experiment that would settle it here

Run on the existing bias suite, reusing the same permutation sets per resume (fixed seeds) so every condition sees identical inputs.

**Models:** every togglable model (Qwen3.5-35B-A3B, Qwen3.6-35B-A3B, Qwen3.8-27B, Gemma-4-26B-A4B / 31B, GLM-4.7-Flash, SEA-LION v4.5). Muse-Glimmer gets an effort sweep (low vs high) as a within-model dose test. Qwen2.5-32B is the non-reasoning reference.

**Conditions (per model):**
1. Thinking off, T=0. This is today's baseline.
2. Thinking on, T=0. This isolates thinking from decoding settings.
3. Thinking on, at the card-recommended sampling settings. This is the setting the model was tuned for.
4. Thinking off, T=0, with the **evidence-first schema** (`evidence_quote` before `verdict`). This is the cheap alternative.
5. *(Optional)* Condition 1 with 3-ordering balanced permutation averaging. This is the mitigation ceiling.

**Noise floor (essential):** for each condition, repeat a subset of *identical* prompts (same order) about 5× under the production concurrency. Report order sensitivity as across-order variance **minus** same-order variance. Without this, condition 2/3 non-determinism will look like position bias.

**Metrics:**
- Per (resume, criterion): verdict flip rate across permutations.
- Per resume: range and SD of the averaged score across permutations.
- A positional effect: regress verdict level on the criterion's position (and on the resume item's position), with resume × criterion fixed effects. This separates "unstable" from "biased toward early/late".
- For thinking conditions, log reasoning-token count and test whether flips correlate with trace length. This replicates X. Wang 2026 in our setting.
- JSON failure and truncation rate. Thinking can consume `max_tokens`.

**Validity check:** score a small human-labeled set (e.g. 30–50 resume × criterion verdicts) under each condition. Lower order sensitivity is only worth having if accuracy holds (Hanna & Feng 2026; Xu et al. 2026).

**Analysis:** compare conditions paired on (resume, criterion, permutation), with bootstrap CIs over resumes. Decide per model, since the literature shows the direction can flip between model families.

**Decision rule (suggested):** adopt thinking for a model only if condition 3 beats condition 1 on noise-corrected flip rate, with non-overlapping CIs, *and* does not lose accuracy on the labeled set. Also compare it against condition 4 and condition 5, which may give most of the benefit at a fraction of the token cost.
