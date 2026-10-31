# Kho tàng tục ngữ OCR: why the model misreads Vietnamese diacritics, and which model to try instead, 2026-10-31

This report compares the developer's Fixes in `vsc-project/khoTangTucNguoiNguoiViet/store/part-1/review.jsonl` with the model's answers in `answers.json` and `spans/`. It also reads the pipeline's request settings (`src/khotangtucngu/`, `src/providers/vllm_client.py`, `scripts/lib/vision_job.sh`, `scripts/lib/model_profiles.sh`) and checks candidate models against primary sources. It ends with a bake-off plan to settle the choice on our own pages.

No code was changed for this report. Claims tagged **(verified)** were checked in the repo, on the scan, or in the cited source. Claims tagged **(inference)** are my reading and still need a test. Every Fix in the log is current: each one's `answer_sha1` matches today's answer for its page, so the diff below compares like with like **(verified)**.

## TL;DR

**What the errors look like (6 fixed pages, 33 Proverb Entries, 878 words):**

- **5 distinct Vietnamese words are misread, and every one is a stacked or wavy diacritic.** *cỗ*→*cổ* (tilde read as hook, both above a circumflex), *võng*→*vồng* (tilde read as circumflex + grave), *trầu*→*trâu* and *bần*→*bận* (the grave next to a circumflex lost or moved), and *dồi*→*đôi* (bar added to d, grave dropped). All five involve the circumflex/tilde zone. No plain vowel, breve or horn letter was misread **(verified)**.
- **Each misreading is copied to every repeat of the word.** *cổ* appears 7 of 7 times on p39 and *vồng* 8 of 8 times on p40, the Correction included. *trâu* appears 3 of 3 times on p38. One reading error becomes about 20 wrong word tokens (2.3% of words). This is the "doubling down" the developer sees: within one Entry Span request, the model copies its own earlier output instead of re-reading the pixels. Temperature 0 then repeats the same answer on every rerun **(verified for the counts; the mechanism is inference)**.
- **One Source Abbreviation is hallucinated across pages.** The model writes "VCVN" as "VCSVN" on 4 separate pages (37, 40, 41, 423), and once drops the volume ("VCVN I" became "VCVN"). The assembler already flags these as `unknown_abbreviation` Warnings **(verified)**.
- **The structure is nearly right.** Only the italics boundaries in Variants and Corrections were wrong (3 Blocks on p38). Citations were folded into the proverb's `citations` field on 69 of 77 proverbs, against the prompt. The assembler accepts that, so it is harmless (`assembly.py:160`) **(verified)**.
- **The image is not the cause.** The source is a 1-bit CCITT scan at about 222 dpi (1835 × 2808 px on A4). We render it at 300 dpi grayscale, and the processor's pixel budget (`longest_edge` 16,777,216 px) does not downscale any crop. On the rendered crop, the tilde of *võng* is plainly visible on all 8 lines where the model wrote *vồng* (section 2.1) **(verified)**.

**Root causes, most likely first:**

1. **The vision path of SEA-LION v4.5 is untested and may be weakened.** Its card lists only a text dataset (`SEA-Instruct-2602`). It says post-training was "solely distillation and model merging", and it reports no OCR or document benchmark. The base Qwen3.6-27B reports OCRBench 89.4 and CC-OCR 81.2 [SEA-LION card][Qwen3.6 card] **(verified)**. Text-only distillation and merging could drift the vision–language alignment **(inference)**.
2. **A general VLM has a weak fine-glyph prior for stacked Vietnamese diacritics.** MDPBench is the only public multilingual parsing benchmark with a Vietnamese split. On it, general open VLMs trail OCR-specialised models and Gemini on Vietnamese [MDPBench] **(verified, with a caveat on how its table reads, section 3)**.
3. **Self-copying within a request, made permanent by greedy decoding** (above).
4. **A smaller contributor: `repetition_penalty: 1.05` on every request** (`src/providers/vllm_client.py:207`). vLLM applies it to tokens "in the prompt and the generated text so far" [vLLM SamplingParams]. On a verbatim-copy task, where Variants repeat the proverb's words, it pushes against correct repeats **(verified that it is set; its effect on these errors is inference)**.

Thinking is off for both phases (`cli.py:84-87`) and the reasoning field is empty in `spans/*.json`, so a reasoning chain is not overriding the image **(verified)**.

