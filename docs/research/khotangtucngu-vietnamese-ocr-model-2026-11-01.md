# Kho tàng tục ngữ OCR Readings: which model reads Vietnamese diacritics best, to replace PaddleOCR-VL-1.6, 2026-11-01

This report follows `docs/research/khotangtucngu-ocr-model-2026-10-31.md`, which picked PaddleOCR-VL-1.6 as the OCR Reading model. It does not repeat that survey. It does four things. It checks the first 349 OCR Readings in `vsc-project/khoTangTucNguoiNguoiViet/store/part-1/` against what the pipeline does with them. It corrects the parts of the prior report that were wrong or incomplete. It looks for evidence specific to Vietnamese and to old scans, model by model, in model cards, papers, repos and licence texts. And it ends with a bake-off plan on our own pages. It also covers `hoaivannguyen/deepdoc_vietocr`, which the user asked about.

No code was changed. I read `src/khotangtucngu/{settings,pages,cli,prompts,diacritics}.py`, `scripts/khotangtucngu/submit.sh`, `scripts/lib/{vision_job,vllm_utils}.sh`, ADR 0002 and the GLOSSARY. Claims tagged **(verified)** were checked in the repo, on a rendered crop, or in the linked primary source. Claims tagged **(inference)** are my reading and still need testing. Where I found no evidence, I say so.

## TL;DR

**No public benchmark measures Vietnamese diacritic accuracy on old printed scans.** No model has a published Vietnamese character or diacritic error rate on material like ours. Benchmarks can only shortlist models. The choice has to be made on our own pages (section 6).

**Ranked recommendation:**

1. **olmOCR-2-7B-1025, FP8 (`allenai/olmOCR-2-7B-1025-FP8`). This is the main candidate to replace PaddleOCR-VL-1.6.**
   - It has the best Vietnamese score of any open model on MDPBench: 84.0, against 78.9 for PaddleOCR-VL-1.5. On olmOCR-bench "Old Scans" it scores 47.7–48.3, against 38.6 for PaddleOCR-VL-1.6.
   - It is Apache-2.0, and vLLM serves it natively as Qwen2.5-VL. Its decoder has 7B parameters, against PaddleOCR-VL's 0.3B.
   - Two weaknesses: it is trained mostly on English pages, and it is used to whole pages at a 1288 px long side, not line crops. It needs about 15% of the GPU in FP8, or a separate job.
2. **Chandra OCR 2 (`datalab-to/chandra-ocr-2`, 5B). Best accuracy evidence, but use it for the bake-off only until the licence is cleared.**
   - Best results: the top open model on a third-party 160-page Vietnamese set (85.6), and top of olmOCR-bench overall (85.8) and on Old Scans (51.1). Its plain-OCR prompt also keeps italics as `<i>`.
   - Licence: the weights use a modified OpenRAIL-M. Free use ends if "your employer, or the entity you are affiliated with" earned or raised more than $2M, unless the use is "personal use or research purposes". Columbia and Fulbright exceed that. A share-alike clause also covers the **Output**.
   - Get written permission from Datalab before Chandra's readings feed the public site.
3. **Make the reading a vote of independent readers, not one model.**
   - Add **VietOCR** (`vgg_transformer`, Apache-2.0, Vietnamese-only vocabulary) and **Tesseract 5 `vie`** (tessdata_best, with the dictionaries off). Both are cheap and run on CPU or a small GPU slice, as voters beside the VLM reader.
   - VietOCR only works on our crops if the 32 px resize is handled. Our full 111 px crop squeezed into 512×32 leaves tone marks about 2–3 px tall (section 4.1).
4. **Cheap arms to keep in the bake-off:**
   - PaddleOCR-VL-1.6 with a 2× upscale of the line (its card upscales small images 2× for spotting).
   - SenOCR-Vi, a Vietnamese LoRA on PaddleOCR-VL-1.6. It changes one model ID, but keeps the same tiny decoder.
   - Qwen3.5-9B (Apache-2.0, OCRBench 89.2, 201 languages) as a general-VLM control.
5. **Change one sentence in the Entry Span prompt now, whichever model wins.**
   - `prompts.py` tells the main model "The OCR model reads letters and diacritics well, so spell each word with the letters and diacritics its OCR Reading has". PaddleOCR-VL disagrees on about 6% of syllables, mostly through its own errors, so that sentence pulls the main model toward those errors.
   - Where the main model followed the OCR Reading, no Diacritic Disagreement is raised, so those errors are **invisible** in `warnings.json` **(inference from `diacritics.py`)**.

**Skip:**
- **Vintern-1B-v3.5:** its card's recommended decoding uses `repetition_penalty=2.5`, it uses 448 px tiles, and it has no OCR error metric.
- **EraX-VL:** no OCR metric and no vLLM recipe.
- **Surya 2.5:** Vietnamese 63.6% on Datalab's own benchmark, and the same style of licence with a $5M threshold.
- **EasyOCR:** a 2024 CRNN with no Vietnamese numbers.
- **dots.ocr / dots.mocr:** they drift into Chinese on Vietnamese pages.
- **Gemma 4:** weaker on documents than Qwen3.5.
- **deepdoc_vietocr:** it has no licence. It is stock VietOCR `vgg_seq2seq` inside RAGFlow's DeepDoc, and VietOCR itself is the useful part.

