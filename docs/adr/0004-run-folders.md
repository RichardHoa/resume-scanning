# Every output lives in one run folder, wiped per pipeline job but never on the web

Each source of work owns one folder under the gitignored `runs/`. Its name says who writes it and which resume set it holds, and every folder has the same layout: `logs/`, `prompt_logs/`, `extraction_markdown/`, `extraction_json/`, `evaluation_json/`, `resumes_pdf/`. Outputs used to be scattered over about ten shared root folders, so a Tech run and a CnB run mixed their files, and nobody could tell which prompt log belonged to which pass.

| Run folder | Written by | Wiped |
| --- | --- | --- |
| `batch-cnb`, `batch-tech` | the pipeline jobs (`--cnb` or `--tech`, one is required) | when each job starts (`evaluate.sh` wipes only the evaluations) |
| `web-cnb`, `web-tech` | the website started with `--cnb` or `--tech` | never automatically |
| `web` | the website started with neither: no dataset, no Evaluation Order, no pipeline folder | never automatically |
| `extractor-consistency-*`, `evaluator-consistency-*` | the consistency checks, per resume set | when that check starts |
| `bias-cnb` | the Bias Check | when it starts |

Wiping a pipeline folder at the start of each job means it always holds exactly one pass. The web folders are never wiped, because HR's uploads and results build up over many sessions, and a server restart must not destroy them. Instead, the web clears only what it redoes: re-extracting a resume clears everything stored for it, and re-evaluating or deleting an evaluation clears that evaluation and its prompt logs.

A website with a resume set also reads the matching batch folder, read-only, so HR can browse a batch run on the web. If a resume is in both folders, the web copy wins, and the web refuses to delete batch results.

## Considered Options

- **One shared website folder for both resume sets.** Rejected: each set is ranked by its own Evaluation Order, so mixing them would mis-rank candidates.
- **The website reads only its own folder.** Rejected: browsing a SLURM run's results on the website is the main way people inspect batch results.
- **Wiping the web folder on server start.** Rejected: it would delete HR's work on every restart.

## Consequences

- No run wipes the HR RAG (`rag/`), the ground truth (`approved_jsons/`), `schemas/`, the datasets or the server's pid and port files, because they sit outside `runs/`.
- `RUN_DIR` must name one of the folders above. The pipeline scripts take no output-directory arguments and refuse to wipe anything else.
- SLURM's own `.out` and `.err` files stay in `logging/`, because `#SBATCH --output` is fixed at submit time. The job's tee'd log in the run folder has the same content.
- The website never reads the consistency or bias folders.
