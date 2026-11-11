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
  cli/            command-line entry points (extract, evaluate, backfill_feedback, proofread, audio, ...)
  pipelines/      extractor, evaluator, scoring, review_panel, ground_truth, proofreader
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
  proofread/, audio/, dspy/   side tools (see below)
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

`src/khotangtucngu` transcribes the Proverb Entries of one PDF Part of the book with the default vision model, using
two Apple Vision reads of every line made on a Mac. It then lets you review them page by page against the scan and
exports website data.
Its terms (PDF Part, Proverb Entry, Citation, Warning, Confirmed Span, ...) are in
[`vsc-project/khoTangTucNguoiNguoiViet/GLOSSARY.md`](vsc-project/khoTangTucNguoiNguoiViet/GLOSSARY.md). The Parts,
their proverb pages and book page offsets are in `src/khotangtucngu/settings.py`: `--part-1` (PDF pages 36–865, PDF page
671 skipped as the book misprints it) and `--part-2` (PDF pages 5–818) are set up now. The commands below use
`--part-1`; for Part 2, use `--part-2` and `store/part-2/`.

Everything for one Part lives in its store, `vsc-project/khoTangTucNguoiNguoiViet/store/<part>/`. `vsc-project/` is
not in git apart from `front-matter.md`, so first copy the Part's PDF there on both the Mac and the cluster
(`kho tàng tục ngữ người việt tập 1 - p1.pdf`, `Kho tàng tục ngữ người việt tập 1 - p2.pdf`).

**1. Read the pages with Apple Vision (Mac, from the repository root, in your own terminal).** Vision runs only on
macOS, so this step is not part of the job. Install its dependencies first:
`pip install -r requirements-macos.txt`. Compiling its reader needs Apple's Command Line Tools.

```bash
python3 -m src.khotangtucngu.vision_ocr --part-1 --pages 36-45,420-424   # a first batch
python3 -m src.khotangtucngu.vision_ocr --part-1                         # every proverb page, about 18 minutes
```

- Runs over different pages add up, and a rerun skips pages with a current read. A page Vision fails on is saved as
  failed and read again next time. A new macOS version reads every page again.
- A changed line finder doesn't count as out of date: delete `store/<part>/lines/` to read the pages again with it.
- It ends by printing pages read, pages failed, the share of Disputed Syllables, and the line that copies its output to
  the cluster. It transfers nothing itself. That line copies only these two folders, never `review.jsonl`:

```bash
rsync -a vsc-project/khoTangTucNguoiNguoiViet/store/part-1/lines vsc-project/khoTangTucNguoiNguoiViet/store/part-1/vision \
      <user>@<login node>:<repo>/vsc-project/khoTangTucNguoiNguoiViet/store/part-1/
```

| File | What it holds |
| --- | --- |
| `lines/pNNN.json` | each page's printed lines found on the scan, and ink outside them |
| `vision/pNNN.json` | each page's Vision record: the PDF's hash, the stamp of how it was read, its status, each Line Number's box and two reads, and the observations matching no line |

**2. Transcribe (cluster, from the repository root).** Copy the reads across first, then use the same `--pages`.

```bash
bash scripts/khotangtucngu/submit.sh --part-1 --dry-run            # login node: token counts, sends nothing
sbatch scripts/khotangtucngu/submit.sh --part-1 --pages 36-45,420-424   # a first batch, with an entry over a page break
sbatch scripts/khotangtucngu/submit.sh --part-1                    # every proverb page of the Part
sbatch scripts/khotangtucngu/submit.sh --part-1 --pages 420        # redo the pages you name (ranges and single pages)
```

- Before any request, including with `--dry-run`, the job exits naming any page of this run whose lines or Vision read
  are missing, failed or made from another PDF, before its server starts. A job with `--pages` needs reads for those
  pages only.
