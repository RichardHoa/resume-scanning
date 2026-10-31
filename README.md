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
4. **Evaluate**: each Category is judged in five runs (run 1 greedy, later runs sampled, ADR 0009). The LLM gives
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
  cli/            command-line entry points (extract, evaluate, backfill_feedback, benchmark, proofread, audio, ...)
  pipelines/      extractor, evaluator, scoring, review_panel, ground_truth, proofreader
  prompts/        every LLM prompt
  providers/      vLLM client, HR RAG store (rag_engine)
  api/ + server.py, templates/, static/   the FastAPI web workbench
  core/           config (paths, defaults), run folders, logging, Reference Date, Evaluation Order
  bias/           the Bias Check suites
  step_1_extractor.py, step_2_evaluate.py, evaluate.py, ground_truth.py   thin entry-point shims
scripts/
  pipeline/       SLURM jobs: extract_evaluate.sh, extract.sh, evaluate.sh, feedback.sh
  checks/         consistency and bias checks, token_stats.py
  lib/            shared shell helpers: config.sh, model_profiles.sh, vllm_utils.sh
  server.sh       starts and stops vLLM + the website
  proofread/, audio/, dspy/   side tools (see below)
schemas/          the extraction JSON schema
Vietnamese-dataset/CnB, Vietnamese-dataset/Tech   the two resume sets (not in git)
rag/              the stored HR RAG (not in git)
runs/             every output, one run folder per job (not in git)
approved_jsons/   verified ground-truth extractions (not in git)
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
| `extractor-consistency-{cnb,tech}`, `evaluator-consistency-{cnb,tech}` | the consistency checks | at the start of each check |
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
| `sbatch scripts/checks/extractor_consistency.sh [model]` | Extracts every resume of both sets 5 times and reports what changes, with every Fidelity Warning and failed run | `runs/extractor-consistency-{cnb,tech}/consistency_report.md` |
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

### Extraction accuracy

```bash
python3 src/evaluate.py --gt-dir approved_jsons --pred-dir runs/batch-cnb/extraction_json
python3 src/ground_truth.py   # review and approve ground-truth extractions at http://localhost:8000
```

---

## 🧰 Side Tools

### AI Proofreading Pass (scanned books)

`scripts/proofread/submit.sh` has a model transcribe every page of a scanned book from its scan, with the OCR
text as a draft, and joins the pages into a new text of the book.

1. In the vsc repo, run `python -m vsc_ocr prepare-ai <book>` and copy the folder it makes, `data-for-ai/<book>/`,
   here as `vsc-project/`.
2. Run the pass:

```bash
bash scripts/proofread/submit.sh --dry-run              # login node: checks every task fits the context window
sbatch scripts/proofread/submit.sh --pages 10-40         # a trial slice
sbatch scripts/proofread/submit.sh --pages 10-40 --no-ocr-hint   # the same slice from the images only
sbatch scripts/proofread/submit.sh                       # the whole book
sbatch scripts/proofread/submit.sh --run-dir vsc-project/ai-pass/<time>   # finish a run's failed tasks
```

3. Copy `book.ai.md`, `ai_corrections.jsonl` and `boxes.jsonl` from the run folder `vsc-project/ai-pass/<time>/`
   back to `data/books/<book>/ai/` in the vsc repo and review them there with `python -m vsc_ocr review <book> --ai`.

`coverage.jsonl` in the run folder lists, page by page, the OCR lines the model left out (put back, marked
`⚠ ai-missed?`) and the text it wrote that the OCR didn't see (marked ⚠). To choose between sending the OCR draft
or not, compare two runs of the same slice against the reviewer's own corrections:

```bash
python3 scripts/proofread/compare_ocr_hint.py vsc-project/ai-pass/<with-hint> vsc-project/ai-pass/<without>
```

### Kho tàng tục ngữ người Việt (scanned proverb collection)

`src/khotangtucngu` transcribes the Proverb Entries of one PDF Part of the book with the default vision model,
one request per PDF page. It then lets you review them page by page against the scan and exports website data.
Its terms (PDF Part, Proverb Entry, Citation, Warning, Fix, ...) are in
[`vsc-project/khoTangTucNguoiNguoiViet/GLOSSARY.md`](vsc-project/khoTangTucNguoiNguoiViet/GLOSSARY.md). The Parts,
their proverb pages and book page offsets are in `src/khotangtucngu/settings.py`; only `--part-1` (PDF pages 36–865)
is set up now.

Everything for one Part lives in its store, `vsc-project/khoTangTucNguoiNguoiViet/store/<part>/`. `vsc-project/` is
not in git apart from `front-matter.md`, so first copy the Part's PDF there on the cluster
(`kho tàng tục ngữ người việt tập 1 - p1.pdf`).

**1. Transcribe (cluster, from the repository root).**

```bash
bash scripts/khotangtucngu/submit.sh --part-1 --dry-run            # login node: token counts, sends nothing
sbatch scripts/khotangtucngu/submit.sh --part-1 --pages 36-45,420-424   # a trial, with an entry over a page break
sbatch scripts/khotangtucngu/submit.sh --part-1                    # every proverb page of the Part
sbatch scripts/khotangtucngu/submit.sh --part-1 --pages 420        # redo the pages you name (ranges and single pages)
```