**Top recommendations:**

1. **Hybrid (recommended target).** Keep our line finder and Entry Spans. Read characters with a dedicated OCR VLM. Let the existing LLM do the Blocks and italics, then reconcile diacritics per syllable and flag disagreements as Warnings. Best open OCR candidates:
   - **PaddleOCR-VL-1.6** (0.9B, Apache-2.0, native in vLLM). Its 1.5 predecessor had the lowest Vietnamese text edit distance in MDPBench, 0.031.
   - **Chandra OCR 2** (5B, top olmOCR-bench at 85.8, top open model on a 160-page Vietnamese set). Its weights licence is restrictive.
2. **The cheapest end-to-end A/B: plain `Qwen/Qwen3.6-27B`.** It has the same architecture and serving flags as today, so it is a one-line profile. It tests cause 1 directly. **Qwen3-VL-32B-Instruct** is the alternative general VLM.
3. **Zero-cost setting changes**, worth trying in the same bake-off: drop `repetition_penalty` for the Entry Span phase. Snap Source Abbreviations to the 63 known ones (prompt list or post-check). Optionally run a 2× upscale of the crop as a variant.
4. **Use a hosted model only as a reference ceiling, not as the pipeline.** Gemini 3 Pro scores VI 85.9 on MDPBench and Gemini 2.5 Flash 89.5% on Chandra's Vietnamese table. Run it on the bake-off pages to see how much headroom exists.
5. **Decide by a bake-off on the fixed pages (section 5), not by benchmarks.** No public benchmark covers 1-bit scans of a 2002 Vietnamese dictionary with dense stacked diacritics.

## 1. What the Fixes show

### 1.1 Method

`read_fixes` and `read_answers` from the store's own `khotangtucngu/review.py` give the latest Fix and the current answer per page. Blocks were aligned by `(kind, number)`, and the `text` and `citations` fields were diffed word by word. Each substituted letter was split in NFD into base, vowel modifier (breve, circumflex, horn) and tone (grave, acute, hook, tilde, dot). The script is in the scratchpad and was not checked in. The Fixes cover PDF pages 37, 38, 39, 40, 41 and 423. Pages 36, 43–45 and 420–424 have answers but no Fix, which does not prove they are clean (`review.py` says "nobody checks every entry").

### 1.2 Numbers

| Measure | Value |
|---|---|
| Fixed pages / Proverb Entries / words in Fix text | 6 / 33 / 878 |
| Character edit rate over all aligned fields (`text` + `citations`, including the Citations moved on p38 and italics marks) | 3.3% (144 edits / 4,343 chars) |
| Wrong Vietnamese word tokens | 20 (2.3% of words) |
| Distinct misread words | 5 (*cỗ, võng, trầu, bần, dồi*) |
| Entries with a wrong Vietnamese word | 5 of 33 (15%) |
| Entries with any content error (words, Source Abbreviations, italics) | about 10 of 33 (30%) |
| Repeats of a misread word that were also wrong | 18 of 18 (*cổ* 7/7, *vồng* 8/8, *trâu* 3/3) |

### 1.3 Letter-level confusions (model → Fix)

| Model wrote | Should be | Count | What changed |
|---|---|---|---|
| ồ (o + circumflex + grave) | õ (o + tilde) | 8 | tilde read as circumflex + grave |
| ổ (circumflex + hook) | ỗ (circumflex + tilde) | 7 | tilde read as hook |
| â | ầ | 3 | grave dropped beside circumflex |
| ậ | ầ | 1 | grave read as dot below |
| ô / đ | ồ / d | 1 each | grave dropped, bar added |

In tone terms: tilde was lost 15 times (to grave 8, to hook 7) and grave was lost 5 times. Every confusion sits on a letter whose marks stack above the x-height. These are the classic hard cases for Vietnamese OCR. The 2025 survey of Vietnamese document recognition names stacked diacritics and tone marks as the main difficulty [Vietnamese DAR survey] **(verified)**.

The wrong words are real, common syllables (*vồng, cổ, trâu, bận, đôi*), though the context makes them nonsense (*hạ vồng*, *ăn trâu đỏ môi*). So the model is choosing a frequent syllable whose glyph is close to the print. It is not drawing on knowledge of the proverb, which would have given the right words **(inference)**.

### 1.4 Other errors

