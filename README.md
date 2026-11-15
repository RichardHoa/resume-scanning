# Vietnamese Resume Screening

Extracts structured data from Vietnamese PDF resumes and evaluates each candidate against one job's HR requirements
with a locally served LLM (vLLM). For every candidate HR gets a score per Category, an Overall Score and Match
Recommendation, any Must-have Rejection, and Candidate Feedback written by a Review Panel. HR works in a Vietnamese
web workbench; the same pipeline also runs as SLURM batch jobs.

Domain terms (Criterion, Verdict, HR RAG, Combined Extraction, ...) are defined in [`GLOSSARY.md`](GLOSSARY.md);
design decisions are recorded in [`docs/adr/`](docs/adr/).

---

## 💡 How It Works

1. **Parse**: PyMuPDF4LLM turns the PDF into layout-aware Markdown (Docling was tried and rejected, ADR 0002). A
   Scanned Resume (no page has text) is rejected and HR asks the candidate for a text PDF; no OCR is run (ADR 0002).
2. **Extract** (Combined Extraction, ADR 0003): the model sees each page's image as well as the text. The
   images give only the layout; every value is copied from the PDF text (ADR 0001), and a fidelity check flags any
   value not found there as a Fidelity Warning. The output follows `schemas/qwen_schema.json`. Extraction needs a
   model that can see images.
3. **Set the HR RAG** (website, RAG page): HR's requirement text is checked for Implicit Assumptions (Clarification
   Questions), then split into Criteria across five Categories, with HR Check Items set aside (ADR 0006). HR reviews
   the Criteria and sets each one's Importance: Must-have, Standard or Nice-to-have (ADR 0007 / 0008).
   Evaluation only reads the HR RAG and stops if there is none (ADR 0005).
4. **Evaluate**: each Category is judged in five greedy runs (ADR 0009). The LLM gives
   each Criterion a Verdict; the code votes each Verdict across the runs and turns the voted Verdicts into Category
   Scores, the Overall Score and the Match Recommendation. A Must-have with No Evidence in most runs is a Must-have Rejection.
5. **Review Panel** (ADR 0011): three Panelists and a Coordinator write the Candidate Feedback. It never changes the
   scores, and runs only for fully scored candidates that are not rejected.

### Model

The only model in use is the default profile `sea-lion-v4.5-27b` (`aisingapore/Qwen-SEA-LION-v4.5-27B-IT`, 40
requests in flight). `scripts/server.sh --lightweight` serves the small `qwen3.5-9b` profile instead. Profiles live
in `scripts/lib/model_profiles.sh`; every job takes a profile key (or a raw HuggingFace ID) as its model argument.

---

## 📁 Project Layout

```
src/
  cli/            command-line entry points (extract, evaluate, backfill_feedback)
  pipelines/      extractor, evaluator, scoring, review_panel, ground_truth
  prompts/        every LLM prompt
  providers/      vLLM client, HR RAG store (rag_engine)
  api/ + server.py, templates/, static/   the FastAPI web workbench
  core/           config (paths, defaults), run folders, logging, Reference Date, Evaluation Order
  bias/           the Bias Check suites
  step_1_extractor.py, step_2_evaluate.py, ground_truth.py   thin entry-point shims
scripts/
  pipeline/       SLURM jobs: extract_evaluate.sh, extract.sh, evaluate.sh, feedback.sh
  checks/         extractor accuracy, evaluator consistency and bias checks, token_stats.py
  lib/            shared shell helpers: config.sh, model_profiles.sh, vllm_utils.sh
  server.sh       starts and stops vLLM + the website
schemas/          the extraction JSON schema
Vietnamese-dataset/CnB, Vietnamese-dataset/Tech   the two resume sets (not in git)
rag/              the stored HR RAG (not in git)
runs/             every output, one run folder per job (not in git)
approved_jsons/   HR-approved extractions, from src/ground_truth.py (not in git)
docs/adr/, GLOSSARY.md, .scratch/   decisions, vocabulary, specs and issues
```

The secret `evaluation_order.txt` / `evaluation_order_tech.txt` and `hr-requirement.txt` / `hr-requirement-tech.txt`
exist only on the compute machine.

### Where outputs go

Every output lives in one run folder under `runs/` (ADR 0004):

| Run folder | Written by | Wiped |
| --- | --- | --- |
| `batch-cnb`, `batch-tech` | the pipeline jobs (`--cnb` / `--tech`, one is required) | at the start of each job (`evaluate.sh`: only the evaluations) |
| `web-cnb`, `web-tech` | the website started with `--cnb` / `--tech` | never |
| `web` | the website started with neither flag (no dataset: no Evaluation Order, no pipeline results) | never |
| `extractor-accuracy` | the Extractor Accuracy Check | at the start of the check |
| `evaluator-consistency-{cnb,tech}` | the evaluator consistency check | at the start of the check |
| `bias-cnb` | the Bias Check | at the start of each check |

Each holds `logs/` (job, vLLM and extractor/evaluator logs, `token_usage.jsonl`), `prompt_logs/<resume>/<category>/`,
`extraction_markdown/`, `extraction_json/`, `evaluation_json/` and `resumes_pdf/`. The website also shows the
matching pipeline run folder's results, read-only, and each candidate's "Chi tiết cho nhà phát triển" panel shows
everything stored for that resume. SLURM's own `.out` / `.err` files go to `logging/`.

