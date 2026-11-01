Status: ready-for-agent

# Kho tàng tục ngữ người Việt: VietOCR reads each line in place of PaddleOCR-VL

Grilled 2026-11-01. Changes `.scratch/kho-tang-tuc-ngu-entry-spans/` (the OCR Readings of ADR 0002). Vocabulary: `vsc-project/khoTangTucNguoiNguoiViet/GLOSSARY.md` (unchanged: OCR model, OCR Reading, Diacritic Disagreement). Decision record: `vsc-project/khoTangTucNguoiNguoiViet/docs/adr/0003-vietocr-reads-each-line.md`. Research: `docs/research/khotangtucngu-vietnamese-ocr-model-2026-11-01.md` (sections 3.1, 4.1).

## Problem Statement

The OCR model, PaddlePaddle/PaddleOCR-VL-1.6, disagrees with the scan on about 6% of syllables, mostly through its own frequency-prior errors (*mót→một*, *võng→vọng*, *cơm→com*), and the Entry Span prompt tells the main model to spell after it. The developer wants the OCR Readings to come from VietOCR, a recogniser trained only on Vietnamese lines, whose vocabulary is the Vietnamese alphabet.

## Solution

VietOCR `vgg_transformer` (pbcquoc/vietocr, Apache-2.0) becomes the only OCR model. It is not a vote beside another reader. It runs in-process in the CLI on the GPU, as the OCR phase before the Entry Span requests. The PaddleOCR-VL vLLM server is removed, and the main model gets back the GPU share it gave up.

Each line is cut tight to its ink and scaled to VietOCR's fixed 32 px height, keeping its aspect ratio (width up to 2048), so the tone marks are about 4–5 px tall instead of the 2–3 px a stock 512 × 32 squeeze gives. No fine-tuning.

The Entry Span prompt stops claiming the OCR model reads diacritics well. Separately, an Entry Span answer's cap goes from 2048 to 4096 tokens.

## VietOCR's input, as its code defines it (v0.3.13, read 2026-11-01)

- Tensor `N × 3 × 32 × W`: RGB (`img.convert("RGB")`, so a grayscale crop is fine), pixels `/255`, no mean/std normalisation (`tool/translate.py:process_image`).
- Height: always 32 (`dataset.image_height`). The weights were trained at 32.
- Width: `32·w/h` rounded **up to a multiple of 10**, clamped to `[image_min_width, image_max_width]` (stock `[32, 512]`), LANCZOS. Past the clamp, the aspect ratio is not kept (`tool/translate.py:resize`).
- CNN: VGG19-bn, average pools `ss = [2,2],[2,2],[2,1],[2,1],[1,1]`. Height ÷16 (32 → 2 rows), width ÷4. The encoder sequence is `(W/4)·2 = W/2` tokens (`model/backbone/vgg.py`).
- Ceiling: the sinusoidal `pe` buffer is `transformer.max_seq_length: 1024`, and it is loaded from the checkpoint, so it cannot grow. So **W ≤ 2048** at height 32 (`model/seqmodel/transformer.py`).
- Output: `translate()` and `translate_beam_search()` stop at 128 tokens. A line is about 70 characters.
- `Cfg.load_config_from_name()` downloads `base.yml` and the model's YAML from `vocr.vn` on every load. `Predictor` downloads http weights to `tempfile.gettempdir()`. `cnn.pretrained: True` makes torchvision download ImageNet VGG19 weights, which are then overwritten.
- `predictor.beamsearch: True` decodes one image at a time (`Predictor.predict`). `predict_batch` always decodes greedily.

## Decisions

1. **Model.** `vgg_transformer` (full-sequence precision 0.880, against 0.870 for `vgg_seq2seq`), weights `https://vocr.vn/data/vietocr/vgg_transformer.pth`.
2. **Dependency.** VietOCR pinned in `requirements.txt` only, at master commit `fe8c3a7` (2025-01-19, the 0.3.13 code). The scripts install nothing. Not the PyPI wheel `vietocr==0.3.13`: it hard-pins `pillow==10.2.0`, `imgaug==0.4.0`, `einops==0.2.0` and `gdown==4.4.0`, which clash with the repo's `pillow==12.2.0`. Master's `setup.py` takes ranges (`pillow>=10.2.0`, no imgaug), and its inference code matches the wheel's except for formatting.
3. **Config in code.** The full config (base plus vgg-transformer values) is built in code from `settings.py`, never with `load_config_from_name`, so nothing is fetched from `vocr.vn` at runtime. Overrides:
   - `cnn.pretrained: False`
   - `device: cuda`
   - `dataset.image_height: 32`
   - `dataset.image_min_width: 32`
   - `dataset.image_max_width: 2048`
   - `predictor.beamsearch: True`
   - `transformer.max_seq_length` stays 1024
