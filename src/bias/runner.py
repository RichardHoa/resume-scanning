"""
Bias & Positional Sensitivity Detection Execution Engine.
Orchestrates multi-threaded evaluation, full prompt logging, and transparent data provenance reporting.
"""
import os
import sys
import json
import csv
import time
import threading
import concurrent.futures
from typing import Dict, List, Any, Tuple, Optional

from src.core.config import RUN_DIR, PROMPT_LOGS_DIR, CATEGORY_EVAL_MAX_TOKENS
from src.core.json_utils import clean_and_parse_json
from src.pipelines.evaluator import ResumeEvaluator
from src.pipelines.scoring import score_run
from src.prompts.evaluator_prompts import get_evaluator_system_prompt, category_evaluation_schema
from src.bias.registry import get_bias_builder


# =============================================================================
# BIAS DETECTION ENGINE EXECUTION CONFIGURATION
# =============================================================================
MAX_EVAL_PER_SHUFFLE_KIND: int = 200
# Bias Repetitions per category: at temperature 0 their differences show how much a score moves with no reordering
NUM_TEST_ITERATIONS: int = 5

def get_csv_fieldnames(num_criteria: int) -> List[str]:
    """
    Generates wide-format CSV column names with overall metrics and per-criterion metrics (C1..Cn).
    Each row represents exactly 1 execution run; iteration_number is its Bias Repetition.
    """
    fields = [
        "iteration_number",
        "run_index",
        "experiment_type",
        "condition",
        "order",
        "overall_score",
        "baseline_score",
        "delta_from_baseline",
        "num_criteria_affected",
        "affected_criteria",
        "is_valid",
        "elapsed_seconds",
    ]
    for i in range(1, num_criteria + 1):
        fields.extend([
            f"c{i}_score",
            f"c{i}_verdict",
            f"c{i}_delta",
        ])
    return fields


def criteria_by_id(raw_criteria: List[Dict[str, Any]], criteria_list: List[str]) -> Dict[str, Dict[str, Any]]:
    """
    Maps each Criterion's id ('C1'..'Cn', in criteria_list order) to its Verdict from a scored run, found by the exact
    Criterion text the schema forces. A Criterion with no Verdict (an invalid run) gets NO_EVIDENCE and 0.
    """
    by_text = {str(c.get("criterion", "")).strip(): c for c in raw_criteria if isinstance(c, dict)}
    matched: Dict[str, Dict[str, Any]] = {}
    for i, c_text in enumerate(criteria_list, start=1):
        crit = by_text.get(c_text.strip())
        matched[f"C{i}"] = {
            "score": float(crit.get("score", 0.0)),
            "verdict": str(crit.get("verdict", "NO_EVIDENCE")),
            "evidence_quote": crit.get("evidence_quote")
        } if crit else {"score": 0.0, "verdict": "NO_EVIDENCE", "evidence_quote": None}
    return matched


def log_data_provenance_report(
    resume_path: str,
    resume_data: Dict[str, Any],
    rag_dir: str,
    rag_status: str,
    categories_to_run: List[str]
) -> None:
    """Logs unambiguous provenance information about where JSON and RAG criteria originate."""
    file_size_bytes = os.path.getsize(resume_path) if os.path.exists(resume_path) else 0
    resume_name = os.path.splitext(os.path.basename(resume_path))[0]
    keys_present = list(resume_data.keys())

    print("=" * 86, file=sys.stderr)
    print(" 🔍 ATS EVALUATOR BIAS DETECTION: DATA PROVENANCE & ENVIRONMENT REPORT", file=sys.stderr)
    print("=" * 86, file=sys.stderr)
    print(f" 📂 CANDIDATE RESUME SOURCE (JSON):", file=sys.stderr)
    print(f"    • File Path:       {resume_path}", file=sys.stderr)
    print(f"    • Candidate ID:    {resume_name}", file=sys.stderr)
    print(f"    • File Size:       {file_size_bytes:,} bytes", file=sys.stderr)
    print(f"    • Top-Level Keys:  {keys_present}", file=sys.stderr)
    print(f" 🧠 RAG CRITERIA VECTOR STORE:", file=sys.stderr)
    print(f"    • Vector DB Dir:   {rag_dir}", file=sys.stderr)
    print(f"    • Storage Status:  {rag_status}", file=sys.stderr)
    print(f" 🎯 CATEGORIES TO TEST:", file=sys.stderr)
    for cat in categories_to_run:
        b = get_bias_builder(cat)
        print(f"    • [{cat}] -> '{b.category_label}'", file=sys.stderr)
    print("=" * 86, file=sys.stderr)


