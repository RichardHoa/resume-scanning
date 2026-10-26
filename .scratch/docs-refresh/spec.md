# Docs refresh: README and shell-script comments

Status: ready-for-human

The README describes an early, extraction-only version of the project, and many header and step comments in
`scripts/` no longer match what the scripts or the Python code do. This plan lists every place that is out of
date and what each should say. Comments only: the behaviour bugs found along the way are listed at the end and
are **not** part of this change unless the developer asks for them.

## 1. README.md: rewrite

### What is wrong now

- **Approach**: says Markdown alone goes to the LLM. Every extraction is now Combined Extraction (PDF text plus page
  images for layout only, ADR 0013/0015), which needs a vision profile. Evaluation is not described at all.
- **Models**: recommends Qwen3.5-35B-A3B / 9B. The only model used is the default profile `sea-lion-v4.5-27b`
  (`aisingapore/Qwen-SEA-LION-v4.5-27B-IT`, CONCURRENCY=40); `qwen3.5-9b` only through `server.sh --lightweight`.
- **Project structure**: lists `schemas/nuextract_schema.json` (does not exist) and only the old `src/step_*.py`
  shims. It leaves out `src/cli`, `src/pipelines`, `src/api`, `scripts/`, `runs/`, `rag/`, `docs/adr`, `GLOSSARY.md`.
  `pdfs/` holds the cluster guide and a paper, not resumes; the resume sets are `Vietnamese-dataset/CnB` and `/Tech`.
- **How to run**: only shows `step_1_extractor.py` and `python3 src/server.py`. Missing: the HR RAG step (set on the
  website's RAG page before any evaluation, ADR 0005), `step_2_evaluate.py` and its flags (`--num-evaluations`,
  `--no-feedback`, `--reference-date`), and every sbatch job.
- **SLURM section**: the interactive `srun --partition=student` example and "Step 4: run the extractor by hand"
  predate the sbatch jobs; most jobs now ask for `student9696` with the RTX Pro 6000 96GB GPU.

### Proposed outline

1. What it does (one paragraph): extract → evaluate against HR's Criteria → Must-have Rejection, scores, Review
   Panel Candidate Feedback; web workbench for HR. Link `GLOSSARY.md` for terms.
2. Pipeline in brief: PyMuPDF4LLM text + page images (Combined Extraction), scanned PDFs rejected; HR RAG and
   Criteria (Importance, must-have / nice-to-have); Category runs (3 per category, median); Review Panel. Each line
   links its ADR.
3. Model: the default profile, `--lightweight`, where profiles live (`scripts/lib/model_profiles.sh`).
4. Project layout: a short tree of the real folders.
5. Run folders: keep the current "Where outputs go" text (it is correct), add the check folders
   (`runs/extractor-consistency-*`, `runs/evaluator-consistency-*`, `runs/bias-cnb`) and that token usage is
   `<run>/logs/token_usage.jsonl`.
6. Cluster setup: VPN, SSH, conda env from `requirements.txt` (keep), then the job table below.
7. Jobs table — one row per script: command, what it wipes, what it needs (HR RAG? vision?), where output goes:
   `pipeline/extract_evaluate.sh`, `pipeline/extract.sh`, `pipeline/evaluate.sh`, `pipeline/feedback.sh`,
   `server.sh`, `checks/extractor_consistency.sh`, `checks/evaluator_consistency.sh`, `checks/evaluator_bias.sh`.
8. Running locally without a GPU: `--mock` on extract / evaluate / server.
9. Extraction accuracy (`src/evaluate.py` vs `approved_jsons/`) and ground-truth tool (`src/ground_truth.py`).
10. Side tools, short, each linking its own doc: AI Proofreading Pass (keep the current text), audio transcription
    (`docs/audio-transcribe.md`), DSPy training.
11. Private files: `evaluation_order*.txt` and `hr-requirement*.txt` exist only on the compute machine.

## 2. Shell scripts: comment fixes

### All sbatch scripts

- The `STEP n` banner comments and the `STEP n` echo lines disagree (e.g. `extract_evaluate.sh` prints "STEP 2" inside
  the "STEP 1" block; `extract.sh` / `evaluate.sh` / `feedback.sh` echo STEP 1–3 with no matching comments;
  `dspy/train.sh` prints "STEP 4" as its first step). Make each script's comment headers and echoes use one numbering.
- "High-Speed" / "High-Precision" titles in headers and echoes: replace with plain names of what the job does.

### `scripts/pipeline/evaluate.sh`

- Title says "vLLM Resume Evaluation Server": it is a batch evaluation job.
- Header should also say: the HR RAG must be set first (job stops before the server starts); `--tech` sets the
  Reference Date to 2015-12-31; each category runs 3 times (median) and the Review Panel writes Candidate Feedback.

### `scripts/pipeline/extract_evaluate.sh`