- Each answer is saved as soon as it arrives. A rerun only redoes requests that failed, never ran, or were made
  under a different prompt, image setting, read or PDF. If the full run hits the job's 4-hour limit, submit the same
  command again and it carries on.
- The job runs 60 requests at a time, its own setting in `scripts/khotangtucngu/submit.sh`. Make the first job at 60 a
  small batch of pages, to show whether the KV cache still fits its GPU memory share of 0.85.
- **Confirmed Spans:** the job reads `review.jsonl` if the store has one, and never writes it. A Confirmed Span gets no
  request, however the layout is read later. A partly confirmed page gets its layout request (reused as usual) and
  requests for its other spans, and lines left below a Confirmed Span are read as a continuation of the entry above. A
  fully confirmed page gets no request at all until one of its spans is undone. If a Confirmed Span was made from
  another PDF, the job stops before any request, naming the pages.
- Runs over different pages add up in the store. The outputs are rebuilt from every saved answer each time.
- `--dry-run` writes its per-request counts to `store/<part>/dry_run_tokens.jsonl`.
- Logs: `logging/slurm_khotangtucngu_<job>.out`, plus `logs/vllm_khotangtucngu.log` for the server.

A run writes into the store:

| File | What it holds |
| --- | --- |
| `layout/pNNN.json`, `layout/pNNN.png` | each PDF page's layout answer, and the page with its Line Numbers as that request saw it |
| `spans/pNNN-LMM.json` | each Entry Span's answer, named by its page and the Line Number it starts on |
| `answers.json` | every current page answer with the model's Blocks and its spans (Block range, band, crop, Line Numbers, whether Leading, reads), for the review server to lay Confirmed Spans over |
| `readings.json` | each page's OCR Readings joined, which its Blocks are checked against for Diacritic Disagreements |
| `agreed.json` | the same readings with their Agreed Syllables flagged, which its Blocks are checked against for Model Edits |
| `entries.json` | the verbatim Proverb Entries with the Confirmed Spans laid over, plus each page's book page, entries and spans |
| `warnings.json` | every Warning, with its kind, reason and PDF page |
| `sources.json` | the 63 Sources, for the review server to write Citations out |
| `pages/pNNN.png` | each page's scan, for the review server |
| `serve.py`, `web/`, `khotangtucngu/` | the review server, its page, and the code that rebuilds the entries with Confirmed Spans |
| `review.jsonl` | the review log: each Confirmed Span in full, undos, printed page numbers. Append-only, written only by `serve.py`, never by a run |
| `token_usage.jsonl` | one line per request sent |

Warnings flag:
- number gaps and duplicates within a letter;
- letter headings out of order;
- unknown Source Abbreviations;
- Citations with no pages or that can't be split;
- Diacritic Disagreements;
- Model Edits: where the model's Blocks differ from an Agreed Syllable or add a word no read has. The model's text is
  kept and the Warning names both spellings;
- page numbers out of step with the PDF page;
- failed or missing pages;
- Leading Blocks with no Proverb Entry to join;
- ink outside every printed line found;
- a model span only partly overlapping a Confirmed Span, after a run without the latest log.

A Confirmed Span's Blocks raise no Warning, but its numbers still feed other spans' checks: an unconfirmed A 16 still
warns that it follows A 14, and a second A 4 keeps its duplicate Warning. Confirming A 14 does hide "A 14 follows A 12"
for good, even if A 13 really is missing, until you undo it. Missing page and Ink outside the lines Warnings always stay.

**3. Review (any machine, nothing to install).** Copy the store to the laptop, into the same path in your clone of
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
  ahead, and lead only to what is unsettled or changed. The header counts the spans confirmed, with no total: nobody
  confirms every entry. "Confirmed" lists the spans you edited, and every Confirmed Span with its toggle.
