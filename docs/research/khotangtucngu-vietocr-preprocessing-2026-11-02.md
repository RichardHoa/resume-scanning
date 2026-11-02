# Kho tàng tục ngữ OCR Readings: what VietOCR does to a line image itself, and whether our preprocessing helps, 2026-11-02

This report checks the uncommitted preprocessing in `src/khotangtucngu/{pages,ocr,settings,cli}.py` against VietOCR's own code at the commit `requirements.txt:167` pins (`pbcquoc/vietocr@fe8c3a7fc714aec57ab81cec844eb3adf0c1636c`). The changes are: `_ink_tops` (the crop grows upward to catch marks over capitals), `ocr.upright` (italic sheared upright), `ocr.grown_marks` (small marks dilated 2 px), greedy decoding in place of beam search, and `OCR_IMAGE_HEIGHT = 32`, `OCR_IMAGE_MAX_WIDTH = 2048`. The developer says nothing documents that VietOCR's input must be 32 px tall. This report answers whether that is right, and what follows from it.

No code was changed. I read the pinned source tree (downloaded from `codeload.github.com` at that commit), the live configs at `vocr.vn`, the GitHub commit history of `aug.py` and `base.yml`, the getting-started notebook, and the author's write-up at `pbcquoc.github.io/vietocr`. In this report, `translate.py:181` means `vietocr/tool/translate.py` line 181 at `fe8c3a7`. Claims tagged **(verified)** were read in the cited source. Claims tagged **(inference)** are my reading and need a run on our pages to confirm. Following the project rule, I verified by reading, not by running the model.

## TL;DR

- **The developer is right on the narrow point.** Nothing requires the caller to resize to 32 px. `Predictor.predict` resizes every image itself, to whatever `config["dataset"]["image_height"]` says (`predictor.py:35-40`, `translate.py:191-201`). It is a plain config value, read on every call **(verified)**. Our code does not pre-resize either. `read_lines` hands VietOCR the full-resolution prepared crop (`ocr.py:159-161`). `seen_image` only writes the debug PNG **(verified)**.
- **32 px is still the right value, for a reason the comments don't give.** No document records the height of the published training run. The only config shipped with the weights, `config/base.yml` (identical on `vocr.vn` today), sets `image_height: 32` and says "resize image to 32 height" (`base.yml:41-42`). The author tells users to predict with the config they trained with (blog, "Inference"). The VGG backbone **flattens height into the encoder sequence** (`vgg.py:47-49`). At 32 px each image column becomes 2 tokens. At 64 px it becomes 4, with a different order and spacing of positions than the weights were trained on. So another height runs without error, but it is out of distribution **(verified for the code, inference for the accuracy effect)**.
- **What is actually wrong is the width reasoning.**
  - "1024 positions, so 2048 px is the most it holds" is correct as a **crash limit** at height 32 (`transformer.py:115-126`).
  - But the same `base.yml` caps training width at **512 px** (`base.yml:44`). So the weights never saw more than **256 encoder positions**. Positions 256–1023 are extrapolation **(verified for the config, inference that the weights used it)**.
  - The settings comment "VietOCR's own 512 px cap would leave [tone marks] 2–3 px" is **wrong**. The width cap never changes the output height (`translate.py:181-188`). A mark's height in pixels depends only on the crop's height. The 2–3 px figure came from the old 111 px tall crop, not from the 512 cap **(verified)**.
- **`grown_marks` is the riskiest change.**
  - A 5 × 5 dilation turns acute, grave, hook and tilde into similar blobs. Those shapes are exactly the distinctions the Diacritic Disagreements track.
  - No VietOCR augmentation ever did this to marks (section 3).
  - Its premise ("a dot under a letter about 1 px") overstates the loss. Pillow's LANCZOS downscale averages over every input pixel that contributes, so a small mark turns grey; it does not vanish.
  - **Remove it**, or keep it only as an A/B arm.
- **`upright` is plausible but needs a guard.**
  - The augmentation that matches the 2022 weights has shear **commented out** (`aug.py@5e3fb5c:32-35`). So upright text is probably closer to what the weights know than italic text is **(inference)**.
  - A single shear per line will slant the roman part backwards on lines that mix roman and italic.