**No decoding-side constraint fixes the main error class.**
- In 349 OCR Readings, only one character falls outside the Vietnamese alphabet (the `ō` of "vōng") **(verified, script over `ocr/*.json`)**.
- Almost every error is a *valid* Vietnamese syllable swapped for another valid one (*mót→một*, *cơm→com*, *mưa→mua*, *dám→đám*). A character-set regex or a syllable lexicon would catch only `ō` and the odd invalid spelling like *cưóp* **(inference from the data)**.
- What does help is independent readers, larger crops (2× upscale), and a prompt that stops trusting one OCR model.

## 1. What the store shows

| Measure | Value |
|---|---|
| OCR Readings (lines) | 349, pages 36–45 and 420–424 (15 pages) |
| Crop size | about 2,041–2,070 × 93–115 px, median height 112 px; one outlier 538 px tall (`p036-L01`, empty answer) **(verified)** |
| Measured on 5 crops | ink band 52–85 px, x-height core about 31–48 px, ink width 650–1,680 px **(verified, PyMuPDF render of the stored `box`)** |
| Diacritic Disagreement Warnings | 121 Warnings covering 158 syllable tokens **(verified, `warnings.json`)** |
| Characters outside the Vietnamese alphabet in OCR output | 1 (`ō`) **(verified)** |

I rendered `p040-L05` at 300 dpi grayscale exactly as `span_image` does. It prints *"- Ai biết bà chúa mót đái mà hạ võng. TNVN 355"* cleanly, and the tilde of *võng* and the acute of *mót* are unmistakable. PaddleOCR-VL-1.6 answered *"… một đái mà hạ vọng."* **(verified)**. This is the frequency-prior failure from the brief: the image is not the problem.

The types of disagreement in `warnings.json` match the brief: horns and breves dropped (*cơm→com* ×7, *mưa→mua*, *như→nhu*), tones swapped for more frequent ones (*mót→một* ×5, *phấn→phần*, *thời→thòi*, *chẳng→chảng*), the đ bar flipped both ways (*đái→dái*, *đôi→dối*), and *dạ→da*. Some Warnings are the main model's fault. The Warning keeps the Blocks' spelling and only flags it.

## 2. Corrections to the prior report

- **"PaddleOCR-VL-1.5 had the lowest Vietnamese text edit distance, 0.031."** This is true, but Table 3 of MDPBench lists only **six** models: Gemini-3-pro, Qwen3-VL-8B, dots.mocr, PaddleOCR-VL-1.5, MonkeyOCR-pro-3B and PP-StructureV3. olmOCR-2, HunyuanOCR, Chandra and the closed models other than Gemini are not in it [MDPBench] **(verified)**. So "lowest" only means lowest among those six. It was the main reason for the pick, and it is weaker evidence than it looked.
- **MDPBench's Vietnamese pages are digital-born or photographed, not scanned.** The digital set comes from "publicly accessible websites" and "public digital libraries" and includes "historical archives". The photographed set re-photographs printed or on-screen documents. The paper does not give a per-language page count or analyse Vietnamese diacritics [MDPBench] **(verified)**.
- **PaddleOCR-VL is the weakest of the strong OCR models on old scans.** Its own 1.6 card reports olmOCR-bench **Old Scans 38.6** [PaddleOCR-VL-1.6]. Chandra 2 reports 51.1, dots.ocr 1.5 48.2, olmOCR 2 47.7, and Qwen3-VL-8B 37.5 [Chandra repo] **(verified)**. That benchmark's old scans are English, not Vietnamese, so this is a proxy. It does match what we see.
- **Chandra's licence is stricter than "commercial use limited".** See section 3.2. Its free-use test counts the revenue and funding of the user's employer or affiliated entity. It also carries a share-alike clause that covers Output **(verified)**.
- **"The 0.9B model needs about 2 GB."** The weights do. The 0.10 share (about 9.6 GB) is mostly KV cache and CUDA graphs. This is still right **(verified, `submit.sh` comment)**.

## 3. Candidates

### 3.1 Vietnamese-specialised recognisers