---

## 🖥️ Cluster Setup

1. Start the NetBird VPN and SSH into the login node: `ssh slurmdang14@100.84.19.126`.
2. Create the Conda environment (Conda and package caches on `/compute_home`, the 2TB SSD, since the home quota is
   small):

   ```bash
   module load miniconda3
   conda create -n resume_env python=3.11 -y
   source activate resume_env
   pip install -r requirements.txt
   ```

   `requirements.txt` pins `vllm` and the CUDA packages, and holds shared dependencies (e.g. `fastapi`, `numpy`) at
   the versions `vllm` needs. Install it only in this GPU compute-node environment.
3. Submit jobs from the repository root with `sbatch` (below). Every job loads its modules, activates `resume_env`,
   starts its own vLLM server on a free port and stops it at the end. Inference never runs on the login node.

---

## 🚀 Running

### The website

On the GPU compute node:

```bash
./scripts/server.sh --cnb      # vLLM + website for the CnB resume set (runs/web-cnb)
./scripts/server.sh --tech     # the Tech resume set (runs/web-tech, Reference Date December 2015)
./scripts/server.sh            # no dataset loaded (runs/web)
./scripts/server.sh --status
./scripts/server.sh --stop
```

The website is on port 8005. `--lightweight` serves `qwen3.5-9b`; `--start-vllm` / `--start-web` (and the matching
`--stop-*`) start or stop one half; `--help` lists everything. Logs: `logs/server.txt` (daemon),
`logs/vllm_server.log`, `<run folder>/logs/web_server.log`.

In the website, set the HR RAG on the RAG page first, then upload a folder or several resumes; they are extracted and
evaluated in parallel as one Batch.

### Pipeline jobs

Set the resume set's HR RAG on the website before any job that evaluates. `--cnb` reads `Vietnamese-dataset/CnB`;
`--tech` reads `Vietnamese-dataset/Tech` with the Reference Date set to 2015-12-31 (the HR RAG must then hold the Tech
requirements). `[model]` defaults to the default profile.

| Job | What it does | Needs |
| --- | --- | --- |
| `sbatch scripts/pipeline/extract_evaluate.sh [pdf_dir] [model] --cnb\|--tech` | The main job: wipes `runs/batch-*`, extracts every PDF, evaluates every extraction (Category runs + Review Panel), prints token stats | HR RAG, vision profile |
| `sbatch scripts/pipeline/extract.sh [pdf_dir] [model] --cnb\|--tech` | Wipes `runs/batch-*` and extracts only | vision profile |
| `sbatch scripts/pipeline/evaluate.sh [model] --cnb\|--tech` | Wipes only the evaluations and re-evaluates the kept extractions (extracts first if there are none) | HR RAG; vision profile if it must extract |
| `sbatch scripts/pipeline/feedback.sh [report_dir] [model]` | Backfills missing, skipped or failed Candidate Feedback into existing reports (default `runs/batch-cnb/evaluation_json`); never re-scores | — |

### Checks

| Job | What it does | Report |
| --- | --- | --- |
| `sbatch scripts/checks/extractor_accuracy.sh [model]` | Extracts every resume with a Ground Truth Extraction (`data/extraction_ground_truth/`) 5 times and reports how often each value matches it | `runs/extractor-accuracy/accuracy_report.md` |
| `sbatch scripts/checks/evaluator_consistency.sh [model] --cnb\|--tech` | Extracts one set once, then runs 5 Repeat Evaluations and reports what flips (needs the HR RAG) | `runs/evaluator-consistency-*/evaluator_consistency_report.md` |
| `sbatch scripts/checks/evaluator_bias.sh [--<category>]` | The Bias Check on one fixed CnB resume, default model only (needs the CnB HR RAG) | `runs/bias-cnb/report.html` |

`python3 scripts/checks/token_stats.py` summarizes a run folder's token usage per pipeline step (`RUN_DIR=batch-tech`
for another folder).

### Command line (inside a GPU session with vLLM already serving)

```bash
python3 src/step_1_extractor.py --pdf resume.pdf --output out.json --vllm-url http://127.0.0.1:8100/v1
python3 src/step_1_extractor.py --dir Vietnamese-dataset/CnB --output runs/batch-cnb/extraction_json --workers 6
python3 src/step_2_evaluate.py --dir runs/batch-cnb/extraction_json --output runs/batch-cnb/evaluation_json
```

`step_2_evaluate.py` also takes `--num-evaluations N` (runs per Category, default 3), `--no-feedback` (skip the
Review Panel) and `--reference-date YYYY-MM-DD`. Both scripts, and `src/server.py`, take `--mock` to run without a
model. The run folder comes from the `RUN_DIR` environment variable (default `runs/batch-cnb`).

### Approving extractions

```bash
python3 src/ground_truth.py   # review and approve extractions into approved_jsons/ at http://localhost:8000
```

Extraction accuracy is measured by the Extractor Accuracy Check (`sbatch scripts/checks/extractor_accuracy.sh`).