- **The beam-search claim is verified, with a sharper mechanism.**
  - Finished hypotheses are ranked by summed log-probability, with no length normalisation (`beam.py:73-80, 105-119`).
  - The search stops as soon as the top beam ends (`beam.py:82-83, 93-94`). By then, a *shorter* hypothesis that finished earlier can outscore it.
  - The defaults agree with greedy: `beamsearch: False` (`base.yml:54-56`), and the author found that beam search "did not improve accuracy" (blog). Keep greedy.

## 1. The repo and the inference path (question A)

### 1.1 Modules

| Path (at `fe8c3a7`) | Role |
|---|---|
| `config/base.yml` | Vocabulary, transformer sizes, trainer, `dataset.image_height/min_width/max_width`, `aug`, `predictor.beamsearch` |
| `config/vgg-transformer.yml` | Weights URL, `backbone: vgg19_bn`, `cnn.ss/ks` (pool strides and kernels), `cnn.hidden: 256`, `cnn.pretrained: True` |
| `vietocr/tool/config.py` | `Cfg.load_config_from_name` downloads `base.yml` and the model YAML from `vocr.vn` and merges them (`config.py:30-36`) |
| `vietocr/tool/predictor.py` | `Predictor`: builds the model, loads the weights, `predict` and `predict_batch` |
| `vietocr/tool/translate.py` | `resize`, `process_image`, `process_input`, `translate` (greedy), `translate_beam_search` / `beamsearch`, `build_model` |
| `vietocr/model/transformerocr.py` | `VietOCR` = `CNN` + `LanguageTransformer` (or Seq2Seq / ConvSeq2Seq) |
| `vietocr/model/backbone/{cnn,vgg,resnet}.py` | Backbones. VGG has its max-pools replaced by average pools of `ks`/`ss` (`vgg.py:22-29`) |
| `vietocr/model/seqmodel/transformer.py` | `LanguageTransformer` and the sinusoidal `PositionalEncoding` |
| `vietocr/model/beam.py` | `Beam` |
| `vietocr/loader/{dataloader,aug}.py`, `model/trainer.py` | Training: LMDB dataset, width-bucketed sampler, augmentation |

### 1.2 `Predictor.predict(img)` to a string

1. **Construction.** `build_model(config)` builds `VietOCR(len(vocab), backbone, cnn, transformer, seq_modeling)` (`translate.py:164-178`). `Predictor.__init__` then calls `model.load_state_dict(torch.load(weights))` with PyTorch's default `strict=True` (`predictor.py:19-27`) **(verified)**.
2. **Preprocessing.** `process_input(img, image_height, image_min_width, image_max_width)` reads the three values from `config["dataset"]` on every call (`predictor.py:35-40`). It returns a `1 × 3 × H × W` float tensor (`translate.py:204-208`); see section 2.
3. **CNN.** VGG19-bn features with average pools, dropout, a 1 × 1 conv to 256 channels, then `transpose(-1,-2)`, `flatten(2)` and `permute(-1,0,1)` give an `(S, N, 256)` sequence (`vgg.py:35-50`).
4. **Encoder.** `forward_encoder` scales by √256, adds `pe[:S]`, and runs `nn.TransformerEncoder` (`transformer.py:86-89, 125-128`).
5. **Decoding.**
   - Greedy (`beamsearch: False`): `translate` feeds the growing prefix to `forward_decoder` and takes the argmax at each step. It stops when every sequence has emitted EOS (token 2), or after `max_seq_length = 128` steps (`translate.py:115-161`).
   - Beam: `translate_beam_search`, with beam 4 and the same 128-step limit (`translate.py:44-112`).
6. **Text.** `vocab.decode(s)` returns the string (`predictor.py:52`).

`predict_batch` groups images by their resized width and decodes each group greedily, whatever `beamsearch` says (`predictor.py:59-85`) **(verified)**.

## 2. What VietOCR does to the image itself (question B)

### 2.1 The preprocessing, step by step (`translate.py:181-208`)