def run_single_category_bias_test(
    category_key: str,
    evaluator: ResumeEvaluator,
    resume_data: Dict[str, Any],
    resume_path: str,
    concurrency: int,
    seed: int = 42,
    atomic_sample_size: int = 300,
    max_eval_per_shuffle_kind: Optional[int] = MAX_EVAL_PER_SHUFFLE_KIND,
    num_iterations: int = NUM_TEST_ITERATIONS,
    dry_run: bool = False
) -> Dict[str, Any]:
    """
    Executes exhaustive bias and positional sensitivity evaluation for a single category across 5 Bias Repetitions.
    Each run is one production Category run (the same slice, schema, scoring and greedy decoding as
    ResumeEvaluator.evaluate_category, without retries); only the order of the prompt content changes.
    Generates a single consolidated CSV file in the run folder: bias_detection_{category_key}.csv.
    A Not Applicable Category (no Criteria in the HR RAG) is skipped; a vector store out of step with the stored HR
    RAG raises, as it fails the Category in production.
    """
    builder = get_bias_builder(category_key)
    category_name = builder.category_label
    resume_name = os.path.splitext(os.path.basename(resume_path))[0]

    # 1. Extract Candidate Data Slice: the raw resume keys production judges this Category on
    candidate_data = builder.extract_candidate_data(resume_data)

    # 2. Retrieve Criteria from RAG, as production does
    query_ctx = json.dumps(candidate_data, ensure_ascii=False)
    criteria_list = evaluator.rag.retrieve(category_key, query_ctx, top_k=None)

    # Mock replies judge no Criteria, so mocks score without an Importance map, as in production. Checked before Not
    # Applicable, as in production, so an empty vector store with a stored HR RAG fails instead of being skipped
    importance_map = {} if evaluator.mock else evaluator.rag.get_importance_map(category_key)
    if importance_map and set(criteria_list) != set(importance_map):
        raise RuntimeError(
            f"The vector store's Criteria for '{category_key}' differ from the stored HR RAG. Save the HR RAG again on the RAG page."
        )

    if not criteria_list:
        print(f"[Not Applicable] The HR RAG has no Criteria for '{category_key}': skipped.", file=sys.stderr)
        return {"category_key": category_key, "category_name": category_name, "not_applicable": True}
    json_schema = category_evaluation_schema(criteria_list)

    # 3. Build Atomic Chunks & Experiments
    effective_sample_size = min(atomic_sample_size, max_eval_per_shuffle_kind) if max_eval_per_shuffle_kind else atomic_sample_size
    atomic_chunks = builder.build_atomic_chunks(criteria_list, candidate_data)
    experiments = builder.build_experiments(
        criteria_list=criteria_list,
        candidate_data=candidate_data,
        seed=seed,
        atomic_sample_size=effective_sample_size,
        max_per_kind=max_eval_per_shuffle_kind if max_eval_per_shuffle_kind and max_eval_per_shuffle_kind > 0 else None
    )

    # Cap maximum evaluations for any shuffle kind / permutation group to max_eval_per_shuffle_kind
    if max_eval_per_shuffle_kind is not None and max_eval_per_shuffle_kind > 0:
        capped_experiments = []
        kind_counts: Dict[str, int] = {}
        for exp in experiments:
            exp_type = exp[0]
            if exp_type == "Baseline":
                capped_experiments.append(exp)
            else:
                count = kind_counts.get(exp_type, 0)
                if count < max_eval_per_shuffle_kind:
                    capped_experiments.append(exp)
                    kind_counts[exp_type] = count + 1
        experiments = capped_experiments

    total_runs_per_iter = len(experiments)
    total_total_runs = total_runs_per_iter * num_iterations

    # Output paths
    bias_result_dir = RUN_DIR
    cat_log_dir = os.path.join(PROMPT_LOGS_DIR, category_key)
    os.makedirs(cat_log_dir, exist_ok=True)
    out_csv = os.path.join(bias_result_dir, f"bias_detection_{category_key}.csv")

    # Group counts
    group_counts: Dict[str, int] = {}
    for exp_type, _, _ in experiments:
        group_counts[exp_type] = group_counts.get(exp_type, 0) + 1

    print(f"\n" + "-" * 86, file=sys.stderr)
    print(f" 🔬 RUNNING CATEGORY: [{category_key}] - '{category_name}'", file=sys.stderr)
    print(f"    • Criteria Items ({len(criteria_list)}): {criteria_list}", file=sys.stderr)
    print(f"    • Candidate Slice Keys: {list(candidate_data.keys())}", file=sys.stderr)
    print(f"    • Runs per Bias Repetition: {total_runs_per_iter:,} | Bias Repetitions: {num_iterations} (Total: {total_total_runs:,} runs)", file=sys.stderr)
    for g_name, g_count in group_counts.items():
        print(f"       - {g_name:28s}: {g_count:5d} runs x {num_iterations} = {g_count * num_iterations:5d}", file=sys.stderr)
    print(f"    • Concurrency: {concurrency} workers", file=sys.stderr)
    print(f"    • Logs Folder: {cat_log_dir}/", file=sys.stderr)
    print(f"    • Output CSV:  {out_csv}", file=sys.stderr)
    print("-" * 86, file=sys.stderr)

    if dry_run:
        print(f"[DRY-RUN] Validating prompt rendering for {total_runs_per_iter} combinations across {num_iterations} Bias Repetitions...", file=sys.stderr)
        for i, (exp_type, cond_label, perm_meta) in enumerate(experiments[:10], start=1):
            p_text, o_meta = builder.render_prompt(
                exp_type=exp_type,
                perm_meta=perm_meta,
                criteria_list=criteria_list,
                candidate_data=candidate_data,
                atomic_chunks=atomic_chunks,
                model_name=evaluator.model_name
            )
            assert len(p_text) > 0, f"Empty prompt generated for {cond_label}"
        print(f"[DRY-RUN] ✅ All sample prompts rendered successfully without error.", file=sys.stderr)
        return {
            "category_key": category_key,
            "category_name": category_name,
            "total_runs": total_total_runs,
            "runs_per_iteration": total_runs_per_iter,
            "num_iterations": num_iterations,
            "group_counts": group_counts,
            "dry_run": True
        }

    system_prompt = get_evaluator_system_prompt(language=evaluator.language)
    all_csv_rows: List[Dict[str, Any]] = []
    all_results_matrix: List[Dict[str, Any]] = []
    details_list: List[Dict[str, Any]] = []
    start_total = time.time()
    file_lock = threading.Lock()

    def evaluate_task(task_args: Tuple[int, str, str, Any, int]) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Dict[str, Any]], str]:
        idx, exp_type, cond_label, perm_meta, iter_num = task_args
        t_iter = time.time()

        user_prompt, order_meta = builder.render_prompt(
            exp_type=exp_type,
            perm_meta=perm_meta,
            criteria_list=criteria_list,
            candidate_data=candidate_data,
            atomic_chunks=atomic_chunks,
            model_name=evaluator.model_name
        )

        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_prompt}
        ]

        # One greedy call, no retries: a retry samples, which would mix sampling noise into the ordering effect
        try:
            raw_response = evaluator._call_vllm_backend(
                messages, temperature=0.0, json_schema=json_schema, max_tokens=CATEGORY_EVAL_MAX_TOKENS, step=f"bias_{category_key}"
            ).text

            parsed = clean_and_parse_json(raw_response)
            validated = score_run(parsed, importance_map=importance_map)
            is_valid = bool(validated is not None)
            score = validated.get("score", 0) if is_valid else 0
            raw_criteria = validated.get("criteria_evaluations", []) if is_valid else []
        except Exception as exc:
            raw_response = f"EXECUTION_ERROR: {str(exc)}"
            is_valid = False
            score = 0
            raw_criteria = []

        elapsed_sec = round(time.time() - t_iter, 2)
        matched_crit = criteria_by_id(raw_criteria, criteria_list)

        # Log prompt
        prefix = f"iter{iter_num:02d}_" if num_iterations > 1 else ""
        prompt_log_file = os.path.join(cat_log_dir, f"{prefix}{idx:04d}_{cond_label}.txt")
        with open(prompt_log_file, "w", encoding="utf-8") as f_log:
            f_log.write(f"============================== [SYSTEM PROMPT] ==============================\n")
            f_log.write(f"{system_prompt}\n\n")
            f_log.write(f"=============================== [USER PROMPT] ===============================\n")
            f_log.write(f"{user_prompt}\n\n")
            f_log.write(f"============================== [RAW MODEL OUTPUT] ===========================\n")
            f_log.write(f"{raw_response}\n\n")
            f_log.write(f"================================= [METRICS] =================================\n")
            f_log.write(f"Bias Repetition: {iter_num}/{num_iterations} | Run: {idx}/{total_runs_per_iter} | Experiment: {exp_type} | Permutation: {perm_meta}\n")
            f_log.write(f"Order: {order_meta}\n")
            f_log.write(f"Parsed Score: {score}/100 | Is Valid: {is_valid} | Response Time: {elapsed_sec}s\n")
            f_log.write(f"Criteria Breakdown: {json.dumps(matched_crit, ensure_ascii=False)}\n")

        row = {
            "iteration_number": iter_num,
            "index": idx,
            "condition": cond_label,
            "experiment_type": exp_type,
            "order": order_meta,
            "score": score,
            "delta_from_baseline": 0,
            "num_criteria_affected": 0,
            "affected_criteria": "None",
            "is_valid": is_valid,
            "elapsed_seconds": elapsed_sec,
            "log_file": prompt_log_file
        }

        detail = {
            "iteration_number": iter_num,
            "index": idx,
            "condition": cond_label,
            "experiment_type": exp_type,
            "order": order_meta,
            "score": score,
            "delta_from_baseline": 0,
            "num_criteria_affected": 0,
            "affected_criteria": "None",
            "is_valid": is_valid,
            "elapsed_seconds": elapsed_sec,
            "log_file": prompt_log_file,
            "criteria_evaluations": matched_crit
        }

        return row, detail, matched_crit, order_meta

    csv_fieldnames = get_csv_fieldnames(len(criteria_list))

    # Initialize single CSV file with header
    with open(out_csv, "w", newline="", encoding="utf-8") as f_csv_init:
        writer_init = csv.DictWriter(f_csv_init, fieldnames=csv_fieldnames)
        writer_init.writeheader()

    # Loop through the Bias Repetitions (1..num_iterations)
    for iter_num in range(1, num_iterations + 1):
        # 1. Run Baseline first for this Bias Repetition
        base_row, base_detail, base_matched_crit, base_order = evaluate_task(
            (1, experiments[0][0], experiments[0][1], experiments[0][2], iter_num)
        )
        baseline_score = base_row["score"]
        baseline_crit_eval = base_matched_crit

        base_row["delta_from_baseline"] = 0
        base_row["num_criteria_affected"] = 0
        base_row["affected_criteria"] = "None"

        base_detail["delta_from_baseline"] = 0
        base_detail["num_criteria_affected"] = 0
        base_detail["affected_criteria"] = "None"

        base_csv_row = {
            "iteration_number": iter_num,
            "run_index": 1,
            "experiment_type": base_row["experiment_type"],
            "condition": base_row["condition"],
            "order": base_order,
            "overall_score": base_row["score"],
            "baseline_score": baseline_score,
            "delta_from_baseline": 0,
            "num_criteria_affected": 0,
            "affected_criteria": "None",
            "is_valid": 1 if base_row["is_valid"] else 0,
            "elapsed_seconds": base_row["elapsed_seconds"],
        }
        for i in range(1, len(criteria_list) + 1):
            c_id = f"C{i}"
            c_info = base_matched_crit.get(c_id, {"score": 0.0, "verdict": "NO_EVIDENCE"})
            base_csv_row[f"c{i}_score"] = c_info["score"]
            base_csv_row[f"c{i}_verdict"] = c_info["verdict"]
            base_csv_row[f"c{i}_delta"] = 0.0

        all_results_matrix.append(base_row)
        all_csv_rows.append(base_csv_row)
        details_list.append(base_detail)

        # Flush baseline row immediately
        with file_lock:
            with open(out_csv, "a", newline="", encoding="utf-8") as f_csv:
                writer = csv.DictWriter(f_csv, fieldnames=csv_fieldnames)
                writer.writerow(base_csv_row)
                f_csv.flush()

        # 2. Run remaining experiments concurrently with incremental CSV flushing
        remaining_tasks = [(i, exp[0], exp[1], exp[2], iter_num) for i, exp in enumerate(experiments[1:], start=2)]
        effective_concurrency = min(concurrency, total_runs_per_iter)
        unflushed_rows: List[Dict[str, Any]] = []

        with concurrent.futures.ThreadPoolExecutor(max_workers=effective_concurrency) as executor:
            future_to_task = {executor.submit(evaluate_task, t): t for t in remaining_tasks}
            for future in concurrent.futures.as_completed(future_to_task):
                row, detail, matched_crit, order_meta = future.result()
                diff = row["score"] - baseline_score
                row["delta_from_baseline"] = diff
                detail["delta_from_baseline"] = diff

                # Compute criterion-level metrics
                affected_cids = []
                task_csv_row = {
                    "iteration_number": iter_num,
                    "run_index": row["index"],
                    "experiment_type": row["experiment_type"],
                    "condition": row["condition"],
                    "order": order_meta,
                    "overall_score": row["score"],
                    "baseline_score": baseline_score,
                    "delta_from_baseline": diff,
                    "is_valid": 1 if row["is_valid"] else 0,
                    "elapsed_seconds": row["elapsed_seconds"],
                }

                for i, _ in enumerate(criteria_list, start=1):
                    c_id = f"C{i}"
                    c_score = matched_crit.get(c_id, {}).get("score", 0.0)
                    c_verdict = matched_crit.get(c_id, {}).get("verdict", "NO_EVIDENCE")
                    b_score = baseline_crit_eval.get(c_id, {}).get("score", 0.0)
                    c_delta = round(c_score - b_score, 2)
                    if abs(c_delta) > 1e-4:
                        affected_cids.append(c_id)

                    task_csv_row[f"c{i}_score"] = c_score
                    task_csv_row[f"c{i}_verdict"] = c_verdict
                    task_csv_row[f"c{i}_delta"] = c_delta

                row["num_criteria_affected"] = len(affected_cids)
                row["affected_criteria"] = ", ".join(affected_cids) if affected_cids else "None"
                detail["num_criteria_affected"] = len(affected_cids)
                detail["affected_criteria"] = ", ".join(affected_cids) if affected_cids else "None"
                task_csv_row["num_criteria_affected"] = len(affected_cids)
                task_csv_row["affected_criteria"] = row["affected_criteria"]

                all_results_matrix.append(row)
                all_csv_rows.append(task_csv_row)
                details_list.append(detail)
                unflushed_rows.append(task_csv_row)

                # Flush to CSV every 10 completed runs
                if len(unflushed_rows) >= 10:
                    with file_lock:
                        with open(out_csv, "a", newline="", encoding="utf-8") as f_csv:
                            writer = csv.DictWriter(f_csv, fieldnames=csv_fieldnames)
                            writer.writerows(unflushed_rows)
                            f_csv.flush()
                    unflushed_rows.clear()

        # Flush any remaining rows for this Bias Repetition
        if unflushed_rows:
            with file_lock:
                with open(out_csv, "a", newline="", encoding="utf-8") as f_csv:
                    writer = csv.DictWriter(f_csv, fieldnames=csv_fieldnames)
                    writer.writerows(unflushed_rows)
                    f_csv.flush()
            unflushed_rows.clear()

    # Sort all CSV rows deterministically by (iteration_number, run_index)
    all_csv_rows.sort(key=lambda x: (x["iteration_number"], x["run_index"]))
    all_results_matrix.sort(key=lambda x: (x["iteration_number"], x["index"]))
    details_list.sort(key=lambda x: (x["iteration_number"], x["index"]))

    # Overwrite CSV with full cleanly ordered rows
    with open(out_csv, "w", newline="", encoding="utf-8") as f_csv:
        writer = csv.DictWriter(f_csv, fieldnames=csv_fieldnames)
        writer.writeheader()
        writer.writerows(all_csv_rows)

    # Imported here: `python -m src.bias.summary` loads this package first, so a top-level import would double-load it
    from src.bias.summary import HTML_FILENAME, REPORT_FILENAME, write_bias_summary
    summary_csv = write_bias_summary(bias_result_dir)

    # 3. Analysis & Summary across all Bias Repetitions
    valid_scores = [r["score"] for r in all_results_matrix if r.get("is_valid", True)]
    eval_pool = valid_scores if valid_scores else [r["score"] for r in all_results_matrix]
    min_score = min(eval_pool) if eval_pool else 0
    max_score = max(eval_pool) if eval_pool else 0
    total_spread = max_score - min_score

    # Group spreads (preserve order of appearance)
    group_spreads: Dict[str, Dict[str, Any]] = {}
    ordered_exp_types = list(dict.fromkeys(r["experiment_type"] for r in all_results_matrix))
    for exp_type in ordered_exp_types:
        scs = [r["score"] for r in all_results_matrix if r["experiment_type"] == exp_type and r.get("is_valid", True)]
        if scs:
            group_spreads[exp_type] = {
                "min": min(scs),
                "max": max(scs),
                "spread": max(scs) - min(scs),
                "count": len(scs)
            }

    # Summary dictionary (in-memory for multi-category suite report)
    deviated_variations = [d for d in details_list if d.get("delta_from_baseline", 0) != 0 or d.get("num_criteria_affected", 0) != 0]
    criteria_map = {f"C{i}": crit for i, crit in enumerate(criteria_list, start=1)}
    summary_data = {
        "target_category": category_key,
        "category_name": category_name,
        "candidate_resume": resume_name,
        "candidate_path": resume_path,
        "criteria_list": criteria_map,
        "baseline_score": all_results_matrix[0]["score"] if all_results_matrix else 0,
        "num_test_iterations": num_iterations,
        "total_iterations": total_total_runs,
        "valid_iterations": len(valid_scores),
        "deviated_iterations": len(deviated_variations),
        "min_score": min_score,
        "max_score": max_score,
        "total_spread_delta": total_spread,
        "group_spreads": group_spreads,
        "variations": deviated_variations
    }

    total_time = round(time.time() - start_total, 2)
    invalid_count = total_total_runs - len(valid_scores)

    print("\n" + "=" * 86, file=sys.stderr)
    print(f" 📊 BIAS & POSITIONAL SENSITIVITY SUMMARY: {category_name.upper()} [{category_key}]", file=sys.stderr)
    print("=" * 86, file=sys.stderr)
    print(f" Candidate Profile:                  {resume_name}", file=sys.stderr)
    print(f" Bias Repetitions:                   {num_iterations}", file=sys.stderr)
    print(f" Total Executions:                   {total_total_runs:,} runs", file=sys.stderr)
    print(f" Overall Score Range:                [{min_score} - {max_score}] (Total Spread: Δ = {total_spread} pts)", file=sys.stderr)
    for g_type, g_info in group_spreads.items():
        print(f" • {g_type:28s} ({g_info['count']:4d}): [{g_info['min']:3d} - {g_info['max']:3d}] (Δ = {g_info['spread']:2d} pts)", file=sys.stderr)
    if invalid_count > 0:
        print(f" ⚠️ NOTICE:                           {invalid_count} of {total_total_runs} runs encountered JSON validation issues.", file=sys.stderr)
    print("-" * 86, file=sys.stderr)
    verdict = "⚠️ POSITIONAL / PLACEMENT BIAS DETECTED" if total_spread > 0 else "✅ POSITION & ORDER INVARIANT (No score variance)"
    print(f" VERDICT: {verdict}", file=sys.stderr)
    print(f" Total Execution Time:               {total_time}s", file=sys.stderr)
    print(f" Prompts Logged to:                  {cat_log_dir}/", file=sys.stderr)
    print(f" Consolidated Output CSV:            {out_csv}", file=sys.stderr)
    print(f" Summary CSV:                        {summary_csv}", file=sys.stderr)
    print(f" Report:                             {os.path.join(bias_result_dir, REPORT_FILENAME)}", file=sys.stderr)
    print(f" Report Page:                        {os.path.join(bias_result_dir, HTML_FILENAME)}", file=sys.stderr)
    print("=" * 86, file=sys.stderr)

    return summary_data
