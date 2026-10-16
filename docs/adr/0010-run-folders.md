# Every output lives in one run folder, wiped per pipeline run but never on the web

Outputs used to be scattered over about ten root folders (`logging/`, `logs/`, `output_jsons/`, `evaluation_json/`, `eval_results/`, `extraction_markdown/`, `broken-json/`, `resumes_pdf/`, ...), shared by every run and every resume set, so a Tech run and a CnB run mixed their files and nobody could tell which prompt log belonged to which pass. Now each source of work owns one folder under the gitignored `runs/`: `full-cnb` and `full-tech` for the extract and evaluate jobs (`--tech` picks the second), `full-web-cnb` and `full-web-tech` for the website (`server.sh --tech` picks the second). Each holds the same layout: `logs/`, `prompt_logs/`, `extraction_markdown/`, `extraction_json/`, `evaluation_json/`, `resumes_pdf/`. A pipeline job wipes its folder before it starts, so the folder is always exactly one pass. The web folder is never wiped automatically, because HR's uploads and results build up over many sessions and a server restart must not destroy them. Instead, re-extracting a resume clears everything stored for it, and re-evaluating or deleting an evaluation clears its evaluation and its evaluation prompt logs. The website also reads the matching pipeline folder (CnB or Tech), read-only, so a batch run can still be browsed on the web. If a resume is in both folders, the web copy wins, and the web refuses to delete pipeline results.

## Considered Options

- One `full-web` folder for both resume sets. Rejected: each set is ranked by its own Evaluation Order, so mixing them mis-ranks candidates.
- The website reads only its own folder. Rejected: browsing a SLURM run's results on the website is the main way batch results are inspected.
- Wiping the web folder on server start. Rejected: it would delete HR's work on every restart.

## Consequences

- The HR RAG (`rag/`), the ground truth (`approved_jsons/`), `schemas/`, the datasets and the server's pid/port files stay outside the run folders and are never wiped. The extract and evaluate job used to wipe `approved_jsons/`; it no longer does.
- The pipeline scripts no longer take output or evaluation directory arguments, and refuse to wipe any folder other than the four known run folders.
- SLURM's own `.out`/`.err` files stay in `logging/`, because `#SBATCH --output` is fixed at submit time. The job's tee'd log in the run folder has the same content.
- The bias and consistency checks are unchanged and still use their old paths.