- Each page's answer is saved as soon as it arrives. A rerun only redoes pages that failed, never ran, or were made
  under a different prompt, image setting or PDF. If the full run hits the job's 4-hour limit, submit the same
  command again and it carries on.
- Runs over different pages add up in the store. The outputs are rebuilt from every saved answer each time.
- `--dry-run` writes its per-request counts to `store/<part>/dry_run_tokens.jsonl`.
- Logs: `logging/slurm_khotangtucngu_<job>.out`, plus `logs/vllm_khotangtucngu.log` for the server.

A run writes into the store:

| File | What it holds |
| --- | --- |
| `requests/pNNN.json` | each PDF page's answer: its printed page number and its Blocks |
| `answers.json` | every current page answer, for the review server to rebuild the entries with Fixes |
| `entries.json` | the verbatim Proverb Entries, plus each page's book page, answer hash and entries |
| `warnings.json` | every Warning, with its kind, reason and PDF page |
| `sources.json` | the 63 Sources, for the review server to write Citations out |
| `pages/pNNN.png` | each page's scan, for the review server |
| `serve.py`, `web/`, `khotangtucngu/` | the review server, its page, and the code that rebuilds the entries with Fixes |
| `review.jsonl` | the review log of Fixes; written only by `serve.py`, never by a run |
| `token_usage.jsonl` | one line per request sent |

Warnings flag:
- number gaps and duplicates within a letter;
- letter headings out of order;
- unknown Source Abbreviations;
- Citations with no pages or that can't be split;
- page numbers out of step with the PDF page;
- failed or missing pages;
- Leading Blocks with no Proverb Entry to join.

**2. Review (any machine, nothing to install).** Copy the store to the laptop, into the same path in your clone of
this repository, then start the server in it:

```bash
rsync -a --exclude review.jsonl <user>@<login node>:<repo>/vsc-project/khoTangTucNguoiNguoiViet/store/part-1/ \
      vsc-project/khoTangTucNguoiNguoiViet/store/part-1/
cd vsc-project/khoTangTucNguoiNguoiViet/store/part-1 && python3 serve.py   # http://127.0.0.1:8000/, --port to change
```

- **The page:** each page's scan is on the left, and its Proverb Entries on the right laid out as printed, with
  italics shown. Each Warning sits on the entry it concerns; the page's own (page number, missing page, Blocks with
  no owner) sit above. Under each entry, its Citations are written out with the Source each matches among the 63, or
  in red if it matches none.
- **Moving around:** ◀ ▶ (or ← →) step through the pages. "Next with Warnings" (`w`) and "Next edited" (`e`) jump
  ahead. "Edits" lists every page with a Fix.
- **Editing:** nobody checks every entry. Where you see the model got something wrong, "✎ Edit" (on hover) opens the
  entry's Blocks as printed text, one row each: change, add, delete or reorder them, and a live preview shows the
  entry and its Warnings. "✎ Edit the page" also edits the printed page number and Blocks outside any entry. Saving
  appends a Fix of the page to `review.jsonl`, and the entries and Warnings are rebuilt with it. An edited entry is
  marked, with its changes against the transcription.
- **Stale Fixes:** if a rerun changes the answer a Fix was made against, the Fix is shown as stale and isn't applied
  until you edit the page again from it or drop it.
- **Keep your review log:** `review.jsonl` is written where you review. When you pull a rerun's store again, keep
  `--exclude review.jsonl` so the copy on the cluster never overwrites your review.
- **Fixing the model's reading:** to redo pages, rerun them on the cluster with `--pages` and pull the store again.

**3. Export (laptop, no GPU).**

```bash
python3 -m src.khotangtucngu.export
```

- **Which Parts:** it exports every Part whose store has an `answers.json`, so a See-also resolves across Parts.
- **Fixes:** the entries are rebuilt with the Fixes that aren't stale in place of the model's Blocks of their pages.
- **Output:** it empties and rewrites each `store/<part>/export/` and writes nothing outside it:
  - `letters/<letter>.json`, one record per Proverb Entry;
  - `sources.json`, the 63 Sources with their Source Notes;
  - `intro.md`, the cleaned Front Matter;
  - `expansions.json`, every General Abbreviation it wrote out, to check by eye;
  - `unresolved_see_also.json`.
- **Into the website:** copy the export folder into `digitizing-vietnam-website` by hand. The card that will read it
  is specced in `.scratch/kho-tang-tuc-ngu-website/spec.md`, which isn't settled yet.

### Audio transcription

`scripts/audio/transcribe.sh` and `sbatch scripts/audio/submit_transcript.sh` turn an interview recording into a
timestamped, speaker-labelled transcript, in a separate venv from `requirements-audio.txt`. See
[`docs/audio-transcribe.md`](docs/audio-transcribe.md).

### DSPy prompt training

`sbatch scripts/dspy/train.sh [model]` optimizes the evaluator prompt with DSPy MIPRO. The optimizer predates the
current Verdict format and must be updated before it is run again (`src/optimization/dspy_evaluator.py`).