- **Confirming and editing:** on an entry's card, "✓ Confirm" and "✎ Edit" (on hover) act on the Entry Span holding that
  entry's Blocks on this page. Either way it becomes a Confirmed Span straight away, with no run: its Warnings go, and
  its rectangle on the scan changes colour. Two entries in one span share its confirmation, and an entry running onto
  the next page is confirmed separately on each page. A letter heading, or Leading Blocks with no owner, has a card of
  its own.
- **The editor:** it opens the whole span as printed text, one row per Block: change, add, delete or reorder them. A live
  preview shows the entries and the Warnings the Blocks would raise, which never stop you saving. You can edit a
  Confirmed Span again, and the latest save wins. An edited span is tagged, with its changes against the model's Blocks.
- **Undo:** puts the model's Blocks and their Warnings back straight away. The next run reads the span again if its saved
  answer is no longer current.
- **The printed page number:** the line above the entries edits, confirms and undoes it. Doing either settles its Page
  number Warning for good.
- **Overlaps:** a run without your latest log can cut a span that only partly overlaps a Confirmed Span. It stays, with
  a Warning and no buttons, until a run with the log cuts the page again.
- **Your review log is the master copy:** `review.jsonl` is written where you review, on the laptop. Before a run, push
  it to the same path on the cluster yourself. A run without your latest log loses nothing, and only wastes requests
  on spans you have since confirmed. Keep `--exclude review.jsonl` when you pull a rerun's store, so the cluster's
  older copy never overwrites yours:

```bash
rsync -a vsc-project/khoTangTucNguoiNguoiViet/store/part-1/review.jsonl \
      <user>@<login node>:<repo>/vsc-project/khoTangTucNguoiNguoiViet/store/part-1/
```

- **Redoing the model's reading:** to redo pages, rerun them on the cluster with `--pages` and pull the store again.
  Confirmed Spans keep their Blocks and their place whatever the new answers say.

**4. Export (laptop, no GPU).**

```bash
python3 -m src.khotangtucngu.export
```

- **Which Parts:** it exports every Part whose store has an `answers.json`, so a See-also resolves across Parts.
- **Confirmed Spans:** the entries are rebuilt with them laid over the model's Blocks. An entry's `fixed` is true only
  if a span holding it was edited, not if it was confirmed as it stood.
- **Output:** it empties and rewrites each `store/<part>/export/` and writes nothing outside it:
  - `letters/<letter>.json`, one record per Proverb Entry;
  - `sources.json`, the 63 Sources with their Source Notes;
  - `intro.md`, the cleaned Front Matter;
  - `expansions.json`, every General Abbreviation it wrote out, to check by eye;
  - `unresolved_see_also.json`;
  - `export-warning.txt`, to check by eye: every repeated Entry Image name (`A-200_2.png` on) with both entries, and
    each letter's count from 1 to its highest number, each missing number listed with the entries either side of it
    (name, PDF and book page, proverb);
  - `entry_images.zip`, the Entry Image of every Proverb Entry (`A-200.png`, grayscale at 200 dpi), cut from the
    Part's PDF, which must be in `vsc-project/khoTangTucNguoiNguoiViet/`. Each record's `image` names its file. An
    image holds the whole of every Entry Span its entry is in, so it may show a letter heading or a neighbouring entry.
- **Into the website:** copy the export folder into `digitizing-vietnam-website` by hand. The card that will read it
  is specced in `.scratch/kho-tang-tuc-ngu-website/spec.md`, which isn't settled yet.

### Audio transcription

`scripts/audio/transcribe.sh` and `sbatch scripts/audio/submit_transcript.sh` turn an interview recording into a
timestamped, speaker-labelled transcript, in a separate venv from `requirements-audio.txt`. See
[`docs/audio-transcribe.md`](docs/audio-transcribe.md).

### DSPy prompt training

`sbatch scripts/dspy/train.sh [model]` optimizes the evaluator prompt with DSPy MIPRO. The optimizer predates the
current Verdict format and must be updated before it is run again (`src/optimization/dspy_evaluator.py`).