| Step | Code | Effect |
|---|---|---|
| Mode | `image.convert("RGB")` (`:192`) | A grayscale `L` image becomes three identical channels. No colour information is needed or used **(verified)** |
| Target width | `new_w = int(H_cfg * w / h)` (`:182`) | Keeps the aspect ratio, truncated toward zero |
| Rounding | `math.ceil(new_w / 10) * 10` (`:183-184`) | Rounds **up** to a multiple of 10, so the image is stretched horizontally by up to 9 px |
| Clamp | `max(new_w, min_width)`, then `min(new_w, max_width)` (`:185-186`) | Past `max_width`, the aspect ratio is **not** kept: the line is squeezed horizontally |
| Height | `return new_w, expected_height` (`:188`) | **Always** `image_height`, whatever the width clamp did |
| Resample | `img.resize((new_w, H_cfg), Image.LANCZOS)` (`:197`) | One LANCZOS resize, which antialiases when downscaling (Pillow: "a high-quality Lanczos filter … on all pixels that may contribute to the output value" [Pillow filters]) |
| Normalise | `img / 255` (`:200`) | Range 0–1. No mean/std normalisation |
| Padding | none | Nothing is padded at inference. In training, batches are bucketed by identical resized width (`dataloader.py:87-98`, `ClusterRandomSampler` at `:145-177`), so no padding is needed there either |
| Batching | `img[np.newaxis]` (`:206`) | `predict` reads one image at a time |

### 2.2 Is `image_height` fixed?

- **It is a config value, read at inference.** `Predictor.predict` passes `self.config["dataset"]["image_height"]` straight to `process_input` (`predictor.py:35-40`). Nothing in the code checks or pins it **(verified)**.
- **Nothing tells the caller to pre-resize.** The README and the notebook call `detector.predict(Image.open(...))` on a raw image (`vietocr_gettingstart.ipynb`, "Inference" cells; README "Quick Start") **(verified)**.
- **The published weights go with height 32.**
  - `config/base.yml:41-44` sets `image_height: 32`, `image_min_width: 32` and `image_max_width: 512`, with the comment "resize image to 32 height, larger height will increase accuracy". The copy on `vocr.vn/data/vietocr/config/base.yml` is identical today **(verified)**.
  - The `dataset` block has stayed at those values since 2020. `base.yml` was last changed on 2020-11-24, and the weights file on `vocr.vn` is dated 2022-12-03 (HTTP `Last-Modified`) **(verified)**.
  - The dataset defaults agree (`dataloader.py:31-33`) **(verified)**.
  - The author's blog says to predict with "config của các bạn được export lúc train nếu đã thay đổi tham số" (the config exported at training time, if you changed parameters). Otherwise it says to use the default config [VietOCR blog] **(verified)**.
  - No document states the height of the published training run in so many words. "The weights were trained at 32" is a strong inference from the config shipped with them **(inference)**.
- **"Larger height will increase accuracy" is about training.** The comment sits in the `dataset:` block that the trainer reads (`trainer.py:365-367, 391-393`). It does not say that feeding a larger height to the existing weights helps **(verified for where it sits; the reading is inference)**.

### 2.3 What a different height does to the network

- **The CNN does not collapse height.** VGG19-bn's convs use padding 1. Only the five pools downsample, with `ss = [2,2],[2,2],[2,1],[2,1],[1,1]` (`vgg-transformer.yml:10-23`, `vgg.py:24-29`). So the feature map is `H' = ⌊H/16⌋` by `W' = ⌊W/4⌋` **(verified)**.
- **Height is flattened into the sequence, column by column.** `conv.transpose(-1,-2).flatten(2)` puts the height index fastest. Token `p` is column `p // H'`, row `p % H'`, and `S = W' · H'` (`vgg.py:47-49`) **(verified)**.
  - At height 32: `H' = 2`, so `S = W/2`, the "one position per 2 px of width" in `settings.py` **(verified)**.
  - At 48: `H' = 3`. At 64: `H' = 4`, so `S = W` **(verified, arithmetic)**.
  - The author's blog describes the same flattening of "heightxwidth" [VietOCR blog] **(verified)**.
