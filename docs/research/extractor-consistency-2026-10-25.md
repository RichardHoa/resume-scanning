# Extractor consistency and accuracy: CnB and Tech, 2026-10-25

This report covers the runs `runs/consistency-cnb` and `runs/consistency-tech`, made by `sbatch scripts/checks/extractor_consistency.sh` on 2026-10-25. The test design is in `.scratch/extractor-consistency/spec.md`. The fix it led to is in `.scratch/fidelity-checker/spec.md`.

## Bottom line

- **The extractor is stable.**
  - 74 of 88 resumes (84%) gave the same JSON in all 5 runs.
  - Of the 4,248 field paths compared, 45 (1.1%) differed between runs.
  - 7 resumes (8%) differed in content rather than formatting. Only 2 of them had a large difference, each caused by a single outlier run.
  - No run failed, and no output was cut off.
- **The extractor follows the copy-only rule (ADR 0001) nearly always.** We checked all 129 Fidelity Warnings by hand and with scripts:
  - **12 are real rule breaks**, in 6 resumes. That is 0.4% of the roughly 3,200 non-empty values extracted. Examples: a company name read from a logo, a translated language name, "present" filled in with a date, a silently corrected typo.
  - **101 (78%) are false warnings.** The value is in the PDF text, but the checker misses it.
  - **16 are correct values that no text-only check can prove.**
- **The fidelity check needs fixing, not the extractor.** It flags 51% of resumes, so a flagged resume tells HR almost nothing. The fix in `.scratch/fidelity-checker/spec.md` would cut flagged resumes from 45 to 12 and keep all 12 real rule breaks. It would also wrongly accept 0.14% more values than today's check.
- **Not measured: whether a value went into the right field or entry.** Every string can come from the resume and still sit in the wrong job, and neither the consistency test nor the fidelity check can see that. One run did exactly this (Nguyen Hoang Nhat, run 1). Measuring it needs a small set of hand-checked "gold" extractions.

---

## 1. What we tested

There were two questions:

1. **Consistency.** If the same resume is extracted again with the same settings, is the JSON the same?
2. **Accuracy (fidelity).** Is every extracted value copied from the resume, rather than invented, translated or inferred?

Evaluation, scoring and the HR RAG are not part of this test.

## 2. Input

| | CnB | Tech |
|---|---|---|
| Folder | `Vietnamese-dataset/CnB/` | `Vietnamese-dataset/Tech/` |
| Files in the folder | 38 PDFs | 53 PDFs, 6 `.docx` (ignored; the job reads PDFs only) |
| Scanned Resumes skipped (no text layer, ADR 0002) | 3: Doan Thi Anh Tuyet, NGUYEN THANH TRUNG, TRAN THI TUYET TRINH | 0 |
| **Resumes extracted** | **35** | **53** |
| Language of the resumes | Vietnamese, English, bilingual | English, Vietnamese, Japanese (BrSE) |
| Reference Date | today (2026-10-25) | 2015-12-31 |
| Resumes with PDF Notes (broken or unmappable characters, pages without text, pages not shown) | 7 | 11 |

**Model and settings**

| Setting | Value |
|---|---|
| Model | `aisingapore/Qwen-SEA-LION-v4.5-27B-IT` (profile `sea-lion-v4.5-27b`, the default) |
| Served by | vLLM, one GPU (RTX PRO 6000 Blackwell 96 GB), vision on, `CONCURRENCY=40` |
| Extraction mode | **Combined Extraction**: the page images and the PyMuPDF4LLM markdown in one prompt (ADR 0003) |
| Page images | at most 6 pages, 150 DPI JPEG |
| Temperature | 0.0 (production setting) |
| Output cap | 8,192 new tokens |
| Runs per resume | 5 |

Because the temperature is 0, any difference between runs comes from vLLM's run-to-run numerical noise (batching, GPU kernels), not from sampling.

## 3. Method

For each resume:

1. **Scanned Resume check.** `find_textless_pages` checks the PDF before any LLM call. A PDF with no text layer is skipped.
2. **Five extraction runs**, each the same as production:
   - PyMuPDF4LLM turns the PDF into markdown. This is the text the extractor must copy from.
   - Each text page is rendered as an image.
   - The model gets the system prompt (copy only, never translate, page images are for layout only), the images and the markdown, and returns JSON in the schema.
   - **Fidelity check** (`check_extracted_fields_in_markdown`): every extracted string is looked up in the markdown. A string that isn't found becomes a **Fidelity Warning**.
   - **PDF Notes**: broken characters, pages without text and pages not shown are noted. These describe the file, not the model.
3. **Comparison**, field by field:
   - Every leaf value is taken at its path, e.g. `work_experience[2].responsibilities`.
   - Strings are trimmed and inner whitespace is collapsed. Nothing else is normalised, so a trailing period counts as a difference.
   - A path present in some runs and missing in others is a difference.
   - No run is the baseline: each distinct value is listed with the runs that produced it.
4. **Failed runs.** Invalid JSON after all retries, a Repaired Extraction, or a request error count as failed runs. There were none.

Then, for this report:

5. **Every Fidelity Warning was checked against its markdown.** Scripts sorted the warnings by why the checker missed them. Every warning the scripts couldn't explain was looked up by hand in the markdown, and for "Vietravel Airlines" and "NGUYỄN ĐỨC NHÂM" in the rendered PDF page as well.
6. **Every field difference was sorted.** It is *cosmetic* if the values are equal once punctuation, whitespace and bullet characters are removed. Otherwise it is *content*.

## 4. Output

Each run folder (`runs/consistency-cnb`, `runs/consistency-tech`) holds:

| Path | What it is |
|---|---|
| `extraction_json/<resume>/run-1.json … run-5.json` | the 5 extractions of each resume |
| `extraction_markdown/<resume>.md` | the PyMuPDF4LLM markdown the extractor copied from |
| `prompt_logs/run-<n>/<resume>/` | the full prompt and raw answer of each run |
| `consistency_report.md` / `.json` | the per-set report: summary, most unstable fields, then each resume's differences, Fidelity Warnings and PDF Notes |
| `logs/consistency.log`, `vllm.log`, `token_usage.jsonl` | job log, server log, tokens per call |

## 5. Results: consistency

### Resume level

| | CnB | Tech | Both |
|---|---|---|---|
| Resumes extracted | 35 | 53 | 88 |
| Identical in all 5 runs | 31 (88.6%) | 43 (81.1%) | **74 (84.1%)** |
| Some field differed | 4 (11.4%) | 10 (18.9%) | 14 (15.9%) |
| … only cosmetic differences | 3 | 4 | 7 (8.0%) |
| … a content difference | 1 | 6 | **7 (8.0%)** |
| Failed runs (invalid JSON, cut-off, request error) | 0 / 175 | 0 / 265 | **0 / 440** |

### Field level

| | CnB | Tech | Both |
|---|---|---|---|
| Field paths compared (union over the 5 runs) | 1,715 | 2,533 | 4,248 |
| Paths that differed | 4 (0.23%) | 41 (1.62%) | **45 (1.06%)** |
| … cosmetic | 3 | 9 | 12 |
| … content | 1 | 32 | 33 |

26 of Tech's 32 content-different paths come from 2 resumes. In each, one run out of five behaved differently.

The field that differs most often is `work_experience[*].responsibilities`: it differed in 9 of the 14 resumes with differences. These are long, multi-bullet fields, and the model sometimes changes a bullet character, a sub-bullet level or a trailing period.

### Every content difference

| Resume | What changed | Runs | Effect |
|---|---|---|---|
| Nguyen Hoang Nhat_BrSE | Run 1 put project names into `work_experience[*].position`, added a "Project Name:" line into responsibilities, and set every `education_background[*].degree` to "Student". The other runs left position empty and wrote degree "Bachelor". | 1 of 5 | **Wrong field and an inferred degree.** The one real extraction error the consistency test found. |
| Dinh Nguyen Minh Duc_NodeJS | Run 2 also copied the 4 projects into `projects`. In all 5 runs they are already in `work_experience`. | 1 of 5 | Duplicated, nothing lost. |
| Nguyen Huu Phat_NodeJS | Run 2 kept the lead sentence "I worked some project about retail store, relate to some techologies:" in front of the bullets. | 1 of 5 | Runs 1, 3, 4, 5 drop one sentence of the resume. |
| Phung Thi Kim Chi | Runs 4–5 kept the section headings ("1. Công tác nhân sự, tiền lương và phúc lợi:" …). Runs 1–3 flattened them away. | 2 of 5 | Headings lost in 3 runs; the duties themselves are the same. |
| Nguyen Chi Nhan_BrSE | `issuing_organization` "Lớp tiếng Nhật Fulltime FPT" or just "FPT". A ">> PG:" label kept or dropped. | 2 of 5 | Shortened value. |
| Cao Ba Loc_NodeJS | Personal website `http://www.loccb.0fees.us` kept or dropped. | 2 of 5 | Value missing in 2 runs. |
| LY Trung Huy_Javascript | `graduation_year` "Tháng 9/2007 - Tháng 9/2011" or "Tháng 9/2011". | 1 of 5 | Shortened value. |

