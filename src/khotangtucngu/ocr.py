"""
The OCR Readings of a Part's printed lines, each read by VietOCR's vgg_transformer (settings.OCR_MODEL) on its own,
in this process on the GPU (docs/adr/0003-vietocr-reads-each-line.md beside the GLOSSARY).

VietOCR's config is its own config/base.yml and config/vgg-transformer.yml (pbcquoc/vietocr at the commit
requirements.txt pins), written out here so that nothing but the weights is fetched from vocr.vn, once, to
settings.OCR_WEIGHTS; its CNN is built without torchvision's ImageNet weights, which its own replace. Each OCR Reading
is saved as <results-dir>/<key>.json the way vlm_requests saves an answer, stamped with what it was read from, so
vlm_requests.current_answer reads it and a re-run reads only lines with no current OCR Reading.
"""
import os
import time
from io import BytesIO
from typing import Any, Callable, Dict, NamedTuple

import requests
from PIL import Image

from src.khotangtucngu.settings import (
    OCR_BEAM_SEARCH, OCR_IMAGE_HEIGHT, OCR_IMAGE_MAX_WIDTH, OCR_IMAGE_MIN_WIDTH, OCR_MODEL, OCR_WEIGHTS,
    OCR_WEIGHTS_URL
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


def seen_image(image):
    """`image` as the OCR model sees it: scaled to OCR_IMAGE_HEIGHT by VietOCR's own resize (its width rounded up to
    a multiple of 10 within OCR_IMAGE_MIN_WIDTH and OCR_IMAGE_MAX_WIDTH), in grayscale, as the line's crop is."""
    from vietocr.tool.translate import resize
    w, h = resize(*image.size, OCR_IMAGE_HEIGHT, OCR_IMAGE_MIN_WIDTH, OCR_IMAGE_MAX_WIDTH)
    return image.convert("RGB").resize((w, h), Image.LANCZOS).convert("L")


def read_lines(lines, results_dir, stamp, *, label):
    """Reads each of `lines` (Line) with no current OCR Reading in `results_dir` (made from `stamp` and its own),
    one at a time, and saves it there, with <key>.png, the line as the OCR model saw it, for the developer to check
    the reading against; a line the OCR model fails on is saved failed, so its page has no answer."""
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
            image = Image.open(BytesIO(line.crop()))
            seen_image(image).save(os.path.join(results_dir, f"{line.key}.png"))
            result.update(status="ok", error=None, answer=reader.predict(image).strip())
        except Exception as e:
            result.update(status="failed", error=f"{type(e).__name__}: {e}")
            print(f"  [{n}/{len(todo)}] {line.key}: failed: {result['error'][:200]}")
        result["elapsed_s"] = round(time.monotonic() - began, 2)
        write_json(path, result)
        counts[result["status"]] = counts.get(result["status"], 0) + 1
        if n % 100 == 0 or n == len(todo):
            print(f"  [{n}/{len(todo)}] {counts}")
    print(f"{label}: finished in {time.monotonic() - started:.0f}s: {counts}")
