"""
The OCR Readings of a Part's printed lines, each read by VietOCR's vgg_transformer (settings.OCR_MODEL) on its own,
in this process on the GPU (docs/adr/0003-vietocr-reads-each-line.md beside the GLOSSARY).

VietOCR's config is its own config/base.yml and config/vgg-transformer.yml (pbcquoc/vietocr at the commit
requirements.txt pins), written out here so that nothing but the weights is fetched from vocr.vn, once, to
settings.OCR_WEIGHTS; its CNN is built without torchvision's ImageNet weights, which its own replace. Each OCR Reading
is saved as <results-dir>/<key>.json the way vlm_requests saves an answer, stamped with what it was read from, so
vlm_requests.current_answer reads it and a re-run reads only lines with no current OCR Reading. Each crop is cut at
its word gaps into pieces VietOCR reads within OCR_IMAGE_MAX_WIDTH, each word sheared upright on its own (pieces), at
full resolution: VietOCR scales each piece to OCR_IMAGE_HEIGHT itself. A line's OCR Reading is its pieces' readings
joined by spaces, each read greedily (settings.OCR_BEAM_SEARCH).
"""
import os
import time
from io import BytesIO
from typing import Any, Callable, Dict, NamedTuple

import numpy as np
import requests
from PIL import Image

from src.khotangtucngu.settings import (
    OCR_BEAM_SEARCH, OCR_GAP_SHARE, OCR_IMAGE_HEIGHT, OCR_IMAGE_MAX_WIDTH, OCR_IMAGE_MIN_WIDTH, OCR_INK_LEVEL,
    OCR_MAX_SLANT, OCR_MODEL, OCR_PAD_PX, OCR_SLANT_MIN_GAIN, OCR_SLANT_STEP, OCR_WEIGHTS, OCR_WEIGHTS_URL
)
from src.providers.vlm_requests import is_current, read_json, write_json

# The characters the weights were trained on, in their order (an answer's token n is VOCAB[n - 4]), as base.yml has
# them: the Vietnamese alphabet, digits, ASCII punctuation and the space
VOCAB = ("aAàÀảẢãÃáÁạẠăĂằẰẳẲẵẴắẮặẶâÂầẦẩẨẫẪấẤậẬbBcCdDđĐ"
         "eEèÈẻẺẽẼéÉẹẸêÊềỀểỂễỄếẾệỆfFgGhHiIìÌỉỈĩĨíÍịỊjJkKlLm"
         "MnNoOòÒỏỎõÕóÓọỌôÔồỒổỔỗỖốỐộỘơƠờỜởỞỡỠớỚợỢpPqQrRsStT"
         "uUùÙủỦũŨúÚụỤưƯừỪửỬữỮứỨựỰvVwWxXyYỳỲỷỶỹỸýÝỵỴzZ"
         "0123456789!\"#$%&'()*+,-./:;<=>?@[\\]^_`{|}~ ")
# VGG19-bn's pools, as [height, width] strides and kernels: height /16 (32 px to 2 rows), width /4
POOLS = [[2, 2], [2, 2], [2, 1], [2, 1], [1, 1]]


class Line(NamedTuple):
    key: str
    crop: Callable[[], bytes]   # the line's png
    # Input this line's OCR Reading depends on beyond the run's stamp (its crop box), saved and checked with it
    stamp: Dict[str, Any]


def reader_stamp():
    """What every OCR Reading depends on of the OCR model: its weights and how it reads a crop."""
    return {"ocr_model": OCR_MODEL, "ocr_weights": OCR_WEIGHTS_URL, "ocr_image_height": OCR_IMAGE_HEIGHT,
            "ocr_image_width": [OCR_IMAGE_MIN_WIDTH, OCR_IMAGE_MAX_WIDTH], "ocr_beam_search": OCR_BEAM_SEARCH}