4. **Weights cache.** The weights are downloaded once to a fixed cache path on the compute machine, not `/tmp`, and loaded from that path. If the file is already there, nothing is downloaded.
5. **Line crop for VietOCR.** From `find_lines`' `lines[n - 1] = [top, bottom, left, right]`: the ink band (which already holds tone marks and dots under letters) **8 px above, 4 px below**, and the line's own ink ends **4 px left and right**, clamped to the page. It is cut from the 300 dpi grayscale scan as `span_image` cuts, then handed to VietOCR, which scales it to height 32. It is no longer `line_box`'s full Entry Span width. `line_box` stays if nothing else needs changing.
6. **Decoding.** Beam search (beam 4, VietOCR's default), one line at a time.
7. **Where it runs.** In-process in `cli.py`, as the OCR phase, still run to completion before any Entry Span request. One Predictor is loaded per run. A line VietOCR fails on has no OCR Reading, so its page has no answer, as today. An OCR Reading is still stored one per line in `ocr/pNNN-LMM.json` and still feeds `readings.json`, the Entry Span user text and the Diacritic Disagreements unchanged.
8. **Stamp.** An OCR Reading is stamped with the OCR model (`vgg_transformer` plus the weights URL), its crop box and padding, image height, min and max width, and beam search, instead of `ocr_model` and `prompt_sha1`. Changing any of them re-reads every line, and so redoes every Entry Span request. Old stores are wiped. No migration.
9. **Removed.**
   - `OCR_PROMPT`, `OCR_REPETITION_PENALTY` and `OCR_MAX_TOKENS` (VietOCR has its own 128 cap), and the `OCR` vLLM `Phase`.
   - `ocr_messages`, and the `--ocr-model-name` / `--ocr-vllm-url` arguments and their exit message.
   - In `scripts/khotangtucngu/submit.sh`: `VISION_OCR_MODEL` and `VISION_OCR_GPU_SHARE`.
   - In `scripts/lib/vision_job.sh`: `start_ocr_server` and the `ocr_args` branch, since Kho tàng tục ngữ was their only user.
   - OCR requests no longer go through `vlm_requests` or `token_usage.jsonl`.
10. **GPU.** `VLLM_GPU_MEMORY_UTILIZATION` in `submit.sh` goes back from 0.78 to **0.85**. VietOCR's roughly 150 MB of weights and its activations live in the CLI process, in the rest of the GPU.
11. **Entry Span prompt** (`prompts.py:77-82`). Drop "The OCR model reads letters and diacritics well, so spell each word with the letters and diacritics its OCR Reading has…". Say instead that the OCR Reading is a hint, not the answer (the GLOSSARY avoids "second reading"): where it differs from the scan, look at the scan again. Keep "read each repeat of a word on its own line's OCR Reading, never from how you copied it before", and keep the note that it knows nothing of Blocks or italics and may miss a space or punctuation.
12. **Entry Span cap.**
    - `SPAN_MAX_TOKENS` goes from 2048 to **4096**, and `REQUEST_TIMEOUT` from 180 to **300**, so a capped runaway still fails as `finish_reason=length`, not as a timeout.
    - Why: p042-L02 hit 2048 twice (77–103 s each) on about 62k newlines before a temperature-0.3 retry answered in 133 tokens. 4096 tokens take about 150–210 s.
    - The settings comment says the cap stops a runaway.
13. **Comments and docs.** `settings.py` (OCR block), the `cli.py` module docstring, `submit.sh` and the `vision_job.sh` header stop naming PaddleOCR-VL, its pixel budget and its GPU share. ADR 0002's model choice is superseded by ADR 0003. Its Hint + Warnings design stands.

## Out of Scope

- A vote of several readers (VietOCR, Tesseract, a VLM), and a bake-off. These come later, if needed.
- Fine-tuning VietOCR at height 48 or 64.
- Cutting lines at word gaps into chunks of 16:1 or narrower. It stays in reserve in case long lines read badly at width 2048.
- Any tests or browser checks. This is verified by reasoning.