- **Positional encoding.** `PositionalEncoding` builds a sinusoidal table `pe` of `max_len = transformer.max_seq_length = 1024` rows. It registers it as a **buffer** (`transformer.py:110-123`), and a buffer is saved in `state_dict` by default [PyTorch register_buffer] **(verified)**.
  - Changing `max_seq_length` makes the strict `load_state_dict` fail on the shape (`predictor.py:27`) **(verified, from strict loading semantics)**. The `ocr.py:74` comment is right.
  - `forward` does `x + self.pe[:x.size(0)]` (`:125-126`). If `S > 1024`, the slice has 1024 rows and the addition fails to broadcast, so `predict` raises **(verified, by reading)**.
- **The hard limit is therefore an area: `⌊W/4⌋ · ⌊H/16⌋ ≤ 1024`.**
  - At H = 32 that is W ≤ 2048. At H = 64 it is W ≤ 1024 **(verified, arithmetic)**.
  - `resize` clamps to `image_max_width` after rounding up, so `max_width = 2048` gives at most exactly 2048 **(verified)**.
- **What changing the height does to the weights.**
  - With `H' = 4`, the encoder sees four tokens per column where it learned two, and position `p` means a different place in the image.
  - The CNN filters see glyphs twice the size they were trained on.
  - Nothing breaks, but this is a different input distribution. The spec already puts "Fine-tuning VietOCR at height 48 or 64" out of scope for this reason (`spec.md`, Out of Scope) **(inference)**.

### 2.4 Is our reasoning right?