- **Source Abbreviations:** "VCSVN" for "VCVN" on p37, p40, p41 and p423, and "VCVN" for "VCVN I" in a Correction on p40. The prompt gives example Abbreviations but not the list of 63, and the model makes up a plausible one, the same way on every page **(verified)**.
- **Italics markup:** on p38, *Ai ăn trâu \*người ấy\* đỏ môi* should be *Ai \*ăn trầu người ấy đỏ môi\**. The Correction's *chơm/cơm* lacked asterisks **(verified)**.
- **Citations as a `citations` Block vs the proverb's `citations` field:** the model used the field on 69 of 77 proverbs. The developer split them out only on p38 and left the rest, and `assembly.py` reads both **(verified)**. This is not worth a model change.

## 2. Could the settings cause the diacritic errors?

### 2.1 Image: resolution, grayscale, crop, pixel budget

- **Source scan:** the PDF page holds one 1835 × 2808 `DeviceGray` CCITTFax (1-bit) image on a 595 × 842 pt page, which is about 222 dpi **(verified with PyMuPDF)**. Rendering at `PAGE_DPI = 300` (`settings.py`) interpolates, and grayscale adds anti-aliasing but no new detail. That is harmless.
- **Pixel budget:** SEA-LION's `preprocessor_config.json` has `patch_size` 16, `merge_size` 2 and `longest_edge` 16,777,216 px [SEA-LION preprocessor] **(verified)**. The largest crop seen, p040-L02 at 2041 × 1306 = 2.7 Mpx, is far under that, so it is not downscaled. That works out to roughly 2,600 visual tokens, each about 32 × 32 px, or about one letter of body text **(inference from the config)**. A diacritic is a few pixels inside one token. Upscaling a crop 1.5–2× gives each mark more patches. It is cheap to test, but it is not a fix on its own **(inference)**.
- **The marks are on the image:** I rendered `spans/p040-L02.json`'s box (`[168, 337, 2209, 1643]`) at 300 dpi grayscale exactly as `span_image` does. The tilde of *võng* is clear and separate from the *o* on all 8 lines where the model wrote *vồng*. So the visual evidence is there, and the model does not use it **(verified)**.
- **Crop top edge:** for an inner Entry Span, the top is `min(previous line's bottom + 2, line top)` (`pages.py:140`). *võng* is on the first line of its crop and its tilde was inside the crop. The "slightly short top border" the developer saw did not cause these errors **(verified on p40)**. It could clip a capital's mark elsewhere **(not checked)**.

### 2.2 Decoding

- **First attempt at temperature 0, `top_p` 1.0, retries at 0.3, and only on failure** (`settings.py`, `vllm_client.py:205-206`). A wrong reading comes back identical on every rerun, which is the "repeats the same mistakes" pattern. Sampling would not fix a confident misreading. It would only make it vary **(inference)**.
- **`repetition_penalty: 1.05`** (`vllm_client.py:207`) is applied to every request in the repo, this one included. vLLM penalises tokens seen "in the prompt and the generated text so far" [vLLM SamplingParams] **(verified)**. In this book a Variant repeats most words of its proverb, and verbatim copying is the job. OCR models are normally run without such penalties, though I found no card that states it **(inference)**. It cannot explain errors that repeat identically, but it adds a push against faithful copying. Set it to 1.0 for the Entry Span phase in the bake-off.
- **Self-conditioning:** the model reads a span top to bottom in one answer. After it has written *vồng* once, the strongest evidence for the next line's last word is its own earlier token, not the pixels. That is why 18 of 18 repeats share the first error. Splitting into one request per Variant would cut the propagation but multiply requests. A per-syllable OCR cross-check (section 4) catches it at the source **(inference)**.
- **Thinking is off** (`Phase(..., thinking=False)`), and `reasoning` is empty in the saved results. A thinking pass would add more text-side generation between the image and the answer. It is unlikely to improve the reading of marks, so leave it off **(inference)**.
- **The JSON schema** (`structured_outputs`) constrains the shape, not the characters. Format constraints can cost some quality [Tam et al. 2024], but nothing here points to it **(inference)**.

### 2.3 The model itself