The cosmetic differences, in 7 resumes, are:

- a trailing `.` added or dropped;
- `- SQL server` or `SQL server`;
- `+` or `-` for sub-bullets;
- a nested list flattened.

The facts are the same in every case.

## 6. Results: accuracy (Fidelity Warnings)

### Counts as reported

| | CnB | Tech | Both |
|---|---|---|---|
| Resumes with at least one Fidelity Warning | 24 / 35 (68.6%) | 21 / 53 (39.6%) | **45 / 88 (51.1%)** |
| Distinct Fidelity Warnings | 55 | 74 | 129 |
| Non-empty values extracted (run 1) | 1,327 | 1,867 | 3,194 |
| Warnings per non-empty value | 4.1% | 4.0% | 4.0% |
| Warnings present in all 5 runs | 55 / 55 | 72 / 74 | 127 / 129 |

Almost every warning repeats in all 5 runs. The model does the same thing each time, so these warnings say something about the checker or the PDF, not about run-to-run noise.

### Why each warning fired

Every one of the 129 warnings, sorted by cause:

| Cause | Count | Share | Real error? | Example |
|---|---|---|---|---|
| Checker bug: stray `<` taken for an HTML tag, `_` kept in words, full-width characters not folded | 30 | 23% | No | Nguyen Tram: `< 50 employees … >90%` read as one tag, 1,480 characters of markdown deleted. `２０１０年１１月` vs `2010年11月`. |
| Text layer splits a word or URL | 23 | 18% | No | `www.linkedin.com/in/nguye nducnham180992`, `Hongtuyet1993@gmail.co m` |
| Model joins bullets or parts that are apart in the markdown | 23 | 18% | No | multi-bullet responsibilities with the KPI block merged in, as the prompt asks; `04/2025 … Now` → "04/2025 - Now" |
| Text interleaved with another column | 19 | 15% | No | `CÔNG HR Lead Quy mô: 70-80 người TY CP ỨNG DỤNG … PKH` → "CÔNG TY CP ỨNG DỤNG PKH" |
| Language named from its certificate (allowed by ADR 0001) | 6 | 5% | No | TOEIC 870 → "English", JLPT → "Japanese" |
| **Correct, but no text-only check can prove it** | 16 | 12% | No | Japanese 履歴書 table: year cell + month cell + `年`/`月` headers → `2013年7月`; dates split across far-apart lines |
| **Real rule break** | **12** | **9%** | **Yes** | see below |

**The 12 real rule breaks** (6 resumes, all repeated in 5 of 5 runs):

| Resume | Field | What the model did | Rule broken |
|---|---|---|---|
| CnB - Hoang Tan Tai | `work_experience[0].company_name` "Vietravel Airlines" | read it from a logo that has no text layer | images are for layout only (ADR 0003) |
| CnB - Tran Ngoc Thien Trang | `skills[0–2]`, `work_experience[1].responsibilities` (4 values) | the text layer is garbled (`Tr�ng Đąi hc`, `n học văn phòng`), so the model read clean text from the image | images are for layout only. The result is right, but nothing can check it. |
| CnB - Pham Truong Hoai Tram | `certifications[0].issuing_organization` | corrected the resume's typo "ĐÀO TÀO" to "ĐÀO TẠO" | copy verbatim |
| Nguyen Anh Tho_BrSE | `languages[1].language` "English" | translated "英語" from the self-PR | never translate |
| Nguyen Anh Tho_BrSE | `work_experience[2].duration` "2013/8 - 2015/12" | the resume says 現在 (present); the model wrote the Reference Date month | never infer |
| Tong That Tung_.Net | `work_experience[3–5].responsibilities` (3 values) | invented a "Projects:" / "Project:" label in front of table content | never write |
| Nguyen Trong Lam_NodeJS | `languages[0].proficiency` | dropped "in English" from "Skillful in English (writing, reading, listening)" | copy verbatim |