| Our claim (`settings.py` comments, `spec.md`) | Verdict |
|---|---|
| "VietOCR scales it to OCR_IMAGE_HEIGHT" | **Right.** VietOCR does the scaling, not us (`translate.py:197`) |
| "the height its weights were trained at" (32) | **Right by strong inference** (`base.yml:42`). No document states it outright. Word it as "the height of the config the weights ship with" |
| "its encoder reads one of its 1024 positions per 2 px of width, so 2048 is the most it holds" | **Right as a crash limit at height 32.** It misleads as a working range: the shipped config trains at ≤ 512 px, so ≤ 256 positions (`base.yml:44`) |
| "where VietOCR's own 512 px cap would leave them 2–3 px" | **Wrong.** The width cap squeezes only horizontally. Mark height is `32 × mark_px / crop_height_px` whatever the cap (`translate.py:181-188`) |
| "the scaling to 32 px leaves a dot under a letter about 1 px" | **Overstated.** A crop of about 80–95 px scales by 0.34–0.40, so a dot of about 5 px becomes about 2 px. LANCZOS spreads it as grey rather than dropping it [Pillow filters] **(inference; the dot's size is not measured)** |
| `seen_image` mimics VietOCR's resize | **Right.** It calls VietOCR's own `resize`, converts to RGB and resizes with LANCZOS, as `process_image` does (`ocr.py:131-136` against `translate.py:191-197`) |

**How wide our lines really are at height 32 (inference, from `settings.py`'s figures):** a 1,700 × 85 px crop becomes `int(32·1700/85) = 640` px wide, which is 320 encoder tokens. That is already past the 256 positions the stock config trains on, but far from 2048. So in practice the 2048 cap is never reached. The real choice is between (a) moderate positional extrapolation (cap ≥ 640) and (b) VietOCR's stock squeeze to 512 (to about 80% of the natural width), which is in distribution. Splitting the line at word gaps, so that each piece is ≤ 16:1 (≤ 512 px at height 32), is in distribution with no squeeze. The spec holds that option in reserve (`spec.md`, Out of Scope).

## 3. Training data and augmentation (question C)

- **Data.** "10m ảnh, bao gồm nhiều loại ảnh khác nhau như ảnh tự phát sinh, chữ viết tay, các văn bản scan thực tế" (10M images: synthetic, handwriting, real scanned documents) (README:39). The fonts and the share of italic are not documented **(verified; no evidence found on italics)**.
- **Augmentation in effect when the weights were published (2022-12-03).** `aug.py` was changed in 2020-11 and not again until 2024-03 (GitHub history of `vietocr/loader/aug.py`). So the 2020-11-29 version (`5e3fb5c`) is the one that matches the weights, assuming they were trained with the repo's own augmenter **(verified for the dates; the assumption is inference)**. Its imgaug `SomeOf((1,5))` list, each step with probability 0.3:
  - **Blur:** `GaussianBlur(sigma 0–1)` or `MotionBlur(k=3)`.
  - **Colour:** hue and saturation, sigmoid contrast, `Invert(0.25)`, `Solarize`, `Multiply`, `Add`, `JpegCompression(5–80)`.
  - **Distortion:** `Crop(1–5%)`, `PerspectiveTransform(0.01)`, `Affine(scale 0.7–1.3, translate ±10%)` **with `rotate` and `shear` commented out** (`:32-35`), and `PiecewiseAffine(0.01)`.
  - **Dropout:** `Dropout(0–0.1)` and `CoarseDropout`.
  - Source: (`aug.py@5e3fb5c:7-42`) **(verified)**.
- **The current augmenter (`fe8c3a7`, 2024-11) postdates the weights.** It uses albumentations `InvertImg`, `ColorJitter`, `MotionBlur(3)`, `RandomBrightnessContrast`, `Perspective(0.01–0.05)` and a random dotted line (`aug.py:60-71`) **(verified)**. It describes how a model fine-tuned today would see data, not the published weights.
- **Masked-language-model noise.** 5% of decoder-input tokens are masked during training (`dataloader.py:221-225`) **(verified)**.
- **What this means for our changes (inference):**
  - Blur, pixel dropout and JPEG noise were in training. So soft or slightly broken marks are in distribution, and the network was trained to cope with them.
  - Morphological thickening of *only* the marks was never in training, so marks bolder than their letters are out of distribution.
  - Shear was deliberately left out of the augmentation, so the network has no augmentation-driven robustness to slant. Any tolerance of italic comes only from italic fonts in the data, which is undocumented. That makes deskewing italic a reasonable thing to try.
- **The author's own warning.** "mô hình khá nhạy cảm với sự thay đổi nhỏ của ảnh đầu vào khi các bạn sử dụng pretrained model trên tập dữ liệu mới" (the model is quite sensitive to small changes of the input image when the pretrained model is used on a new dataset) [VietOCR blog] **(verified)**. Every preprocessing change is therefore an empirical bet, and each should be measured on our pages.

## 4. Beam search (question D)

- **Scoring.**
  - `Beam.advance` adds the step's log-probabilities to `current_scores`, which are cumulative and unnormalised (`beam.py:47-50`).
  - When a beam emits EOS, it is appended to `finished` with that raw cumulative score (`:73-80`).
  - `sort_finished` sorts by raw score (`:105-119`).
  - No length penalty or normalisation appears anywhere. `min_length=0` (`translate.py:81-88`) **(verified)**.
- **Why short readings win.** Every log-probability is ≤ 0, so the cumulative score can only fall as a hypothesis grows **(verified, arithmetic)**.
  - `done()` becomes true once the **top** beam (index 0) ends and at least `n_top = 1` hypotheses have finished (`beam.py:82-83, 93-94`).
  - A hypothesis that ended earlier while not ranked first is still in `finished`, with the higher score it had when it was shorter.
  - So when the full reading finally ends at the top, a truncated reading from earlier steps can outrank it and be returned (`translate.py:105-112`).
  - That is the "dropped a line's last word" failure seen on p036-L16 (`settings.py` comment) **(verified for the mechanism; the p036 case is the developer's observation)**.
  - A finished beam also keeps its slot only by having its children set to −1e10 (`beam.py:51-55`), so the beam narrows in practice **(verified)**.
- **This is the standard length bias.** Neural machine translation fixes it with length normalisation or a length penalty (GNMT, Wu et al. 2016, §7) [GNMT] **(verified)**.
- **The defaults agree.**
  - `base.yml:54-56` ships `beamsearch: False`, noting "use beamsearch will be slower".
  - The author wrote: "Mình đã sử beamsearch khi phát sinh câu, tuy nhiên độ chính xác không cải thiện" (I used beam search when generating, but accuracy did not improve) [VietOCR blog] **(verified)**.
  - Greedy is the documented default and the right setting. Spec decision 6 (beam 4) is superseded.

## 5. Each technique in the diff (question E)

### 5.1 `_ink_tops` and the taller crop (`pages.py:62-81, 178-184`)

- **Effect on scale.** The crop's height is the only thing that sets the scale to 32 (section 2.1). Every row of headroom shrinks every glyph by the same factor. An extra 10 px on an 80 px crop shrinks the text by about 11% **(verified, arithmetic)**.
- **Why it is still worth it.** A cut-off hook over a capital is unrecoverable, while a slightly smaller line is not. The search is bounded by `OCR_ABOVE_SHARE · height`, by `OCR_ABOVE_GAP_PX` blank rows, by the previous line's bottom (`floor`), and by the line's own `left:right` span, so it cannot take in the line above **(verified, by reading)**.
- **Small points.**
  - The padding is symmetric, `OCR_PAD_PX = 4` on all sides. VietOCR pads nothing itself, and training images were not padded either (section 2.1). So 4 px is a harmless margin, not a requirement **(verified)**.
  - Dots under letters rely on the band including them (`line_box` docstring). No "ink below" search mirrors `_ink_tops`. That is fine if `line_bands` already includes them, as the comment says **(not re-checked here)**.
- **Verdict:** keep.

### 5.2 `upright`: projection-profile shear (`ocr.py:86-100`)

- **What it does.** It tries shears `s ∈ [0, 0.4]` in steps of 0.02 (up to about 22°) and keeps the one that maximises `Σ_col (ink count in column)²`. Shearing to make vertical strokes stack is the classic slant-normalisation idea for text lines; Vinciarelli & Luettin (2001) is the usual reference [Vinciarelli 2001] **(paper identified via Crossref. I did not re-read its full text, so I do not quote its exact criterion. As I recall it, it counts only columns that hold a single continuous stroke, while ours counts all ink, so tone marks and dots also vote)**.
- **The geometry is correct.**
  - PIL's `AFFINE` data `(a,b,c,d,e,f)` maps each output pixel `(x,y)` to the input `(ax+by+c, dx+ey+f)` [Pillow transform]. So `(1, −s, 0, 0, 1, 0)` reads the input at `x − s·y`, and ink moves right by `s·y`. Lower rows move right, which uprights a right-leaning italic.
  - The width grows by `⌈s·h⌉`. `fillcolor=255` keeps the background white **(verified)**.
- **In or out of distribution.** Shear was commented out of the matching augmentation (section 3). So upright text is the safer input **(inference)**.
- **Risks:**
  - **Mixed lines.** A line with roman and italic parts gets one shear, chosen by whichever has more ink. The roman part then leans left by up to 22° **(inference)**. The dictionary mixes roman proverbs with italic Variants and Corrections (see the 2026-10-31 report's italics-boundary findings).
  - **Weak optimum.** On upright text the criterion can still prefer a small non-zero `s`, because marks and serifs vote. A tie keeps 0, since `max` returns the first maximum, but a near-tie does not **(inference)**.
- **Verdict:** keep, with a guard. Shear only when the best score beats `s = 0` by a clear margin. Better still, estimate and apply the shear per segment between word gaps (the same gaps a chunked read would use).

### 5.3 `grown_marks`: dilating small components (`ocr.py:103-123`)

- **What it does.** It labels 8-connected ink components (`ndimage.label` with a 3 × 3 structure) and keeps those no taller or wider than `0.2 ×` the line's ink height and with at least 4 px. It applies a 5 × 5 `minimum_filter` (grey erosion of a white background, which is a dilation of the dark ink) to those components only, then takes the pixelwise min with the original [scipy minimum_filter][scipy label] **(verified)**.
- **Why it is harmful (inference):**
  - **Shape loss.** Vietnamese tone marks differ by **shape and direction**: sắc ´, huyền `, hỏi ̉, ngã ~. At 300 dpi they are about 8–12 px (`settings.py`). A square 5 × 5 structuring element adds 2 px on every side. That rounds the end of a stroke, fills the hook's opening and thickens the tilde's wave. After a 0.34–0.40 downscale, the extra 4 px across becomes about 1.5 px of a mark only 3–5 px across. Dilation is the textbook operation for *closing* gaps and *joining* parts [OpenCV morphology], which is the opposite of keeping a hook's opening.
  - **Gap loss.** Growth also eats the gap between a mark and its letter, or between a circumflex and the tone mark stacked on it (*ầ*, *ỗ*). The stacked circumflex-plus-tilde zone is exactly where the earlier reports found the misreadings (`khotangtucngu-ocr-model-2026-10-31.md`, TL;DR).
  - **Out of distribution.** Marks bolder than their letters never occurred in training (section 3).
  - **Weak premise.** LANCZOS downscaling keeps a 2–3 px mark as a grey blob, not 0 px (section 2.4). VietOCR trained with blur and dropout, so it reads soft marks.
- **Verdict:** remove it. If kept for an A/B, use a 3 × 3 element (`OCR_MARK_GROW_PX = 1`) on dots and full stops only, not on tone marks.

### 5.4 Grayscale (`prepare`: `image.convert("L")`)

The crop is already grayscale (`span_image` renders with `csGRAY`, `pages.py:195`). VietOCR converts any mode to RGB with three equal channels (`translate.py:192`). The source scan is 1-bit at about 222 dpi (`khotangtucngu-ocr-model-2026-10-31.md`, TL;DR), so no colour is lost. Keeping `L` is correct and has no effect on what the model sees **(verified)**.

### 5.5 Height 32 and max width 2048

- **Height:** keep 32 (section 2.3).
- **Max width.**
  - 2048 is safe from the crash, but it lets lines use encoder positions 256–1023, which the 512-px training config never used.
  - At our line sizes (about 640 px, 320 tokens at height 32) the extrapolation is moderate. Whether it beats the stock 512 squeeze is an empirical question **(inference)**.
  - The in-distribution option with no squeeze is to split each line at word gaps into pieces ≤ 16:1 and join the readings with spaces.

## Sources

**VietOCR, primary (pinned commit `fe8c3a7fc714aec57ab81cec844eb3adf0c1636c`)**
- [VietOCR@fe8c3a7] https://github.com/pbcquoc/vietocr/tree/fe8c3a7fc714aec57ab81cec844eb3adf0c1636c. Files: `vietocr/tool/predictor.py`, `vietocr/tool/translate.py`, `vietocr/tool/config.py`, `vietocr/model/backbone/{vgg,cnn}.py`, `vietocr/model/seqmodel/transformer.py`, `vietocr/model/transformerocr.py`, `vietocr/model/beam.py`, `vietocr/loader/{dataloader,aug}.py`, `vietocr/model/trainer.py`, `config/base.yml`, `config/vgg-transformer.yml`, `README.md`, `vietocr_gettingstart.ipynb`
- [aug.py@5e3fb5c] https://github.com/pbcquoc/vietocr/blob/5e3fb5c/vietocr/loader/aug.py (2020-11-29; history: https://github.com/pbcquoc/vietocr/commits/master/vietocr/loader/aug.py)
- [base.yml history] https://github.com/pbcquoc/vietocr/commits/master/config/base.yml (last change 2020-11-24)
- [vocr.vn configs] https://vocr.vn/data/vietocr/config/base.yml, https://vocr.vn/data/vietocr/config/vgg-transformer.yml (identical to the repo's); weights https://vocr.vn/data/vietocr/vgg_transformer.pth (`Last-Modified: Sat, 03 Dec 2022`)
- [VietOCR blog] pbcquoc (the repo's author), "VietOCR", https://pbcquoc.github.io/vietocr/ (sections "Inference", "Một Số Kết Quả Thực Nghiệm", "Custom Augmentor", "CRNN … CTCLoss")

**Libraries and techniques**
- [Pillow filters] https://pillow.readthedocs.io/en/stable/handbook/concepts.html#filters (LANCZOS, BICUBIC)
- [Pillow transform] https://pillow.readthedocs.io/en/stable/reference/Image.html#PIL.Image.Image.transform (AFFINE data)
- [PyTorch register_buffer] https://pytorch.org/docs/stable/generated/torch.nn.Module.html#torch.nn.Module.register_buffer (persistent buffers are in `state_dict`)
- [scipy minimum_filter] https://docs.scipy.org/doc/scipy/reference/generated/scipy.ndimage.minimum_filter.html
- [scipy label] https://docs.scipy.org/doc/scipy/reference/generated/scipy.ndimage.label.html
- [OpenCV morphology] https://docs.opencv.org/4.x/d9/d61/tutorial_py_morphological_ops.html (dilation "increases the white region … useful in joining broken parts of an object")
- [Vinciarelli 2001] A. Vinciarelli, J. Luettin, "A new normalization technique for cursive handwritten words", *Pattern Recognition Letters* 22(9):1043–1050, 2001, doi:10.1016/S0167-8655(01)00042-3
- [GNMT] Wu et al., "Google's Neural Machine Translation System", arXiv:1609.08144, §7 (length normalisation and coverage penalty in beam search)

**In the repo**
- `src/khotangtucngu/ocr.py:35-36, 67-83, 86-136, 159-161`, `pages.py:62-81, 178-195`, `settings.py` (OCR block), `cli.py:137, 145, 272`
- `.scratch/kho-tang-tuc-ngu-vietocr/spec.md`, `docs/research/khotangtucngu-ocr-model-2026-10-31.md`, `docs/research/khotangtucngu-vietnamese-ocr-model-2026-11-01.md`

## Recommended fixes

1. **Keep `OCR_IMAGE_HEIGHT = 32`, and rewrite its comment.**
   - New wording: VietOCR resizes every crop itself to `dataset.image_height` (`translate.py:191-197`). We pass 32 because it is the height in the config the weights ship with (`base.yml:42`).
   - The VGG backbone flattens height into the encoder sequence (`vgg.py:47-49`), so another height changes the sequence the weights learned and needs fine-tuning.
   - Do not pre-resize anywhere. The code already does not, and `seen_image` stays a debug view.
2. **Fix the wrong width comment in `settings.py`.**
   - Delete "where VietOCR's own 512 px cap would leave them 2–3 px". The width cap squeezes only horizontally. Mark height is set by the crop's height alone.
   - Restate the 2048 limit as a crash ceiling: `⌊W/4⌋·⌊H/16⌋ ≤ 1024` positions (`transformer.py:123-126`). Note that the weights' config trained at ≤ 512 px, which is ≤ 256 positions.
3. **Decide `OCR_IMAGE_MAX_WIDTH` on our own pages.**
   - Run one comparison: 512 (stock, in distribution, about 80% squeeze) against the current 2048 (about 640 px in practice, extrapolated positions).
   - Score each on the Diacritic Disagreements and the developer's Fixes.
   - If long lines read badly either way, implement the reserved option from the spec: split at word gaps into pieces ≤ 16:1 and join the readings.
4. **Remove `grown_marks`** from `ocr.prepare`, together with `OCR_MARK_SHARE`, `OCR_MARK_MIN_PX`, `OCR_MARK_GROW_PX` and their part of the `OCR_IMAGE` string.
   - It blunts the shapes that tell sắc, huyền, hỏi and ngã apart, and closes the gaps in stacked marks. That is out of distribution for VietOCR, and LANCZOS already keeps small marks as grey.
   - If the developer wants it tested, make it an A/B arm with `OCR_MARK_GROW_PX = 1`, limited to components below the x-height band (dots under letters and full stops).
5. **Guard `upright`.**
   - Apply the shear only when the best slant's score beats `s = 0` by a set margin, for example a new `OCR_SLANT_MIN_GAIN` share.
   - Preferably estimate the slant per word-gap segment, so a mixed roman and italic line is not sheared as a whole.
   - Keep `OCR_MAX_SLANT = 0.4` and the bicubic, white-fill transform. They are correct.
6. **Keep greedy decoding (`OCR_BEAM_SEARCH = False`).**
   - The comment's reason is verified (`beam.py:73-119`). Add that it is VietOCR's own default (`base.yml:56`).
   - Update spec decision 6 (beam 4) and the spec's "VietOCR's input" block: "Height: always 32", and "W ≤ 2048" without the 512-trained caveat.
7. **Keep `_ink_tops`, the 4 px padding and grayscale `L` as they are.**
   - The taller crop costs about 1% of scale per extra px on an 80 px line, which is worth it for a mark over a capital.
   - VietOCR adds no padding and converts `L` to RGB itself.