- The SEA-LION v4.5 card calls the model "a Causal Language Model with Vision Encoder" and says early fusion "delivers good performance across ... visual tasks". It lists only `aisingapore/SEA-Instruct-2602` as training data, says post-training "consists solely of distillation and model merging", and reports only text evaluations [SEA-LION card] **(verified)**. The vision path is inherited from Qwen3.6-27B and never measured after the Vietnamese fine-tune. Its Vietnamese text skill is better, but that is the skill that would pick a plausible syllable over the printed one **(inference)**.
- Qwen3.6-27B reports OCRBench 89.4 and CC-OCR 81.2. It is Apache-2.0, served in vLLM by the same `--reasoning-parser qwen3`, and the card recommends `--language-model-only` only for text use [Qwen3.6 card] **(verified)**.

## 3. Candidate models

Vietnamese-specific public evidence is thin. These are the only per-language numbers found:

- **MDPBench** [MDPBench] (Mar 2026; 3,400 pages, 17 languages including Vietnamese; digital and photographed pages; score = 1 − normalised edit distance for text, with CDM and TEDS for formulas and tables, averaged per page). VI column from Table 2, as read from the HTML: Gemini-3-pro-preview 85.9, Kimi-K2.5 86.2, olmOCR2 84.0, Claude-Sonnet-4.6 83.1, ChatGPT-5.2 82.1, HunyuanOCR 80.6, dots.mocr 79.9, dots.ocr 79.1, PaddleOCR-VL-1.5 78.9, Qwen3.5-9B 74.0, Qwen3-VL-8B 73.4, Nanonets-OCR2-3B 66.0, PaddleOCR-VL (1.0) 66.6, DeepSeek-OCR 54.1, MinerU-2.5-VLM 46.0. Vietnamese **text** edit distance from Table 3: PaddleOCR-VL-1.5 0.031, dots.mocr 0.039, Qwen3-VL-8B 0.046, Gemini 0.050. **(verified that the paper reports these. The column-to-language mapping in the HTML table was checked against the Latin-group averages but should be re-read in the PDF before quoting further.)** The paper notes dots.mocr drifting into Chinese on Vietnamese.
- **Chandra's multilingual table** [Chandra repo], "vi" row: Gemini 2.5 Flash 89.5%, Datalab API 85.0%, GPT-5 Mini 83.6%, Chandra 1 81.6%, Chandra 2 80.4% **(verified)**. This is the vendor's own benchmark.
- **SenOCR-Vi's 160-page Vietnamese MDPBench slice** [SenOCR-Vi] (a third party): chandra-ocr-2 85.60, MonkeyOCRv2 83.20, Claude-Sonnet-4.6 83.10, SenOCR-Vi 82.83, ChatGPT-5.2 82.10, PaddleOCR-VL-1.6 80.90 **(verified)**. It is small, run by a competitor, and the page types are not stated.

None of these benchmarks has 1-bit scans, a 2002 typeface or a diacritic-specific metric. Rankings can change on our pages.