Real rule-break rate: **12 of 3,194 non-empty values (0.38%)**, in **6 of 88 resumes (6.8%)**. Most are small. The one that could mislead an HR reader is the invented end date for Nguyen Anh Tho.

### With the proposed fidelity check

Simulated on the same stored markdown and JSONs, with no re-extraction (see `.scratch/fidelity-checker/spec.md` for the rules):

| | CnB | Tech | Both |
|---|---|---|---|
| Warnings now → after | 55 → 10 | 74 → 18 | **129 → 28** |
| Resumes flagged now → after | 24 → 6 | 21 → 6 | **45 (51%) → 12 (14%)** |
| Real rule breaks still flagged | 6 / 6 | 6 / 6 | **12 / 12** |
| Foreign values wrongly accepted, beyond today's check | 5 / 3,852 | 8 / 5,218 | **13 / 9,070 (0.14%)** |

"Foreign values" means: each resume's markdown was checked against every value extracted from 3 other resumes in the same set. This measures how often the looser match would accept text the resume doesn't contain. The 13 extra values it accepts are short generic strings ("Frontend Developer", "Kỹ năng làm việc nhóm", "2011 – 2014").

## 7. Cost

| | CnB | Tech |
|---|---|---|
| Extractions | 175 | 265 |
| Wall time | 2,771 s (46 min) | 3,208 s (53 min) |
| Wall time per extraction (40 in parallel) | 15.8 s | 12.1 s |
| Prompt tokens, median | 6,928 | 6,657 |
| Completion tokens, median / max | 1,504 / 3,391 | 954 / 2,873 |
| Answers that hit the 8,192-token cap | 0 | 0 |

## 8. Is the extraction pipeline accurate?

**For copying, yes:**

- 99.6% of extracted values are found in the resume text, or are correct values that only the image can confirm.
- Rule breaks are rare (0.4% of values) and the same in every run, so they can be fixed in the prompt.
- Runs agree on 99% of fields.

**For placement, we don't know yet.** Both checks here only ask whether a string came from the resume, not whether it went into the right field or entry. The one placement error we saw (project names as job titles, in 1 of 5 runs) was found only because the runs disagreed. A placement error that happens in all 5 runs would pass every check in this report.

## 9. Recommendations

1. **Fix the fidelity check** (`.scratch/fidelity-checker/spec.md`). This is the largest gain for the least work: flagged resumes drop from 51% to 14%, and the warnings that remain are worth reading.
2. **Tighten the prompt for the rule breaks seen:**
   - never replace "present"/現在/Hiện tại with a date;
   - never translate a language name except from a certificate;
   - never add a label the resume doesn't have;
   - don't fix typos.
   Then rerun this test and check that the 12 warnings are gone.
3. **Measure placement.** Hand-check about 10–15 resumes per set into gold JSONs, covering two-column layouts, tables and Japanese 履歴書, and compare each run to them field by field. This is the only way to test what Combined Extraction is meant to fix.
4. **Optional:** normalise bullet characters and trailing periods after extraction. That would make 7 of the 14 differing resumes identical, but it is cosmetic.
5. **Check the RapidOCR question.** The job log shows PyMuPDF4LLM running RapidOCR on some pages. If OCR text gets into the markdown, the fidelity check can no longer tell text-layer values from pixel-read ones.

## 10. Reproduce

```bash
sbatch scripts/checks/extractor_consistency.sh            # default model, Combined Extraction
sbatch scripts/checks/extractor_consistency.sh <model> --text   # text-only extraction
```

The job wipes and rewrites `runs/consistency-cnb` and `runs/consistency-tech`. The sorting of warnings and differences in sections 5–6 was done with one-off scripts, which are not in the repo. The counts can be re-derived from `consistency_report.json` and `extraction_markdown/`.
