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

from src.core.config import RUN_DIR, PROMPT_LOGS_DIR, CATEGORY_EVAL_MAX_TOKENS, DEFAULT_NUM_EVALUATIONS, DEFAULT_IMPORTANCE
from src.core.importance import normalize_importance
from src.core.json_utils import clean_and_parse_json
from src.pipelines.evaluator import ResumeEvaluator
from src.pipelines.scoring import score_run
from src.prompts.evaluator_prompts import get_evaluator_system_prompt, category_evaluation_schema
from src.bias.registry import get_bias_builder


# =============================================================================
# BIAS DETECTION ENGINE EXECUTION CONFIGURATION
# =============================================================================
MAX_EVAL_PER_SHUFFLE_KIND: int = 200
# Bias Repetitions per category: one per production evaluation run, so each ordering's runs combine into a Category
# Score as production combines them. The single-run Baselines' differences show how much one run moves with no reordering
NUM_TEST_ITERATIONS: int = DEFAULT_NUM_EVALUATIONS

def get_csv_fieldnames(num_criteria: int) -> List[str]:
    """
    Generates wide-format CSV column names with overall metrics and per-criterion metrics (C1..Cn).
    Each row represents exactly 1 execution run; iteration_number is its Bias Repetition. c<i>_importance is the
    Criterion's Importance, which the summary needs to combine an ordering's runs.
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
            f"c{i}_importance",
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
    Executes exhaustive bias and positional sensitivity evaluation for a single category across its Bias Repetitions.
    Each run is one production Category run (the same slice, schema, scoring and greedy decoding as
    ResumeEvaluator.evaluate_category, without retries); only the order of the prompt content changes. Every ordering
    is run once per Bias Repetition, and its runs are combined as production combines a Category's runs, so each
    ordering is judged by its production Category Score against the Combined Baseline.
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
    # Each Criterion's Importance, written on every row so the summary can combine an ordering's runs from the CSV
    importance_by_id = {
        f"C{i}": normalize_importance(importance_map.get(c_text)) if importance_map else DEFAULT_IMPORTANCE
        for i, c_text in enumerate(criteria_list, start=1)
    }

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
    start_total = time.time()
    file_lock = threading.Lock()

    def evaluate_task(task_args: Tuple[int, str, str, Any, int]) -> Tuple[Dict[str, Any], Dict[str, Dict[str, Any]], str]:
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
            "score": score,
            "is_valid": is_valid,
            "elapsed_seconds": elapsed_sec,
        }

        return row, matched_crit, order_meta

    csv_fieldnames = get_csv_fieldnames(len(criteria_list))

    # Initialize single CSV file with header
    with open(out_csv, "w", newline="", encoding="utf-8") as f_csv_init:
        writer_init = csv.DictWriter(f_csv_init, fieldnames=csv_fieldnames)
        writer_init.writeheader()

    # Loop through the Bias Repetitions (1..num_iterations)
    for iter_num in range(1, num_iterations + 1):
        # 1. Run Baseline first for this Bias Repetition
        base_row, base_matched_crit, base_order = evaluate_task(
            (1, experiments[0][0], experiments[0][1], experiments[0][2], iter_num)
        )
        baseline_score = base_row["score"]
        baseline_crit_eval = base_matched_crit

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
            base_csv_row[f"c{i}_importance"] = importance_by_id[c_id]
            base_csv_row[f"c{i}_score"] = c_info["score"]
            base_csv_row[f"c{i}_verdict"] = c_info["verdict"]
            base_csv_row[f"c{i}_delta"] = 0.0

        all_csv_rows.append(base_csv_row)

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
                row, matched_crit, order_meta = future.result()
                diff = row["score"] - baseline_score

                # Criterion-level differences from this Bias Repetition's single-run Baseline (the raw record)
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

                    task_csv_row[f"c{i}_importance"] = importance_by_id[c_id]
                    task_csv_row[f"c{i}_score"] = c_score
                    task_csv_row[f"c{i}_verdict"] = c_verdict
                    task_csv_row[f"c{i}_delta"] = c_delta

                task_csv_row["num_criteria_affected"] = len(affected_cids)
                task_csv_row["affected_criteria"] = ", ".join(affected_cids) if affected_cids else "None"

                all_csv_rows.append(task_csv_row)
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

    # Overwrite CSV with full cleanly ordered rows
    with open(out_csv, "w", newline="", encoding="utf-8") as f_csv:
        writer = csv.DictWriter(f_csv, fieldnames=csv_fieldnames)
        writer.writeheader()
        writer.writerows(all_csv_rows)

    # Imported here: `python -m src.bias.summary` loads this package first, so a top-level import would double-load it
    from src.bias.summary import HTML_FILENAME, REPORT_FILENAME, write_bias_summary, load_category_runs, combine_orderings, changed_criteria
    summary_csv = write_bias_summary(bias_result_dir)

    # 3. Analysis & Summary: each ordering's runs combined into one Category Score, as production combines them
    orderings = combine_orderings(load_category_runs(out_csv))
    baseline = orderings[0]
    scored = [o for o in orderings if not o["failed"]]
    min_score = min((o["score"] for o in scored), default=0)
    max_score = max((o["score"] for o in scored), default=0)
    total_spread = max_score - min_score

    # Group spreads (preserve order of appearance)
    group_spreads: Dict[str, Dict[str, Any]] = {}
    for exp_type in dict.fromkeys(o["experiment_type"] for o in orderings):
        scs = [o["score"] for o in scored if o["experiment_type"] == exp_type]
        if scs:
            group_spreads[exp_type] = {
                "min": min(scs),
                "max": max(scs),
                "spread": max(scs) - min(scs),
                "count": len(scs)
            }

    # Orderings whose combined score or voted Verdicts differ from the Combined Baseline's
    deviated_variations = []
    if not baseline["failed"]:
        for o in scored[1:]:
            affected_cids = changed_criteria(o, baseline)
            if o["score"] != baseline["score"] or affected_cids:
                deviated_variations.append({
                    "run_index": o["run_index"],
                    "condition": o["condition"],
                    "experiment_type": o["experiment_type"],
                    "score": o["score"],
                    "delta_from_baseline": o["score"] - baseline["score"],
                    "num_criteria_affected": len(affected_cids),
                    "affected_criteria": ", ".join(affected_cids) if affected_cids else "None"
                })

    # Summary dictionary (in-memory for multi-category suite report)
    criteria_map = {f"C{i}": crit for i, crit in enumerate(criteria_list, start=1)}
    invalid_count = sum(1 for r in all_csv_rows if not r["is_valid"])
    failed_orderings = len(orderings) - len(scored)
    summary_data = {
        "target_category": category_key,
        "category_name": category_name,
        "candidate_resume": resume_name,
        "candidate_path": resume_path,
        "criteria_list": criteria_map,
        "baseline_score": baseline["score"],
        "num_test_iterations": num_iterations,
        "total_iterations": total_total_runs,
        "invalid_runs": invalid_count,
        "orderings": len(orderings),
        "failed_orderings": failed_orderings,
        "min_score": min_score,
        "max_score": max_score,
        "total_spread_delta": total_spread,
        "group_spreads": group_spreads,
        "variations": deviated_variations
    }

    total_time = round(time.time() - start_total, 2)
    combined_baseline = "failed" if baseline["failed"] else baseline["score"]

    print("\n" + "=" * 86, file=sys.stderr)
    print(f" 📊 BIAS & POSITIONAL SENSITIVITY SUMMARY: {category_name.upper()} [{category_key}]", file=sys.stderr)
    print("=" * 86, file=sys.stderr)
    print(f" Candidate Profile:                  {resume_name}", file=sys.stderr)
    print(f" Bias Repetitions:                   {num_iterations} (combined per ordering, as production combines its runs)", file=sys.stderr)
    print(f" Total Executions:                   {total_total_runs:,} runs ({len(orderings):,} orderings)", file=sys.stderr)
    print(f" Combined Baseline:                  {combined_baseline}", file=sys.stderr)
    print(f" Combined Score Range:               [{min_score} - {max_score}] (Total Spread: Δ = {total_spread} pts)", file=sys.stderr)
    for g_type, g_info in group_spreads.items():
        print(f" • {g_type:28s} ({g_info['count']:4d}): [{g_info['min']:3d} - {g_info['max']:3d}] (Δ = {g_info['spread']:2d} pts)", file=sys.stderr)
    if invalid_count > 0:
        print(f" ⚠️ NOTICE:                           {invalid_count} of {total_total_runs} runs encountered JSON validation issues, failing {failed_orderings} of {len(orderings)} orderings.", file=sys.stderr)
    print("-" * 86, file=sys.stderr)
    if baseline["failed"] or len(scored) < 2:
        verdict = "⚠️ NO VERDICT (the Combined Baseline or every other ordering failed)"
    elif total_spread > 0 or deviated_variations:
        verdict = "⚠️ POSITIONAL / PLACEMENT BIAS DETECTED"
    else:
        verdict = "✅ POSITION & ORDER INVARIANT (No combined score or voted Verdict variance)"
    print(f" VERDICT: {verdict}", file=sys.stderr)
    print(f" Total Execution Time:               {total_time}s", file=sys.stderr)
    print(f" Prompts Logged to:                  {cat_log_dir}/", file=sys.stderr)
    print(f" Consolidated Output CSV:            {out_csv}", file=sys.stderr)
    print(f" Summary CSV:                        {summary_csv}", file=sys.stderr)
    print(f" Report:                             {os.path.join(bias_result_dir, REPORT_FILENAME)}", file=sys.stderr)
    print(f" Report Page:                        {os.path.join(bias_result_dir, HTML_FILENAME)}", file=sys.stderr)
    print("=" * 86, file=sys.stderr)

    return summary_data