| Model | Size / VRAM (bf16, inference) | vLLM | Licence | Vietnamese evidence | Fits our structured Blocks + italics? | Verdict |
|---|---|---|---|---|---|---|
| **Qwen/Qwen3.6-27B** (base of SEA-LION) | 27B, about 54 GB weights; already fits one 96 GB card | yes, as today [Qwen3.6 card] | Apache-2.0 | OCRBench 89.4 overall; no VI split | yes, drop-in | **Run first:** isolates the SEA-LION fine-tune |
| **Qwen/Qwen3-VL-32B-Instruct** | 32B, about 66 GB; fits, less KV cache | yes (`Qwen3VLForConditionalGeneration`) [vLLM models] | Apache-2.0 | 32 OCR languages, robust to blur [Qwen3-VL card]; the 8B scores VI 73.4 / text ED 0.046 on MDPBench | yes, drop-in | Run if budget allows; a general VLM, so expect the same failure type |
| **PaddlePaddle/PaddleOCR-VL-1.6** | 0.9B, about 2 GB | yes (`PaddleOCRVLForConditionalGeneration`), plus an official vLLM server image [PaddleOCR-VL-1.6] | Apache-2.0 | 1.5: VI 78.9, best VI text ED 0.031 [MDPBench]; 1.6: 80.9 [SenOCR-Vi]; 109 languages, Vietnamese in the Latin group [PaddleOCR-VL paper] | text only, no italics markup **(inference)**; use it as the character reader | **Top OCR pick** for the hybrid |
| VietAlphaLabs/SenOCR-Vi | 0.96B (LoRA on PaddleOCR-VL-1.6), FP32 | `vllm serve` documented, not benchmarked by the author | Apache-2.0 | 82.83 on its own 160-page set | as above | Cheap extra arm; a community model |
| **datalab-to/chandra-ocr-2** | 5B (per [SenOCR-Vi]), about 10 GB | served with vLLM through `chandra_vllm` / own server; not in vLLM's named list [Chandra repo][vLLM models] | code Apache-2.0; **weights modified OpenRAIL-M**: free for research and personal use, commercial use limited | VI 80.4% (vendor), 85.60 (third party); olmOCR-bench 85.8 | HTML/Markdown/JSON with layout; may keep italics **(inference)** | Strong arm; check the licence fits a public website |
| allenai/olmOCR-2-7B-1025 | 7B (Qwen2.5-VL-7B base), about 16 GB | `vllm serve` [olmOCR-2 card] | Apache-2.0 | card tags English only; MDPBench VI 84.0 | Markdown | Worth one arm given the MDPBench VI score; renders at 1288 px long side, lower than ours |
| rednote-hilab/dots.ocr | 3B, about 6 GB | needs `--trust-remote-code` and a registration patch [dots.ocr card] | MIT | VI 79.1; dots.mocr drifts into Chinese on VI [MDPBench] | layout JSON with text | Lower priority |
| tencent/HunyuanOCR | 1B | yes (`HunYuanVLForConditionalGeneration`) [vLLM models] | see card | VI 80.6 [MDPBench] | text | Optional arm |
| DeepSeek-OCR, MinerU-2.5, Nanonets-OCR2, PaddleOCR-VL 1.0 | small | mostly yes | various | VI 46–67 [MDPBench] | — | **Skip** |
| Vintern-1B-v2 (5CD-AI) | 1B (Qwen2-0.5B + InternViT-300M) | InternVL arch | MIT | trained on Vietnamese OCR/VQA [Vintern paper]; no comparable benchmark | weak structuring | Skip for now; too small for structure, unproven on characters |
| VietOCR (pbcquoc) | VGG + Transformer, line images | no (PyTorch) | Apache-2.0 | 10M training images incl. scanned documents; 0.88 full-sequence accuracy on its own test set [VietOCR] | line text only | Good **second reader** on our line crops; ignores italics |
| Tesseract 5 `vie` / `script/Vietnamese` (tessdata_best) | CPU | no | Apache-2.0 | files exist [tessdata_best]; no recent VI benchmark found | line text only | Cheap third voter in the reconciliation |
| PP-OCRv5 Latin recogniser (`lang=vi`) | CPU/GPU, small | no | Apache-2.0 | Vietnamese is listed in the Latin model's languages [PP-OCRv5 multilingual] (read from a docs mirror) | line text only | Alternative to Tesseract |
| Gemini 3 Pro / 2.5 Flash, Claude Sonnet 4.6, GPT-5.x | hosted | — | paid API | best VI scores above | yes | **Reference ceiling** on the bake-off pages only. Sending a 2002 in-copyright book to a third-party API is a project decision |

## 4. Recommended setup: OCR for characters, the LLM for Blocks

Rationale: our structure is already good, and the errors are glyph-level. A dedicated OCR model is trained to transcribe every mark and has a smaller language prior to override the image with **(inference)**. But no OCR model emits our Block kinds, Variant italics or Correction syntax, and several do not mark italics at all. So:

1. Keep the line finder and the layout request unchanged. They are near-perfect.
2. For each Entry Span crop, get **OCR text** from PaddleOCR-VL-1.6 or Chandra 2, one vLLM server on the same GPU next to the 27B model. The 0.9B model needs about 2 GB **(inference)**. Optionally add VietOCR or Tesseract on each found line as further voters.
3. Give the Entry Span request the crop **and** the OCR text: "OCR reading of this crop, letters reliable, structure not: …". Ask for Blocks with the OCR's spelling unless the image clearly shows otherwise. This keeps italics and Block kinds with the VLM.
4. **Reconcile per syllable in code.** Align the VLM's text with each OCR text on the diacritic-stripped skeleton. Where the skeletons match but the marks differ, take the majority. On a tie, keep the VLM's reading and write a new `diacritic_disagreement` Warning naming the syllable, so the review server shows the developer where to look. That turns "the developer finds errors by reading everything" into "the developer checks flagged syllables".
5. Snap Source Abbreviations to the 63 in `front-matter.md` (put the list in the prompt, or fold this into the existing `unknown_abbreviation` check), which removes the VCSVN class.