def fetch_weights():
    """settings.OCR_WEIGHTS, downloaded from OCR_WEIGHTS_URL first if it isn't there."""
    if not os.path.exists(OCR_WEIGHTS):
        os.makedirs(os.path.dirname(OCR_WEIGHTS), exist_ok=True)
        print(f"[Kho tàng tục ngữ] Downloading the OCR model's weights from {OCR_WEIGHTS_URL} to {OCR_WEIGHTS}")
        partial = OCR_WEIGHTS + ".part"
        with requests.get(OCR_WEIGHTS_URL, stream=True, timeout=60) as r:
            r.raise_for_status()
            with open(partial, "wb") as f:
                for chunk in r.iter_content(chunk_size=1 << 20):
                    f.write(chunk)
        os.replace(partial, OCR_WEIGHTS)
    return OCR_WEIGHTS


def predictor():
    """VietOCR's vgg_transformer on the GPU, with its weights."""
    from vietocr.tool.predictor import Predictor
    return Predictor({
        "vocab": VOCAB,
        "device": "cuda",
        "seq_modeling": "transformer",
        # max_seq_length is the length of the positions table the weights hold, so it stays 1024
        "transformer": {"d_model": 256, "nhead": 8, "num_encoder_layers": 6, "num_decoder_layers": 6,
                        "dim_feedforward": 2048, "max_seq_length": 1024, "pos_dropout": 0.1, "trans_dropout": 0.1},
        "backbone": "vgg19_bn",
        "cnn": {"pretrained": False, "ss": POOLS, "ks": POOLS, "hidden": 256},
        "weights": fetch_weights(),
        "dataset": {"image_height": OCR_IMAGE_HEIGHT, "image_min_width": OCR_IMAGE_MIN_WIDTH,
                    "image_max_width": OCR_IMAGE_MAX_WIDTH},
        "predictor": {"beamsearch": OCR_BEAM_SEARCH},
    })


def upright(image):
    """`image` (a word's grayscale crop) sheared so its ink stands upright: each row moved right by the slant times its
    depth below the top, the slant being the one from 0 to OCR_MAX_SLANT that stacks the ink into the fewest columns,
    kept only if it stacks it more than OCR_SLANT_MIN_GAIN better than no slant (an upright word's marks and serifs
    can tip a near-tie), the image widened to keep all of it."""
    ys, xs = np.nonzero(np.asarray(image) < OCR_INK_LEVEL)
    if not xs.size:
        return image
    w, h = image.size

    def stacked(s):
        # A sheared row y of the output reads the input at x - s * y, so ink at (x, y) lands at x + s * y
        return int((np.bincount(np.rint(xs + s * ys).astype(int)).astype(np.int64) ** 2).sum())

    slant = max(np.arange(0, OCR_MAX_SLANT + OCR_SLANT_STEP / 2, OCR_SLANT_STEP), key=stacked)
    if not slant or stacked(slant) <= (1 + OCR_SLANT_MIN_GAIN) * stacked(0):
        return image
    return image.transform((w + int(np.ceil(slant * h)), h), Image.Transform.AFFINE, (1, -float(slant), 0, 0, 1, 0),
                           resample=Image.Resampling.BICUBIC, fillcolor=255)


def words(gray):
    """The words of `gray` (a line's grayscale crop), left to right, as [left, right) column ranges: its runs of
    inked columns, split where at least OCR_GAP_SHARE of its ink height of columns in a row are blank."""
    ink = np.asarray(gray) < OCR_INK_LEVEL
    rows, cols = np.flatnonzero(ink.any(axis=1)), np.flatnonzero(ink.any(axis=0))
    if not cols.size:
        return []
    breaks = np.flatnonzero(np.diff(cols) - 1 >= OCR_GAP_SHARE * (rows[-1] + 1 - rows[0]))
    starts = np.concatenate(([cols[0]], cols[breaks + 1]))
    stops = np.concatenate((cols[breaks], [cols[-1]])) + 1
    return [(int(a), int(b)) for a, b in zip(starts, stops)]


