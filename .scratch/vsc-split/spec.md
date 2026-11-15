Status: ready-for-agent

# VSC split: move the scanned-book work to vsc-work, remove the transcript and DSPy code

Requirement collection only. Nothing here is implemented yet. Every question is settled.

## Problem Statement

resume-scanning also holds the scanned-book transcription work for VSC (Kho tàng tục ngữ người Việt, Nữ Giới Chung, the AI Proofreading Pass for Truyện cổ dân gian), an audio interview transcription tool, and a DSPy prompt optimizer that no longer matches the Verdict format. The repo should hold resume-scanning only. The VSC work moves to its own repo at `/Users/linux/Documents/CODE/vsc-work` (empty today, not a git repo); the transcript and DSPy code are deleted.

## Decisions

### What moves to vsc-work

Same layout as today (`src/…`, `scripts/…`, `vsc-project/…`), so `from src.khotangtucngu…` imports and submit-script paths keep working unchanged. Renaming can happen later inside vsc-work.

- **Kho tàng tục ngữ:** `src/khotangtucngu/`, `scripts/khotangtucngu/`, `docs/research/khotangtucngu-*.md` (3 files), `vsc-project/khoTangTucNguoiNguoiViet/` (with its GLOSSARY.md and all untracked data)
- **Nữ Giới Chung:** `src/nugioichung/` (with its GLOSSARY.md and `docs/adr/0001`, `0002`), `scripts/nugioichung/`, `vsc-project/NuGioiChung/`
- **AI Proofreading Pass** (goes to vsc-work, not to `vsc-truyen-co-dan-gian-viet-nam`): `src/cli/proofread.py`, `src/pipelines/proofreader.py`, `src/prompts/proofread_prompts.py`, `scripts/proofread/`, `tests/test_proofreader.py`, `vsc-project/truyen-co-dan-gian-cham/`
- **Audio data only:** `vsc-project/audio-transcribe/` (the `.m4a`, the reviewed transcript, context and ground truth), so the recording survives the code's deletion
- **Issues:** every `.scratch/kho-tang-tuc-ngu*/` and `.scratch/nugioichung*/` folder
- **Run log:** `runs/slurm_khotangtucngu_7357.out` → `vsc-work/runs/`
- `requirements-macos.txt` (Kho tàng's Apple Vision step)

After the move, `vsc-project/` no longer exists in resume-scanning.

### Shared model-serving code: copied and trimmed, never shared

- **vsc-work gets copies** of `src/providers/vllm_client.py`, `vlm_requests.py`, `page_images.py`, `src/core/config.py`, `scripts/lib/{config,model_profiles,vllm_utils,vision_job}.sh`, plus whatever `__init__.py` files the imports need, each trimmed to what the VSC code uses (e.g. resume-only settings dropped from `config.py`).
- **resume-scanning deletes** `src/providers/page_images.py`, `src/providers/vlm_requests.py`, `scripts/lib/vision_job.sh`, `require_vision_profile` and `serve_vision_on` in `scripts/lib/model_profiles.sh`, and the `PROOFREAD_*` settings in `src/core/config.py`. Comments that point at the moved code (e.g. `scripts/khotangtucngu/submit.sh` in `vllm_client.py`) are reworded or dropped. It keeps `vllm_client.py` and the model profiles.

### Transcript code: deleted

`src/cli/{transcribe_audio,review_transcript,score_transcript,fix_names}.py`, `src/prompts/transcript_*`, `scripts/audio/`, `docs/audio-transcribe.md`, `requirements-audio.txt`, `.scratch/audio-transcribe/`. (The data folder moves; see above.)

### DSPy: deleted

`src/optimization/`, `src/cli/train_prompts.py`, `scripts/dspy/`, `DSPY_MAX_TOKENS` in `src/core/config.py`, `dspy-ai` in `requirements.txt`, the README's "DSPy prompt training" section, and any DSPy hooks in `src/prompts/evaluator_prompts.py`. ADRs 0007/0008 and old `.scratch` specs that mention DSPy stay untouched as history.

### Requirements

- resume-scanning's `requirements.txt` drops every package that only the moved or deleted code imports (candidates: `opencv-python`, `scipy`, `PyYAML`, PyMuPDF extras), decided by an import check. `pymupdf` stays (`src/pipelines/extractor.py`).
- vsc-work gets its own `requirements.txt` with only what the VSC code imports, at the versions resume-scanning pins today.

### Domain docs and repo setup

- **resume-scanning:** single context. Delete `GLOSSARY-MAP.md` (`CLAUDE.md` already says single-context). Remove the `/vsc-project/**` rules from `.gitignore`. README drops the proofreader, Kho tàng tục ngữ, audio and DSPy sections and their mentions in the layout overview (`cli/`, `pipelines/`, `scripts/` lines).
- **vsc-work:**
  - `GLOSSARY-MAP.md` listing Kho tàng tục ngữ (`vsc-project/khoTangTucNguoiNguoiViet/GLOSSARY.md`) and Nữ Giới Chung (`src/nugioichung/GLOSSARY.md`); the proofreader has no glossary.
  - `CLAUDE.md` and `docs/agents/` copied from resume-scanning, with "Domain docs" changed to multi-context via `GLOSSARY-MAP.md`.
  - `.gitignore` with the `/vsc-project/**` rules (keeping `review.jsonl` tracked) plus the generic ones (`.DS_Store`, `__pycache__`, `/runs`, `/export`).
  - New `README.md` built from the moved README sections (proofreader, Kho tàng tục ngữ, Nữ Giới Chung) plus setup steps.
  - Plain copy, no git history. `git init` only; nothing committed. The developer makes every commit.

### Out of scope

The bias runner and consistency scripts stay. Untracked empty folders in the root (`approved_jsons`, `broken-json`, `eval_results`, `evaluation_json`, `extraction_markdown`, `logging`, `rag`, `resumes_pdf`, `server_state`), the root `__pycache__`, `frontend-fix.md`, `pdfs/`, `Report/` and `design-system/` are left alone. Integrating the proofreader into the `vsc_ocr` repo is a separate job.

## Done when

- `grep -riE "khotangtucngu|nugioichung|proofread|vsc-project|transcri|dspy|vision_job|page_images|vlm_requests"` over resume-scanning's tracked files hits only ADRs and old `.scratch` specs kept as history.
- Every import in vsc-work's `src/` resolves to a file inside vsc-work, and every `scripts/lib` path its submit scripts source exists there.
- Nothing is committed in either repo.

## Comments

**Implementation notes (2026-11-15):**

- `require_vision_profile` and `serve_vision_on` stay in resume-scanning's `scripts/lib/model_profiles.sh`: Combined Extraction (`server.sh`, `scripts/pipeline/*`, `scripts/checks/*`) uses both. vsc-work's copy drops `require_vision_profile`, `resolve_model_arg` and `COMBINED_MAX_PAGES` instead.
- resume-scanning's `vllm_client.chat` also loses the VSC-only `text_output`, `stop`/`stop_string` and `usage_file` options; vsc-work's copy loses the resume-only usage helpers, and its usage record names the `task` instead of `resume_name`.
- `requirements.txt` only drops `dspy-ai` and `optuna`. `scipy` and `PyYAML` were imported by the moved code but are also pinned dependencies of `scikit-learn` and `transformers`/`vllm`, so they stay. `opencv-python` was not imported by the moved code.
- The Kho tàng `GLOSSARY.md`, `docs/adr/` and front/back matter were never tracked here (ignored by `/vsc-project/**`); vsc-work's `.gitignore` tracks them.
- vsc-work's AI Proofreading Pass now writes `token_usage.jsonl` into its run folder like the other two jobs; `scripts/checks/token_stats.py` was copied for `print_token_stats`.
- 1076 files under resume-scanning's `vsc-project/khoTangTucNguoiNguoiViet/store/` are owned by root and could not be deleted without sudo; all are copied to vsc-work.