Whether step 3 is needed, or the reconciliation of independent readings (steps 2 + 4) is enough, is a bake-off question.

## 5. Bake-off plan

**Gold set.** Pages 37–41 and 423 have Fixes now (33 entries, 878 words). That is too few to separate models by a point or two. Before the bake-off, the developer should fix about 10 more pages, so that every Block of every gold page is checked, not only the ones that looked wrong:
- 36 and 43–45 (already answered);
- 420–422 and 424;
- 3–4 pages from later letters with dense stacked tones (for example, pages starting with *Nh*, *Ng* or *Tr*).
That gives about 16 pages and about 2,500 words. Freeze the gold as a copy of `review.jsonl`.

**Metrics** (all on NFC text of aligned Blocks):
- **DER (diacritic error rate):** syllables whose diacritic-stripped skeleton matches the gold but whose marks differ, divided by gold syllables. This is the headline metric.
- **CER** and **WER** on `text`.
- **Source Abbreviation exact match**, scored on parsed Citations.
- **Italics F1**, on asterisk-marked words in Variants and Corrections.
- **Block-kind sequence match** rate.
- **Cost:** seconds per page and GPU memory, from `token_usage.jsonl` and the metrics log.

Also report DER on **unique** misreadings, counting a word misread on all its repeats once, so self-copying does not dominate.

**Running end-to-end VLM arms with the existing pipeline:**
- Add profiles to `scripts/lib/model_profiles.sh` and their keys to `MODEL_PROFILE_KEYS`, for example:
  - `qwen3.6-27b` → `MODEL="Qwen/Qwen3.6-27B"`, `VLLM_VISION=1`, `CONCURRENCY=40`, `--reasoning-parser qwen3`
  - `qwen3-vl-32b` → `Qwen/Qwen3-VL-32B-Instruct`, `VLLM_VISION=1`, `CONCURRENCY=20`
  - `serve_vision_on` already strips `--language-model-only` for vision jobs **(verified)**.
- **Important: the model is not part of an answer's stamp.** The stamp holds the PDF hash, dpi, image setting, prompt hash, user text, lines and crop (`cli.py:222-225`, `vlm_requests.is_current`). So `--model X` on the existing store would reuse SEA-LION's saved answers and send nothing **(verified)**. Per arm:
  1. Copy `store/part-1` aside.
  2. Delete `spans/pNNN-*.json` for the gold pages and keep `layout/`, so every arm reads identical crops.
  3. Run `sbatch scripts/khotangtucngu/submit.sh --part-1 --model qwen3.6-27b --pages 36-45,420-424,...`.
  4. Save `answers.json` as `answers.qwen3.6-27b.json`, then restore the store.
- Run the `repetition_penalty` = 1.0 and 2× crop upscale variants as extra arms on the best model. Each needs a temporary local edit.

**Running OCR arms:** run a small standalone script over the same crops: the `box` in each `spans/*.json`, cut with `pages.span_image`. Serve PaddleOCR-VL-1.6 with `vllm serve PaddlePaddle/PaddleOCR-VL-1.6` (or the PaddleOCR genai server image) and Chandra 2 with `chandra_vllm` on the same SLURM node. Score their raw text against the gold `text` fields concatenated per span; these arms have no Blocks, so score CER, DER and Abbreviations only. Then score the hybrid (section 4, steps 2–4) against SEA-LION alone.

**Hosted reference:** send the same crops and prompt to one hosted model (Gemini) for the gold pages only, to get the ceiling.

**Decision rule:** adopt the cheapest arm that cuts DER by at least half against SEA-LION, with no loss in Block-kind match or italics F1. If no single model does, adopt the hybrid with reconciliation Warnings.

## 6. Sources

**Models and benchmarks**