- Header is mostly right. Add: the Review Panel runs as part of evaluation; token stats are printed at the end.
- "(the HR RAG and approved_jsons are kept)" — fine, keep.

### `scripts/pipeline/extract.sh`

- Header is right; only the title and STEP numbering.

### `scripts/pipeline/feedback.sh`

- Header should say where prompt logs go: the report dir's run folder when it is one of `batch-*` / `web*`,
  otherwise the default `runs/batch-cnb`; and that the vLLM log is `logs/vllm_batch.log`.

### `scripts/server.sh`

- Header: add that the model must see images and vLLM is served with vision on (Combined Extraction); list the
  `--start-server` / `--stop-server` aliases the dispatcher accepts (also missing from `--help`).
- `setup_environment` creates `temp_uploads` and `static` at the repo root — confirm they are still used; drop
  from the comment/README if not.

### `scripts/lib/config.sh`

- Header "Centralized Shell Configuration" — say what it gives: repo root + PYTHONPATH, `VLLM_MAX_MODEL_LEN`,
  `require_hr_rag`, the run-folder helpers.
- `_require_pipeline_run_dir` comment says "pipeline and consistency run folders"; it also allows `runs/bias-cnb`.
- The `VLLM_MAX_MODEL_LEN` line falls back to 32768 silently when `src.core.config` can't import; say so.

### `scripts/lib/vllm_utils.sh`

- Header: also sourced by `server.sh`, not only SLURM scripts.
- The "vllm not installed" message tells the user to `pip install vllm`; point to `pip install -r requirements.txt`
  instead (vllm is pinned there).
- `start_vllm_server` usage comment: note the default model and default log path.

### `scripts/lib/model_profiles.sh`

- Header: add that only `sea-lion-v4.5-27b` (default) is used, `qwen3.5-9b` only via `--lightweight`; the other
  profiles are kept for reference.

### `scripts/checks/*.sh`

- `evaluator_bias.sh`: header lists `--dry-run` without saying what it does — add one line.
- `evaluator_consistency.sh`, `extractor_consistency.sh`: headers match the Python (report names verified). Only
  the STEP numbering.

### `scripts/dspy/train.sh`

- Header is one line: add usage (`[model]`), that it reads `runs/batch-cnb/extraction_json`, writes
  `prompts/dspy_compiled_prompt.json`, and logs to `training.txt` at the repo root.

### `scripts/proofread/submit.sh`, `scripts/audio/*.sh`

- Headers match the code. No change.

### `scripts/checks/token_stats.py` (docstring)

- Says it reads `logging/token_usage.jsonl`; it reads `<RUN_DIR>/logs/token_usage.jsonl`.

## Behaviour bugs found (not in this change)

1. `evaluate.sh` auto-extracts when the run folder has no extractions, but never calls `require_vision_profile` /
   `serve_vision_on`, so that extraction runs against a text-only server although every extraction is Combined
   Extraction.
2. `feedback.sh` deletes `logging/token_usage.jsonl` before the run, but token usage is written to
   `<RUN_DIR>/logs/token_usage.jsonl`, so old usage is never cleared and `token_stats.py` mixes runs.
3. `evaluate.sh`, `extract.sh`, `feedback.sh`, `dspy/train.sh` source `config.sh` before activating `resume_env`, so
   its `python3 -c` (VLLM_MAX_MODEL_LEN) runs on the system Python and can silently fall back to 32768.
   `extract_evaluate.sh` and the checks already activate conda first.
4. `dspy/train.sh` never loads modules or activates `resume_env`.

## Order of work

1. Script comments (small, mechanical; one script at a time).
2. README rewrite against the corrected scripts.
3. Developer decides whether to open tickets for the four bugs.

## Comments

**2026-10-26, implemented** (all of sections 1–2 and the four bugs, in one pass):

- Bug 1: `evaluate.sh` counts the extractions before starting vLLM; with none it checks the PDF dir, calls
  `require_vision_profile` and `serve_vision_on`, and extracts with `--workers 6` like the other jobs.
- Bug 2: fixed by deleting the `rm` rather than pointing it at `<RUN_DIR>/logs/token_usage.jsonl`, because that
  file also holds the run's extraction and evaluation usage, which the developer-details panel reads. The printed
  token stats now cover the whole run folder, the Review Panel step included.
- Bug 3: `evaluate.sh`, `extract.sh`, `feedback.sh`, `dspy/train.sh` and also `proofread/submit.sh` (same bug)
  now activate `resume_env` before sourcing `config.sh`. `audio/submit_transcript.sh` still sources it first; there
  the audio venv is used before resume_env, so it was left as is.
- Bug 4: `dspy/train.sh` now loads modules and activates `resume_env`.
- `server.sh` no longer creates the unused repo-root `temp_uploads/` and `static/` (src/server.py makes its own
  under `src/`).
- README: the old `src/evaluate.py --extracted/--ground-truth` example was wrong; the flags are `--gt-dir` /
  `--pred-dir`.
