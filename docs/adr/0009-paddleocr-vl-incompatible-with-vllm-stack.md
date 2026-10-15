# PaddleOCR-VL is not used: Paddle cannot share an environment with torch/vLLM

We looked at PaddleOCR-VL (`PaddlePaddle/PaddleOCR-VL`) as a resume parser for its table handling, and dropped it before trying it, because `paddlepaddle-gpu` cannot be installed next to our pinned stack. vLLM 0.30 requires torch 2.13, which pins its own CUDA packages, and every Paddle GPU build pins different ones:

| Paddle build | Paddle needs | We pin (via torch) |
|---|---|---|
| 3.4.0, CUDA 13.0 | `cuda-toolkit==13.0.2`, `nvidia-nccl-cu13==2.30.7` | `cuda-toolkit==13.0.3`, `nvidia-nccl-cu13==2.29.7` |
| 3.3.1, CUDA 13.0 | `nvidia-cublas==13.0.2.14`, `nvidia-cuda-runtime==13.0.88` | `13.1.1.3`, `13.0.96` |
| 3.4.0, CUDA 12.9 | `cuda-python==12.9.4` → `cuda-bindings~=12.9.4` | `cuda-bindings==13.3.1` (torch needs 13.x) |

pip fails with `ResolutionImpossible` (checked 2026-10-15). Fitting Paddle in would mean downgrading torch and vLLM, which the whole pipeline runs on. Do not add `paddlepaddle-gpu` or `paddleocr` to `requirements.txt` without re-checking these pins.

## Consequences

- PyMuPDF4LLM stays the only parser (ADR 0008).
- A separate venv for Paddle would work, and so might the CPU `paddlepaddle` build (no CUDA pins) with the VL model served by vLLM; neither was tried.
- Even if installable, PaddleOCR-VL reads page images, so it is OCR: its Markdown would be model-generated, not the PDF's text layer, which clashes with the no-OCR rule (ADR 0007) and the fidelity check (ADR 0003), and Vietnamese is not among its named languages. Revisit those before adopting it.