- [SEA-LION card] AI Singapore, Qwen-SEA-LION-v4.5-27B-IT model card. https://huggingface.co/aisingapore/Qwen-SEA-LION-v4.5-27B-IT
- [SEA-LION preprocessor] `preprocessor_config.json` of the same repo. https://huggingface.co/aisingapore/Qwen-SEA-LION-v4.5-27B-IT/raw/main/preprocessor_config.json
- [Qwen3.6 card] Qwen Team, Qwen3.6-27B model card. https://huggingface.co/Qwen/Qwen3.6-27B
- [Qwen3-VL card] Qwen Team, Qwen3-VL-32B-Instruct model card. https://huggingface.co/Qwen/Qwen3-VL-32B-Instruct
- [MDPBench] Li et al., "MDPBench: A Benchmark for Multilingual Document Parsing in Real-World Scenarios", arXiv:2603.28130 (2026). https://arxiv.org/html/2603.28130v1. Dataset: https://huggingface.co/datasets/Delores-Lin/MDPBench
- [PaddleOCR-VL paper] Cui et al., "PaddleOCR-VL: Boosting Multilingual Document Parsing via a 0.9B Ultra-Compact Vision-Language Model", arXiv:2510.14528. https://arxiv.org/abs/2510.14528
- [PaddleOCR-VL-1.6] PaddlePaddle, PaddleOCR-VL-1.6 model card. https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6 (1.5: https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.5; 1.0: https://huggingface.co/PaddlePaddle/PaddleOCR-VL)
- [SenOCR-Vi] VietAlphaLabs, SenOCR-Vi model card. https://huggingface.co/VietAlphaLabs/SenOCR-Vi
- [Chandra repo] Datalab, chandra (Chandra OCR 2), GitHub. https://github.com/datalab-to/chandra
- [olmOCR-2 card] Allen AI, olmOCR-2-7B-1025 model card. https://huggingface.co/allenai/olmOCR-2-7B-1025
- [dots.ocr card] rednote-hilab, dots.ocr model card. https://huggingface.co/rednote-hilab/dots.ocr
- [HunyuanOCR] Tencent Hunyuan, "HunyuanOCR Technical Report", arXiv:2511.19575. https://arxiv.org/abs/2511.19575
- [Vintern paper] Doan et al., "Vintern-1B: An Efficient Multimodal Large Language Model for Vietnamese", arXiv:2408.12480. https://arxiv.org/abs/2408.12480 (weights: https://huggingface.co/5CD-AI/Vintern-1B-v2)
- [VietOCR] pbcquoc, vietocr, GitHub. https://github.com/pbcquoc/vietocr
- [tessdata_best] Tesseract OCR, `vie.traineddata` and `script/Vietnamese.traineddata`. https://github.com/tesseract-ocr/tessdata_best
- [PP-OCRv5 multilingual] PaddleOCR docs, "PP-OCRv5 Multilingual Text Recognition" (read via the paddleocr.ai mirror). https://www.paddleocr.ai/latest/en/version3.x/algorithm/PP-OCRv5/PP-OCRv5_multi_languages.html
- [Vietnamese DAR survey] "A Survey on Vietnamese Document Analysis and Recognition: Challenges and Future Directions", arXiv:2506.05061. https://arxiv.org/html/2506.05061v1

**Inference engine**

- [vLLM models] vLLM docs, "Supported Models". https://docs.vllm.ai/en/latest/models/supported_models/
- [vLLM SamplingParams] vLLM API docs, `vllm.sampling_params` (`repetition_penalty`, `presence_penalty`). https://docs.vllm.ai/en/latest/api/vllm/sampling_params/
- [Tam et al. 2024] Tam et al., "Let Me Speak Freely? A Study on the Impact of Format Restrictions on Performance of Large Language Models". https://arxiv.org/abs/2408.02442

**In the repo**

- `vsc-project/khoTangTucNguoiNguoiViet/store/part-1/review.jsonl`, `answers.json`, `spans/p0{37..41}-*.json`, `spans/p423-*.json`, `warnings.json`
- `src/khotangtucngu/settings.py`, `prompts.py`, `pages.py:120-158`, `cli.py:84-87, 222-225`; `src/providers/vllm_client.py:180-215`; `src/providers/vlm_requests.py:161-163, 313-322`
- `scripts/lib/model_profiles.sh`, `scripts/lib/vision_job.sh`, `scripts/khotangtucngu/submit.sh`
- `vsc-project/khoTangTucNguoiNguoiViet/docs/adr/0001-entry-spans-from-numbered-lines.md`, `GLOSSARY.md`, `front-matter.md` (Bảng chữ tắt: the VCVN I–IV rows)