**VietOCR (pbcquoc/vietocr).**
- **What it is:** a CNN (VGG19-bn) plus a Transformer or attention-Seq2Seq decoder that reads one line image. Its vocabulary is the Vietnamese alphabet, digits and ASCII punctuation, so `ō` cannot come out.
- **Training and accuracy:** trained on "10m ảnh … ảnh tự phát sinh, chữ viết tay, các văn bản scan thực tế" (synthetic images, handwriting, real scanned documents). Full-sequence precision is 0.880 (transformer) and 0.870 (seq2seq) on its own 10M set.
- **Licence and maintenance:** Apache-2.0. The last push was 2025-01-19 (per the coordinator's check) [VietOCR] **(verified)**.
- **Gaps:** what the "scanned documents" are, and whether old print is among them, is not documented **(no evidence found)**. No public test of VietOCR on old Vietnamese print exists **(no evidence found)**.
- **Why it is still worth a vote:** its decoder is character-level and trained only on Vietnamese lines, so its prior is a Vietnamese spelling prior, not a cross-lingual one. It is a different family of model from any VLM, so its errors should be largely independent **(inference)**.

**deepdoc_vietocr (hoaivannguyen).**
- It is RAGFlow's DeepDoc split into its own repo, with PaddleOCR detection exported to ONNX, YOLOv10 layout and table models, and the recogniser swapped for stock VietOCR. `module/ocr.py` loads `Cfg.load_config_from_name('vgg_seq2seq')` with `vgg_seq2seq.pth` on CPU, and the transformer variant is commented out.
- It does no retraining and reports no benchmark. It has **no licence** (GitHub `license: null`): 40 stars, 8 commits, last push 2025-09-12 [deepdoc_vietocr] **(verified by the coordinator)**.
- We already find lines and cut crops, so its detection and layout add nothing. Without a licence its code cannot be reused. **Use VietOCR directly** (section 4.1) **(inference)**.

**AsterNet (asterxlabs/asternet-vietnamese-ocr, "2026", MIT).**
- A 10.6M-parameter CTC line recogniser with a high-pass stem "to keep small accents" and auxiliary tone and diacritic heads. Input is 32 × W.
- Its only test is 100 lines, self-reported: CER 3.45% against VietOCR's 3.85%, and WER 9.01% against VietOCR's 8.23%. It reports no diacritic metric, and its integration code is partly stub [AsterNet] **(verified)**.
- An optional fourth voter. The evidence is too thin to rank it.

**SenOCR-Vi (VietAlphaLabs).**
- A LoRA (rank 32) on PaddleOCR-VL-1.6. Only 1.26% of weights were trained, on 42k records, most of them handwriting (Viet-Handwriting-OCR-v2, 23k) and scene text (VinText, 10k), plus 2,808 private "archival" records.
- It scores 82.83 on its own 160-page MDPBench Vietnamese slice, against 80.90 for PaddleOCR-VL-1.6. It reports no diacritic metric and uses the prompt `OCR:`. It is Apache-2.0 and served with `vllm serve` [SenOCR-Vi] **(verified)**.
- The same 0.3B decoder and a handwriting-heavy LoRA make it unlikely to fix rare-syllable substitutions on print **(inference)**. Its one advantage: it is a one-string swap.

**Vintern-1B-v3.5 (5CD-AI).**
- Fine-tuned from InternVL2.5-1B (0.9B), MIT, served by vLLM as `InternVLChatModel`. vi-MTVQA 41.9, OCRBench 706, against 785 for its base. It reports no OCR error rate.
- Its card's generation config is `num_beams=3, repetition_penalty=2.5` [Vintern-1B-v3.5] **(verified)**. A penalty that high is wrong for verbatim copying.
- Its 448 px tiles would cut a 2041 × 111 line into many stretched tiles **(inference)**.
- Vintern-3B-R-beta (about 4B, MIT) is a reasoning fine-tune. Its card says "OCR performance on blurred or unclear text may be slightly affected" and points users to v3.5 for OCR [Vintern-3B-R] **(verified)**. **Skip both.**

**EraX-VL-7B-V1.5 (Qwen2-VL-7B fine-tune, Apache-2.0).** Its training data is undisclosed and it reports no OCR metric. Its only figure is VQA (VI-MTVQA 47.2), and it calls itself "NOT a typical OCR-only tool" [EraX-VL] **(verified)**. **Skip.**

**Others:** I found no Vietnamese OCR model from Zalo, VinAI, FPT or Viettel in 2025–2026 with open weights and an OCR metric **(no evidence found)**. VinAI's VinText work is scene text. Its dictionary-guided recogniser (CVPR 2021) is relevant only as a decoding idea (section 5) [Dict-guided].

### 3.2 General OCR VLMs with larger decoders

**olmOCR-2-7B-1025 (Allen AI).**
- **Model and licence:** a Qwen2.5-VL-7B base (the card lists 8B parameters, BF16) fine-tuned on olmOCR-mix-1025 and then trained with GRPO. Apache-2.0, with Ai2's Responsible Use Guidelines. An official FP8 checkpoint exists. `vllm serve allenai/olmOCR-2-7B-1025` runs natively (`Qwen2_5_VLForConditionalGeneration`) [olmOCR-2 card][vLLM models] **(verified)**.
- **Evidence:** MDPBench Vietnamese **84.0**, the best open model and above Claude Sonnet 4.6 (83.1) and ChatGPT-5.2 (82.1). Old Scans 48.3 (BF16) and 47.7 (FP8) [MDPBench][olmOCR-2 card] **(verified)**.
- **Caveats:**
  - The card tags only English.
  - Its page images are rendered at a 1288 px long side, about 110 dpi on A4. At that scale an x-height is about 11 px; ours is about 30–45 px. Downscaling the crop by about 0.5, or testing both scales, is worth an arm **(inference)**.
  - Its prompt builder (`build_no_anchoring_v4_yaml_prompt`) expects a page and returns YAML front matter. For a line, plain text after the front matter has to be parsed out **(inference)**.

**Chandra OCR 2 (Datalab, March 2026).**
- **Model and serving:** 5B, BF16, built on Qwen 3.5, so vLLM serves it natively (`Qwen3_5ForConditionalGeneration`). Datalab's own launcher uses `vllm/vllm-openai:v0.17.0` with `--mm-processor-kwargs {"min_pixels":3136,"max_pixels":6291456}`, sends temperature 0 and top_p 0.1, and renders PDFs at 192 dpi [Chandra repo][chandra-ocr-2 card] **(verified)**.
- **Prompt:** its plain-OCR prompt (`PROMPT_MAPPING["ocr"]`) is "OCR this image to HTML", allowing `<i>`, `<b>` and `<sub>`. A line answer could keep italics and subscripts, which PaddleOCR-VL cannot. The same prompt also says "Make sure the text is accurate and easy for a human to read", which leaves room for normalisation **(verified for the prompt; the effect is inference)**.
- **Evidence:**
  - Vietnamese: 80.4% on Datalab's own table, below Chandra 1 (81.6%) and Gemini 2.5 Flash (89.5%). 85.60 on SenOCR-Vi's slice.
  - Old scans: Old Scans 51.1 and olmOCR-bench overall 85.8, the best open model [Chandra repo][SenOCR-Vi] **(verified)**.
- **Licence:** the code is Apache-2.0; the weights are a modified OpenRAIL-M [Chandra licence] **(verified)**.
  - Attachment A §2 bars commercial use "(a) for any purpose if You (your employer, or the entity you are affiliated with) generated more than two million US Dollars ($2,000,000) in gross revenue in the prior year, except where Your Use is limited to personal use or research purposes". §2(b) applies the same test to funding raised.
  - §8 "Share-a-Like": "You agree to apply this License … to the Output and any derivatives".
  - §7 requires attribution "in connection with any Output".
  - Digitizing Vietnam is part of the Columbia University (Weatherhead East Asian Institute)–Fulbright University Vietnam cooperation [DV Tuoi Tre] **(verified)**. Both institutions earn well over $2M **(inference)**.
  - So use outside "research purposes" is not free, and the published text could be argued to be a derivative of Output that would have to carry OpenRAIL-M and an attribution. The bake-off is research and is fine.
  - **Production use needs Datalab's written confirmation** **(inference; not legal advice)**.

**Qwen3.5-9B / Qwen3-VL-8B (Apache-2.0).**
- Qwen3.5-9B: natively multimodal, 201 languages, OCRBench 89.2, CC-OCR 79.3 [Qwen3.5-9B] **(verified)**. Qwen3.5-9B scores Vietnamese 74.0 on MDPBench and Qwen3-VL-8B 73.4. Qwen3-VL-8B's Vietnamese *text* edit distance is 0.046, against PaddleOCR-VL-1.5's 0.031 [MDPBench] **(verified)**.
- Qwen3-VL claims OCR in "32 languages"; I could not confirm Vietnamese is among them [Qwen3-VL card] **(no evidence found)**.
- A general-VLM control arm. It shares the base family with our main model, so its errors may be correlated **(inference)**.

**Smaller or less suitable:**
- HunyuanOCR (1B, Tencent Hunyuan Community License, Vietnamese 80.6 on MDPBench, vLLM native; card recommends `repetition_penalty 1.08`) [HunyuanOCR].
- GLM-OCR (0.9B, MIT, Vietnamese 69.2) [GLM-OCR].
- dots.ocr (MIT, Vietnamese 79.1; "dots.mocr demonstrates language drift when handling Vietnamese, incorrectly recognizing it as Chinese") [MDPBench].
- MonkeyOCRv2 (83.20 on SenOCR-Vi's slice; licence and serving not confirmed from an official card).
- Gemma 4 (Apache-2.0; OmniDocBench edit distance 0.131 for 31B and 0.164 for 12B, weaker than the Qwen3.5 family) [Gemma 4].
- DeepSeek-OCR, MinerU and Nanonets score 46–67 on Vietnamese.

**None is worth an arm ahead of the above (inference).**

### 3.3 Classic engines as voters

- **Tesseract 5, tessdata_best.** `vie.traineddata` (12.4 MB) and `script/Vietnamese.traineddata` exist (HTTP 200), Apache-2.0, LSTM engine only [tessdata_best] **(verified)**.
  - Run it per line with `--psm 7` (single line) or `--psm 13` (raw line).
  - Turn the dictionaries off: `load_system_dawg=0 load_freq_dawg=0`. Tesseract's docs say "Disabling the dictionaries … should increase recognition if most of your text isn't dictionary words".
  - Keep about a 10 px border and 300 dpi input [Tesseract ImproveQuality] **(verified)**. With the dictionaries off it has no word prior that could turn *mót* into *một* **(inference)**.
  - The 2025 Vietnamese document-analysis survey says Tesseract's "accuracy remains limited due to diacritic handling and document noise", but gives no figure [Vietnamese DAR survey] **(verified)**.
- **PP-OCRv5 `latin_PP-OCRv5_mobile_rec`.** Lists `vi`, with 84.7% on a 3,111-image Latin set and no Vietnamese figure [PP-OCRv5 multilingual] **(verified)**. An alternative to Tesseract, but it comes from the same vendor family as PaddleOCR-VL **(inference)**.
- **EasyOCR.** Has `vi` (`easyocr/config.py`). It is a CRNN with CTC, Apache-2.0, last release 1.7.2 (Sept 2024), with no accuracy figures [EasyOCR] **(verified)**. Low priority.
- **Surya 2.5.** A 689M VLM. Vietnamese 63.6% on Datalab's internal benchmark. Weights under a modified OpenRAIL-M with a $5M threshold [Surya] **(verified)**. **Skip.**

### 3.4 Comparison

| Model | Params / weights | vLLM | Licence | Vietnamese evidence (source) | Old-scan evidence | Line crop fit | Verdict |
|---|---|---|---|---|---|---|---|
| PaddleOCR-VL-1.6 (today) | 0.9B (0.3B decoder) / ~2 GB | native | Apache-2.0 | 1.5: Vietnamese 78.9, text ED 0.031 among 6 models [MDPBench]; 1.6: 80.9 [SenOCR-Vi] | Old Scans 38.6 [card] | yes (element OCR) | Baseline; ~6% syllable disagreement on our lines |
| **olmOCR-2-7B-1025 (FP8)** | 8B / ~9 GB FP8, ~16 GB BF16 | native (Qwen2.5-VL) | Apache-2.0 | Vietnamese **84.0** [MDPBench] | Old Scans 47.7–48.3 | page-trained, 1288 px | **#1 replacement** |
| **Chandra OCR 2** | 5B / ~10 GB BF16 | native (Qwen3.5) | Apache-2.0 code; weights modified OpenRAIL-M ($2M affiliate test, share-alike on Output) | 80.4% (vendor), 85.6 (SenOCR-Vi slice) | **Old Scans 51.1** | page-trained, 192 dpi; keeps `<i>` | **#1 on evidence; bake-off only until licensed** |
| Qwen3.5-9B | 10B / ~20 GB | native | Apache-2.0 | Vietnamese 74.0 [MDPBench] | Qwen3-VL-8B: 37.5 | general | Control arm |
| SenOCR-Vi | 0.96B, FP32 | `vllm serve` | Apache-2.0 | 82.83 (own slice) | none | as Paddle | Cheap swap |
| VietOCR `vgg_transformer` | ~37M / ~145 MB (per AsterNet) | no (PyTorch) | Apache-2.0 | 0.88 full-line accuracy on own set | none published | **line-native, but 32 px** | **Voter**, after the resize fix |
| Tesseract 5 `vie` best | CPU | no | Apache-2.0 | none quantified | none | line-native (`--psm 7`) | **Voter**, dictionaries off |
| AsterNet | 10.6M | no (ONNX) | MIT | 100-line self-test | none | line-native, 32 px | Optional voter |
| Vintern-1B-v3.5 | 0.9B | native (InternVL) | MIT | vi-MTVQA only | none | 448 px tiles | Skip |
| HunyuanOCR, GLM-OCR, dots.ocr | 1–3B | native | Hunyuan / MIT / MIT | 80.6 / 69.2 / 79.1 | dots 1.5: 48.2 | yes | Skip (dots: drift into Chinese) |
| Surya 2.5, EasyOCR | small | Surya via vLLM | OpenRAIL-M $5M / Apache | 63.6 / none | none | — | Skip |

## 4. Fitting the candidates to our crops and GPU

### 4.1 VietOCR's 32 px resize (and deepdoc_vietocr)

VietOCR resizes every line to `image_height: 32` and clamps the width to `[32, 512]`, using LANCZOS with no aspect-preserving padding (`vietocr/tool/translate.py:resize`; `config/base.yml`: "resize image to 32 height, larger height will increase accuracy") [VietOCR] **(verified)**. On our crops:

- **Whole crop, 2041 × 111:** the vertical scale is 0.29, so the width would be 590, but it is clamped to 512, a horizontal scale of 0.25. The x-height (about 31–45 px) becomes **about 9–13 px**. A tone mark of about 8–10 px becomes **about 2–3 px**. Each character, about 29 px wide on the scan, becomes about 7 px. The image is also squeezed horizontally by about 13% **(inference from the measured crops)**. That is too little for *ỗ* against *ổ*.
- **Tight crop to the ink band plus 4 px (about 60–90 px tall):** the vertical scale is about 0.36–0.53, giving an x-height of about 14–17 px and marks of about 4–5 px. But the ink width (650–1,680 px) scales to about 350–890 px, so the 512 clamp squeezes long lines to 58% of their aspect **(inference)**.
- **Fix without retraining:**
  - Tight-crop each line to its ink rows (`find_lines` already has them), then raise `image_max_width` at inference only.
  - The CNN is fully convolutional. Height pools by 16 (32 → 2 rows) and width by 4, so the encoder sequence is W/2 tokens. The Transformer's sinusoidal position table holds `max_seq_length: 1024`, so W up to about 2,000 px fits **(verified from `config/vgg-transformer.yml`, `backbone/vgg.py`; that accuracy holds is inference)**.
  - Training lines were at most 512 px wide (at most 16:1), so the safer option is to **cut each line at word gaps into chunks of 16:1 or less** (2–3 chunks per line) and join the outputs **(inference)**.
  - Turn on `predictor.beamsearch: True` to cut greedy errors.
- **Higher `image_height` (48 or 64) needs fine-tuning.** At height 64 the CNN emits 4 rows instead of 2, which changes the encoder's sequence layout away from what the weights learned **(inference from the code)**. Fine-tuning from the pretrained weights at height 64 is supported by the config. It needs labelled lines: our reviewed Fixes, plus synthetic lines rendered in a Times-like face from the book's own vocabulary. I found no published result for that recipe on old print **(no evidence found)**.
- **Use `vgg_transformer`, not deepdoc's `vgg_seq2seq`.** The transformer is the more accurate of the two (0.880 against 0.870), and speed does not matter at about 25 lines per page.

### 4.2 GPU budget

- **Today:** the main model takes `VLLM_GPU_MEMORY_UTILIZATION=0.78` and the OCR server `VISION_OCR_GPU_SHARE=0.10`. The OCR server starts with `--max-num-batched-tokens 16384 --no-enable-prefix-caching --limit-mm-per-prompt.image 1`, plus the shared `--max-model-len 32768 --max-num-seqs 256 --enforce-eager` (`vision_job.sh:start_ocr_server`, `vllm_utils.sh`) **(verified)**.
- **olmOCR-2 FP8 (about 9 GB of weights) or Chandra 2 BF16 (about 10 GB):**
  - Neither fits in 0.10 (9.6 GB).
  - For a line of 15–30 tokens, `--max-model-len 4096` and `--max-num-seqs 64` keep the KV cache small. A share of about 0.15 (14.4 GB) should hold either model, with the main model cut to about 0.73 (70 GB: 54 GB of weights plus 16 GB).
  - Whether 40 concurrent Entry Span requests still fit depends on the main model's KV use. Qwen3.6 uses hybrid attention, which keeps its KV cache small, but I have not checked this **(inference)**. The serving log's "GPU KV cache size" line answers it.
- **Separate pass:** the OCR phase runs to completion before any Entry Span request (`cli.py:319`). Its answers are stamped by OCR model and crop, so a first job could fill `ocr/` with the OCR model given the whole GPU, and a second job could run the main model. This needs a CLI flag to stop after OCR, which is a code change **(verified that the phases are sequential; the flag does not exist)**.
- **VietOCR and Tesseract:** CPU or a tiny GPU slice, outside vLLM. `cli.py` reads OCR through an OpenAI-compatible `Model(name, url)` (`cli.py:310`). A voter outside vLLM needs either a small HTTP shim or a second OCR path in `cli.py` **(verified that only one OCR model is wired)**.

## 5. Decoding-side mitigations

| Idea | Evidence | Expected effect here |
|---|---|---|
| Vietnamese character-set regex (vLLM `structured_outputs: {"regex": …}`; `guided_regex` was removed in v0.12) [vLLM structured outputs] | **(verified)** that vLLM supports it | Removes `ō`-type output: 1 character in 349 lines. Almost no gain **(verified count; inference on effect)** |
| Lexicon of valid Vietnamese syllables (dictionary-guided recognition, VinAI CVPR 2021 [Dict-guided]; the DAR survey says dictionary guidance "has shown promise") | **(verified)** that the idea exists for Vietnamese scene text | Our errors are valid→valid syllable swaps, and *mót* and *võng* are valid. It would also have to keep the rare syllables we want to survive. Use it only as a Warning ("not a syllable") **(inference)** |
| `repetition_penalty` 1.0 for OCR | Already set (`OCR_REPETITION_PENALTY = 1.0`) **(verified)**. HunyuanOCR recommends 1.08 and Vintern 2.5 | Keep at 1.0. Rule out models whose cards require a penalty |
| 2× upscale of the line | PaddleOCR-VL-1.6's card upscales images under 1500 px 2× with LANCZOS for spotting [PaddleOCR-VL-1.6] **(verified)** | 4082 × 222 = 0.9 Mpx stays under its about 1 Mpx budget. Each mark gets about 4× the vision patches. A cheap arm for PaddleOCR-VL **(inference)** |
| Downscale for page-trained models | olmOCR-2 trains at a 1288 px long side; Chandra renders at 192 dpi **(verified)** | Match their training text size: about 0.45× for olmOCR, 0.64× for Chandra. Test both native and matched sizes **(inference)** |
| Paragraph or Entry Span crops | ADR 0002 rejected one OCR request per Entry Span (over PaddleOCR-VL's pixel budget, and copying down the span) **(verified)** | Chandra's and olmOCR's budgets are about 6.3 Mpx, so a whole Entry Span (about 2.7 Mpx) fits. That gives more context but also more language prior. Compare as an arm for the large models only **(inference)** |
| Independent voters plus majority vote per syllable | VLM OCR on historical documents shows "orthographic normalization … meaning-altering substitutions that remain fluent" that CER hides [Low-CER-not-enough]; MLLMs show "overreliance on linguistic priors" on degraded documents [KIE-HVQA] **(verified)** | Different model families make different frequency mistakes. `diacritics.disagreements` already aligns syllables on bare letters, so extending it to N readers is natural **(inference)** |
| Prompt wording | `prompts.py` tells the main model to follow OCR spelling **(verified)** | Until a reader is shown to be right more often than the main model, say "a second reading; where it differs, look again at the scan" instead **(inference)** |

## 6. Bake-off plan

**Gold.**
- No `review.jsonl` exists under `store/` today. The store was wiped since the prior report **(verified)**.
- Use the 15 pages that have OCR Readings now (36–45, 420–424; 349 lines). The developer fixes every line's text, letters and diacritics only, as a frozen file.
- Add 3–4 later pages dense in stacked tones (letters *Nh*, *Ng*, *Tr*).
- That gives about 450 lines and about 3,500 syllables. That is enough to separate 6% from 2% syllable error, but not 2% from 1.5% **(inference)**.

**Metrics per line** (NFC, asterisks and HTML tags stripped):
- **DER:** syllables with matching bare letters but wrong marks, divided by gold syllables. This is the headline metric.
- **Đ-error rate.**
- **Rare-syllable survival:** the share of gold syllables outside the top 3,000 most frequent that come out exactly right.
- **CER.**
- **Out-of-alphabet characters.**
- **Seconds per line and GPU memory.**

For the hybrid also score:
- **The final Blocks' DER**, which is what gets published.
- **How many of the main model's errors the Warnings catch.**
- **How many OCR errors the main model adopted**, which is the invisible failure from TL;DR item 5.

**Arms**, all on the same line crops (`ocr/*.json`'s `box`, cut with `pages.span_image`):

| Arm | How (describe, don't edit) |
|---|---|
| A. PaddleOCR-VL-1.6 (today) | Existing `ocr/*.json` |
| B. PaddleOCR-VL-1.6, 2× upscale | Scale the PNG 2× (LANCZOS) before `data_url` in `ocr_requests`; that changes the `OCR_IMAGE` stamp string, so the lines are re-read |
| C. SenOCR-Vi | `OCR_MODEL = "VietAlphaLabs/SenOCR-Vi"` in `settings.py` and `VISION_OCR_MODEL` in `submit.sh`; prompt stays `OCR:` |
| D. olmOCR-2-7B-1025-FP8 | Same two strings. `OCR_PROMPT` becomes the olmOCR v4 no-anchoring prompt (or a plain "Transcribe this line exactly, letter by letter, every diacritic as printed"), with YAML front matter stripped from answers. `VISION_OCR_GPU_SHARE=0.15`, `VLLM_GPU_MEMORY_UTILIZATION=0.73`. Add `--max-model-len 4096 --max-num-seqs 64` to `start_ocr_server`'s `VLLM_EXTRA_ARGS`. `OCR_MAX_TOKENS` about 512 to leave room for the front matter. Variant D2: 0.45× downscale |
| E. Chandra OCR 2 | `OCR_MODEL = "datalab-to/chandra-ocr-2"`. `OCR_PROMPT` = Chandra's `PROMPT_MAPPING["ocr"]` text. Share as D (add `--quantization fp8` if BF16 does not fit). Keep `<i>` from the answer for an italics side metric. Variant E2: whole Entry Span crops. **Research use only** |
| F. Qwen3.5-9B | `Qwen/Qwen3.5-9B`, a plain transcription prompt, thinking off (the phase already sends `thinking=False`). Separate job or FP8 at 0.15 |
| G. VietOCR `vgg_transformer` | Standalone script on CPU or GPU: tight ink crop, `image_max_width` raised to 2048 (or chunks at word gaps of 16:1 or less), `beamsearch: True` |
| H. Tesseract 5 `vie` best | `tesseract crop.png - -l vie --psm 7 -c load_system_dawg=0 -c load_freq_dawg=0`, 10 px border |
| I. Votes | Per-syllable majority over {best VLM, G, H}, aligned on bare letters as in `diacritics.py`; on a tie, emit a Warning |
| Ref. Gemini (hosted) | Ceiling only, on the gold lines, if the project accepts sending the scans out |

**Running VLM arms through the pipeline:**
- `ocr_base` stamps `ocr_model` and `prompt_sha1` (`cli.py:283`), so changing `OCR_MODEL` or `OCR_PROMPT` re-reads every line by itself and then re-runs every Entry Span request, because its prompt holds the readings **(verified)**.
- Copy `store/part-1` aside for each arm, run `sbatch scripts/khotangtucngu/submit.sh --part-1 --pages 36-45,420-424,…`, and keep `ocr/` and `answers.json` per arm.
- To score the OCR alone, a standalone script against the same server is enough and spares the 27B model.

**Decision rule:**
- Adopt the reader, or vote, with the lowest DER that also keeps rare syllables at least as well as the main model.
- Prefer the hybrid vote if no single reader cuts DER by at least half against arm A.
- Adopt Chandra only with Datalab's written licence confirmation for the public site.

## 7. Sources

**Benchmarks and papers**
- [MDPBench] Li et al., "MDPBench: A Benchmark for Multilingual Document Parsing in Real-World Scenarios", arXiv:2603.28130. https://arxiv.org/html/2603.28130v1
- [Vietnamese DAR survey] "A Survey on Vietnamese Document Analysis and Recognition: Challenges and Future Directions", arXiv:2506.05061. https://arxiv.org/html/2506.05061
- [Low-CER-not-enough] Gardella et al., "When Low CER is Not Enough: An Analysis of Hallucinations in Vision-Language OCR Systems on Historical Uruguayan Documents", arXiv:2607.24077 (ICDAR 2026 ADAPDA). https://arxiv.org/abs/2607.24077
- [KIE-HVQA] "Seeing is Believing? Mitigating OCR Hallucinations in Multimodal Large Language Models", arXiv:2506.20168 (NeurIPS 2025). https://arxiv.org/abs/2506.20168
- [Dict-guided] Nguyen et al., "Dictionary-Guided Scene Text Recognition", CVPR 2021. https://openaccess.thecvf.com/content/CVPR2021/html/Nguyen_Dictionary-Guided_Scene_Text_Recognition_CVPR_2021_paper.html, code and VinText: https://github.com/VinAIResearch/dict-guided

**Models**
- [PaddleOCR-VL-1.6] https://huggingface.co/PaddlePaddle/PaddleOCR-VL-1.6
- [SenOCR-Vi] https://huggingface.co/VietAlphaLabs/SenOCR-Vi
- [olmOCR-2 card] https://huggingface.co/allenai/olmOCR-2-7B-1025 (FP8: https://huggingface.co/allenai/olmOCR-2-7B-1025-FP8)
- [Chandra repo] https://github.com/datalab-to/chandra (prompts: `chandra/prompts.py`; launcher: `chandra/scripts/vllm.py`; settings: `chandra/settings.py`)
- [chandra-ocr-2 card] https://huggingface.co/datalab-to/chandra-ocr-2
- [Chandra licence] https://huggingface.co/datalab-to/chandra-ocr-2/blob/main/LICENSE
- [Qwen3.5-9B] https://huggingface.co/Qwen/Qwen3.5-9B
- [Qwen3-VL card] https://huggingface.co/Qwen/Qwen3-VL-8B-Instruct
- [HunyuanOCR] https://huggingface.co/tencent/HunyuanOCR
- [GLM-OCR] https://huggingface.co/zai-org/GLM-OCR
- [Gemma 4] https://huggingface.co/google/gemma-4-12B-it
- [Vintern-1B-v3.5] https://huggingface.co/5CD-AI/Vintern-1B-v3_5
- [Vintern-3B-R] https://huggingface.co/5CD-AI/Vintern-3B-R-beta
- [EraX-VL] https://huggingface.co/erax-ai/EraX-VL-7B-V1.5
- [AsterNet] https://huggingface.co/asterxlabs/asternet-vietnamese-ocr
- [VietOCR] https://github.com/pbcquoc/vietocr (`config/base.yml`, `config/vgg-transformer.yml`, `vietocr/tool/translate.py`, `vietocr/model/backbone/vgg.py`)
- [deepdoc_vietocr] https://github.com/hoaivannguyen/deepdoc_vietocr
- [tessdata_best] https://github.com/tesseract-ocr/tessdata_best (`vie.traineddata`, `script/Vietnamese.traineddata`)
- [Tesseract ImproveQuality] https://tesseract-ocr.github.io/tessdoc/ImproveQuality.html
- [PP-OCRv5 multilingual] https://www.paddleocr.ai/latest/en/version3.x/algorithm/PP-OCRv5/PP-OCRv5_multi_languages.html
- [EasyOCR] https://github.com/JaidedAI/EasyOCR (`easyocr/config.py`)
- [Surya] https://github.com/datalab-to/surya

**Serving and project**
- [vLLM models] https://docs.vllm.ai/en/latest/models/supported_models/
- [vLLM structured outputs] https://docs.vllm.ai/en/latest/features/structured_outputs/
- [DV Tuoi Tre] Tuoi Tre News, "Fulbright Vietnam signs academic cooperation deal with Columbia University" (Nov 2025; names the "AI-based 'Digitizing Vietnam' archive initiative"). https://news.tuoitre.vn/fulbright-vietnam-signs-academic-cooperation-deal-with-columbia-university-103251108102806815.htm

**In the repo**
- `vsc-project/khoTangTucNguoiNguoiViet/store/part-1/ocr/*.json`, `warnings.json`, `readings.json`
- `src/khotangtucngu/settings.py` (OCR_*), `cli.py:93-95, 138-160, 283, 310, 319`, `prompts.py:77-82`, `pages.py:154-175`, `diacritics.py`
- `scripts/khotangtucngu/submit.sh`, `scripts/lib/vision_job.sh:50-64`, `scripts/lib/vllm_utils.sh:119-140`
- `vsc-project/khoTangTucNguoiNguoiViet/docs/adr/0002-ocr-readings-of-each-line.md`, `GLOSSARY.md`