def pieces(image):
    """`image` (a line's crop) as VietOCR reads it before its own resize: in grayscale, each of its words sheared
    upright on its own (a line can mix roman and italic), the gaps between them kept as they were, cut at word gaps
    into pieces no wider than OCR_IMAGE_MAX_WIDTH is at OCR_IMAGE_HEIGHT with OCR_PAD_PX either side, so VietOCR
    never squeezes one (a word wider than that is a piece of its own)."""
    gray = image.convert("L")
    w, h = gray.size
    limit = OCR_IMAGE_MAX_WIDTH * h // OCR_IMAGE_HEIGHT - 2 * OCR_PAD_PX
    groups, width, before = [], 0, None  # each group [(gap before, sheared word)], its width, the last word's right
    for left, right in words(gray):
        word = upright(gray.crop((left, 0, right, h)))
        gap = 0 if before is None else left - before
        if groups and width + gap + word.width <= limit:
            groups[-1].append((gap, word))
            width += gap + word.width
        else:
            groups.append([(0, word)])
            width = word.width
        before = right
    if not groups:
        return [gray]
    cut = []
    for group in groups:
        piece = Image.new("L", (sum(gap + word.width for gap, word in group) + 2 * OCR_PAD_PX, h), 255)
        x = OCR_PAD_PX
        for gap, word in group:
            piece.paste(word, (x + gap, 0))
            x += gap + word.width
        cut.append(piece)
    return cut


def seen_image(cut):
    """The pieces `cut` as the OCR model sees them, side by side with a grey bar between: each scaled to
    OCR_IMAGE_HEIGHT by VietOCR's own resize (its width rounded up to a multiple of 10 within OCR_IMAGE_MIN_WIDTH and
    OCR_IMAGE_MAX_WIDTH), in grayscale, as the line's crop is."""
    from vietocr.tool.translate import resize
    seen = [piece.convert("RGB").resize(resize(*piece.size, OCR_IMAGE_HEIGHT, OCR_IMAGE_MIN_WIDTH,
                                               OCR_IMAGE_MAX_WIDTH), Image.LANCZOS).convert("L") for piece in cut]
    bar = 2
    joined = Image.new("L", (sum(s.width for s in seen) + bar * (len(seen) - 1), OCR_IMAGE_HEIGHT), 128)
    x = 0
    for s in seen:
        joined.paste(s, (x, 0))
        x += s.width + bar
    return joined


def read_lines(lines, results_dir, stamp, *, label):
    """Reads each of `lines` (Line) with no current OCR Reading in `results_dir` (made from `stamp` and its own),
    one at a time, and saves it there, with <key>.png, the line's pieces as the OCR model saw them, for the developer
    to check the reading against; a line the OCR model fails on is saved failed, so its page has no answer."""
    os.makedirs(results_dir, exist_ok=True)
    todo = []
    for line in lines:
        path = os.path.join(results_dir, f"{line.key}.json")
        line_stamp = {**stamp, **line.stamp}
        if os.path.exists(path) and is_current(read_json(path), line_stamp):
            continue
        todo.append((line, path, line_stamp))
    print(f"{label}: {len(todo)} line(s) to read with {OCR_MODEL}")
    if not todo:
        return
    reader, counts, started = predictor(), {}, time.monotonic()
    for n, (line, path, line_stamp) in enumerate(todo, 1):
        result = {"task": line.key, "phase": "ocr", "model": OCR_MODEL, **line_stamp}
        began = time.monotonic()
        try:
            cut = pieces(Image.open(BytesIO(line.crop())))
            seen_image(cut).save(os.path.join(results_dir, f"{line.key}.png"))
            answer = " ".join(filter(None, (reader.predict(piece).strip() for piece in cut)))
            result.update(status="ok", error=None, answer=answer)
        except Exception as e:
            result.update(status="failed", error=f"{type(e).__name__}: {e}")
            print(f"  [{n}/{len(todo)}] {line.key}: failed: {result['error'][:200]}")
        result["elapsed_s"] = round(time.monotonic() - began, 2)
        write_json(path, result)
        counts[result["status"]] = counts.get(result["status"], 0) + 1
        if n % 100 == 0 or n == len(todo):
            print(f"  [{n}/{len(todo)}] {counts}")
    print(f"{label}: finished in {time.monotonic() - started:.0f}s: {counts}")
