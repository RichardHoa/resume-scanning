#!/usr/bin/env python3
"""
Evaluator Consistency Check — extracts every resume of one resume set once, evaluates that extraction 5 times
(5 Repeat Evaluations, each a full production evaluation) and reports what changes between them: the Match
Recommendation, the Must-have Rejection, the Overall and Category Scores, and each Verdict HR sees, with the
reasoning behind each Verdict a Criterion flipped between (.scratch/evaluator-consistency/spec.md).

Run with RUN_DIR set to the resume set's evaluator consistency run folder (scripts/checks/evaluator_consistency.sh).
Writes extraction_json/<resume>.json, evaluation_json/<resume>/eval-<n>.json and
evaluator_consistency_report.md / .json to the run folder.
"""
import os
import sys
import json
import argparse
import time
from collections import Counter
from concurrent.futures import ThreadPoolExecutor, as_completed

# Ensure repository root is in sys.path for 'src' package imports and set CWD
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)
os.chdir(_PROJECT_ROOT)

from src.core.config import (
    DEFAULT_LLM_MODEL, DEFAULT_VLLM_URL, RUN_DIR, EXTRACTION_JSON_DIR, EVALUATION_JSON_DIR, PROMPT_LOGS_DIR,
    DEFAULT_NUM_EVALUATIONS, VLLM_MAX_CONCURRENT_REQUESTS, CATEGORY_LABELS
)
from src.core.reference_date import set_reference_date, get_reference_date
from src.pipelines.extractor import ResumeExtractor
from src.pipelines.evaluator import ResumeEvaluator
from src.cli.evaluate import load_hr_rag_requirements
from extractor_consistency import is_scanned_pdf, extraction_error

REPEAT_EVALUATIONS = 5
MISSING = "(missing)"
NO_REJECTION = "none"


def parse_args():
    parser = argparse.ArgumentParser(description="Evaluator Consistency Check: every resume evaluated 5 times")
    parser.add_argument("--dir", type=str, required=True, help="Directory of the resume set's PDF resumes")
    parser.add_argument("--set-name", type=str, required=True, help="Resume set name shown in the report (CnB, Tech)")
    parser.add_argument("--model-name", type=str, default=DEFAULT_LLM_MODEL, help="Model name served by the vLLM server")
    parser.add_argument("--vllm-url", type=str, default=DEFAULT_VLLM_URL, help="vLLM server URL")
    parser.add_argument("--extract-workers", type=int, default=6, help="Extractions running at once")
    parser.add_argument("--workers", type=int, default=VLLM_MAX_CONCURRENT_REQUESTS,
                        help="Repeat Evaluations running at once (default: the vLLM request limit, which does the throttling)")
    parser.add_argument("--reference-date", type=str, default="",
                        help="Date (YYYY-MM-DD) the prompts treat as today, for old resume sets (default: the real date)")
    return parser.parse_args()


def extract_once(extractor: ResumeExtractor, name: str, pdf_path: str) -> dict:
    """
    The resume's one extraction, saved as extraction_json/<resume>.json. Returns {"data"} or {"error"}; "raised"
    marks a request that failed (server down, timeout, rejected), which says nothing about the model's answers.
    """
    try:
        text = extractor.extract(pdf_path, log_dir=os.path.join(PROMPT_LOGS_DIR, "extraction"))
    except Exception as e:
        return {"error": f"extraction raised: {e}", "raised": True}
    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        with open(os.path.join(EXTRACTION_JSON_DIR, f"{name}.txt"), "w", encoding="utf-8") as f:
            f.write(text or "")
        return {"error": "invalid JSON after all retries"}

    with open(os.path.join(EXTRACTION_JSON_DIR, f"{name}.json"), "w", encoding="utf-8") as f:
        f.write(text)
    error = extraction_error(data)
    return {"error": error} if error else {"data": data}


def run_evaluation(evaluator: ResumeEvaluator, name: str, resume_data: dict, n: int, standard_req: str,
                   hidden_req: str) -> dict:
    """
    Repeat Evaluation n of one resume, saved as evaluation_json/<resume>/eval-<n>.json, its prompt logs under
    prompt_logs/eval-<n>/ so the 5 never overwrite each other's. Returns {"evaluation", "report"} or
    {"evaluation", "error", "raised"}.
    """
    try:
        report = evaluator.evaluate_resume(
            resume_data, standard_req, hidden_req,
            resume_name=name,
            output_path=os.path.join(EVALUATION_JSON_DIR, name, f"eval-{n}.json"),
            num_evaluations=DEFAULT_NUM_EVALUATIONS,
            log_dir=os.path.join(PROMPT_LOGS_DIR, f"eval-{n}"),
            generate_feedback=False
        )
    except Exception as e:
        return {"evaluation": n, "error": f"evaluation raised: {e}", "raised": True}
    return {"evaluation": n, "report": report}


def crashed_categories(report: dict) -> dict:
    """{Category name: exception text} for each Category whose evaluation raised instead of running out of retries."""
    return {
        dim.get("category_name", key): dim["error"]
        for key, dim in (report.get("dimension_scores") or {}).items() if dim.get("error")
    }


def evaluations_by_value(values_per_evaluation: dict) -> list[dict]:
    """{evaluation: value} grouped into distinct values with their evaluations, the most common value first."""
    groups = {}
    for n, value in sorted(values_per_evaluation.items()):
        groups.setdefault(value, []).append(n)
    ordered = sorted(groups.items(), key=lambda item: (-len(item[1]), item[1][0]))
    return [{"value": value, "evaluations": evals} for value, evals in ordered]


def rejected_must_haves(report: dict) -> str:
    """The Must-haves a Must-have Rejection names, as one comparable string."""
    names = sorted(
        f"{CATEGORY_LABELS.get(m.get('category'), m.get('category'))}: {m.get('criterion', '')}"
        for m in report.get("must_have_rejection") or []
    )
    return "; ".join(names) or NO_REJECTION


def compare_resume(name: str, results: list[dict]) -> dict:
    """The comparison of one resume's Repeat Evaluations; a Failed Evaluation is listed and left out of it."""
    reports, failed = {}, []
    for r in results:
        if "error" in r:
            failed.append({"evaluation": r["evaluation"], "error": r["error"]})
            continue
        report = r["report"]
        if report.get("status") == "ok":
            reports[r["evaluation"]] = report
            continue
        dims = report.get("dimension_scores") or {}
        crashed = crashed_categories(report)
        failed.append({
            "evaluation": r["evaluation"],
            "failed_categories": [dims.get(k, {}).get("category_name", k) for k in report.get("failed_categories") or []],
            "error": "; ".join(f"{cat}: {err}" for cat, err in crashed.items()) or "ran out of retries",
        })

    recommendation = {n: rep.get("match_recommendation") for n, rep in reports.items()}
    rejection = {n: rejected_must_haves(rep) for n, rep in reports.items()}
    overall = {n: rep.get("overall_score") for n, rep in reports.items()}

    category_scores, verdicts = {}, {}
    for n, rep in reports.items():
        for key, dim in (rep.get("dimension_scores") or {}).items():
            if dim.get("not_applicable"):
                continue
            cat_name = dim.get("category_name", key)
            category_scores.setdefault(cat_name, {})[n] = dim.get("score")
            # The Verdicts voted across the Category's runs: the ones HR is shown
            for crit in dim.get("criteria_evaluations") or []:
                verdicts.setdefault((cat_name, crit.get("criterion", "")), {})[n] = crit

    category_differences = []
    for cat_name, per_eval in category_scores.items():
        per_eval = {n: per_eval.get(n, MISSING) for n in reports}
        if len(set(per_eval.values())) > 1:
            category_differences.append({"category": cat_name, "values": evaluations_by_value(per_eval)})

    # Each Criterion's Criterion Score (the mean Verdict score of its Category's runs) per evaluation that judged it:
    # what the Category Score is computed from, so it can settle even where the shown Verdict still flips
    criterion_scores = {key: {n: c["score"] for n, c in per_eval.items() if isinstance(c.get("score"), (int, float))}
                        for key, per_eval in verdicts.items()}
    criterion_score_spreads = [{"category": cat, "criterion": crit, "scores": scores,
                                "spread": round(max(scores.values()) - min(scores.values()), 2)}
                               for (cat, crit), scores in criterion_scores.items() if len(scores) > 1]

    verdict_differences = []
    for (cat_name, criterion), per_eval in verdicts.items():
        values = {n: (per_eval[n].get("verdict") if n in per_eval else MISSING) for n in reports}
        if len(set(values.values())) < 2:
            continue
        grouped = evaluations_by_value(values)
        for g in grouped:
            # One reasoning per distinct Verdict, from its first evaluation, to read side by side
            first = per_eval.get(g["evaluations"][0]) or {}
            g["reasoning"] = first.get("reasoning", "")
        importance = next(iter(per_eval.values())).get("importance", "")
        verdict_differences.append({"category": cat_name, "criterion": criterion, "importance": importance,
                                    "values": grouped, "criterion_scores": criterion_scores[(cat_name, criterion)]})

    scores = [s for s in overall.values() if isinstance(s, (int, float))]
    return {
        "resume": name,
        "ok_evaluations": sorted(reports),
        "failed_evaluations": sorted(failed, key=lambda f: f["evaluation"]),
        "match_recommendation": evaluations_by_value(recommendation),
        "must_have_rejection": evaluations_by_value(rejection),
        "overall_score": {
            "min": min(scores), "max": max(scores), "spread": round(max(scores) - min(scores), 1),
            "values": evaluations_by_value(overall),
        } if scores else None,
        "category_score_differences": category_differences,
        "verdict_differences": verdict_differences,
        "criterion_score_spreads": criterion_score_spreads,
        # Every Criterion judged, so the change rate counts the stable ones too; one scored evaluation compares nothing
        "criteria_compared": [{"category": cat, "criterion": crit} for cat, crit in verdicts] if len(reports) > 1 else [],
    }


def _spread(c: dict) -> float:
    return c["overall_score"]["spread"] if c["overall_score"] else 0.0


def _recommendation_changed(c: dict) -> bool:
    return len(c["match_recommendation"]) > 1


def _rejection_changed(c: dict) -> bool:
    return len(c["must_have_rejection"]) > 1


def _is_stable(c: dict) -> bool:
    return not (c["failed_evaluations"] or _recommendation_changed(c) or _rejection_changed(c)
                or c["category_score_differences"] or c["verdict_differences"])


def build_report(set_name: str, mode: str, reference_date: str, standard_req: str, hidden_req: str,
                 resumes: list[dict], scanned: list[str], extraction_failures: list[dict]) -> dict:
    # Least stable first: a changed recommendation, a changed rejection or a Failed Evaluation, the widest spread,
    # the most flipped Verdicts
    resumes = sorted(resumes, key=lambda c: (
        not _recommendation_changed(c),
        not (_rejection_changed(c) or c["failed_evaluations"]),
        -_spread(c), -len(c["verdict_differences"]), c["resume"],
    ))
    unstable, judged = Counter(), Counter()
    for c in resumes:
        unstable.update({(d["category"], d["criterion"]) for d in c["verdict_differences"]})
        judged.update({(j["category"], j["criterion"]) for j in c["criteria_compared"]})
    # The share of (resume, Criterion) pairs whose Verdict differed: unlike "any Verdict changed", it does not grow
    # just because the HR RAG is split into more Criteria
    flipped, compared = sum(unstable.values()), sum(judged.values())
    # A resume with one scored evaluation has no spread to measure
    scored = [c for c in resumes if len(c["ok_evaluations"]) > 1]
    widest = max(scored, key=_spread, default=None)
    criterion_spreads = [(c["resume"], s) for c in resumes for s in c["criterion_score_spreads"]]
    widest_criterion = max(criterion_spreads, key=lambda rs: rs[1]["spread"], default=None)
    return {
        "resume_set": set_name,
        "mode": mode,
        "reference_date": reference_date or "today",
        "repeat_evaluations": REPEAT_EVALUATIONS,
        "category_runs_per_evaluation": DEFAULT_NUM_EVALUATIONS,
        "standard_requirements": standard_req,
        "hidden_requirements": hidden_req,
        "counts": {
            "resumes": len(resumes),
            "stable": sum(1 for c in resumes if _is_stable(c)),
            "recommendation_changed": sum(1 for c in resumes if _recommendation_changed(c)),
            "verdict_changed": sum(1 for c in resumes if c["verdict_differences"]),
            "with_failed_evaluation": sum(1 for c in resumes if c["failed_evaluations"]),
            "scanned_skipped": len(scanned),
            "extraction_failed": len(extraction_failures),
        },
        "overall_score_spread": {
            "mean": round(sum(_spread(c) for c in scored) / len(scored), 1) if scored else None,
            "largest": _spread(widest) if widest else None,
            "largest_resume": widest["resume"] if widest else None,
        },
        "criterion_score_spread": {
            "mean": round(sum(s["spread"] for _, s in criterion_spreads) / len(criterion_spreads), 3)
            if criterion_spreads else None,
            "largest": widest_criterion[1]["spread"] if widest_criterion else None,
            "largest_resume": widest_criterion[0] if widest_criterion else None,
            "largest_criterion": widest_criterion[1]["criterion"] if widest_criterion else None,
        },
        "verdict_change_rate": {
            "changed": flipped, "compared": compared,
            "percent": round(flipped / compared * 100, 1) if compared else None,
        },
        "unstable_criteria": [{"category": cat, "criterion": crit, "resumes": n, "judged": judged[(cat, crit)],
                               "percent": round(n / judged[(cat, crit)] * 100, 1) if judged[(cat, crit)] else None}
                              for (cat, crit), n in unstable.most_common()],
        "scanned_resumes": scanned,
        "extraction_failures": extraction_failures,
        "resumes": resumes,
    }


def _evals(evals: list[int]) -> str:
    return ("eval " if len(evals) == 1 else "evals ") + ", ".join(str(n) for n in evals)


def _values_line(values: list[dict]) -> str:
    """One value, or each distinct value with its evaluations."""
    if len(values) == 1:
        return f"{values[0]['value']} (all)"
    return "; ".join(f"{v['value']} — {_evals(v['evaluations'])}" for v in values)


def render_markdown(report: dict) -> str:
    counts = report["counts"]
    spread = report["overall_score_spread"]
    lines = [
        f"# Evaluator consistency: {report['resume_set']}",
        "",
        f"{report['mode']}, {report['repeat_evaluations']} Repeat Evaluations per resume, each with "
        f"{report['category_runs_per_evaluation']} Category runs, Reference Date {report['reference_date']}.",
        "",
        "HR RAG judged against:",
        "",
        "```text",
        f"Standard Requirements:\n{report['standard_requirements'] or '(none)'}",
        "",
        f"Hidden Requirements:\n{report['hidden_requirements'] or '(none)'}",
        "```",
        "",
        "## Summary",
        "",
        f"- Resumes compared: {counts['resumes']}",
        f"- Stable across all evaluations: {counts['stable']}",
        f"- Match Recommendation changed: {counts['recommendation_changed']}",
        f"- Any Verdict changed: {counts['verdict_changed']}",
        f"- Verdict change rate: {report['verdict_change_rate']['changed']} of "
        f"{report['verdict_change_rate']['compared']} Criterion Verdicts compared"
        + (f" ({report['verdict_change_rate']['percent']}%)" if report["verdict_change_rate"]["percent"] is not None
           else ""),
        f"- With a Failed Evaluation: {counts['with_failed_evaluation']}",
        f"- Scanned Resumes skipped: {counts['scanned_skipped']}"
        + (f" ({', '.join(report['scanned_resumes'])})" if report["scanned_resumes"] else ""),
        f"- Failed extractions skipped: {counts['extraction_failed']}"
        + (f" ({'; '.join(f['resume'] + ': ' + f['error'] for f in report['extraction_failures'])})"
           if report["extraction_failures"] else ""),
    ]
    if spread["mean"] is not None:
        lines.append(f"- Overall Score spread (max − min): mean {spread['mean']}, largest {spread['largest']} "
                     f"({spread['largest_resume']})")
    crit_spread = report["criterion_score_spread"]
    if crit_spread["mean"] is not None:
        lines.append(f"- Criterion Score spread (max − min, 0–1): mean {crit_spread['mean']} over every Criterion "
                     f"compared, largest {crit_spread['largest']} ({crit_spread['largest_resume']}: "
                     f"{crit_spread['largest_criterion']})")
    lines.append("")
    if report["unstable_criteria"]:
        lines += ["### Most unstable Criteria", "",
                  "| Category | Criterion | Resumes where its Verdict differs | Resumes compared | Change rate |",
                  "|---|---|---|---|---|"]
        lines += [f"| {u['category']} | {u['criterion']} | {u['resumes']} | {u['judged']} | {u['percent']}% |"
                  for u in report["unstable_criteria"]]
        lines.append("")

    lines += ["## Resumes", ""]
    for c in report["resumes"]:
        flags = []
        if _recommendation_changed(c):
            flags.append("Match Recommendation changed")
        if _rejection_changed(c):
            flags.append("Must-have Rejection changed")
        if _spread(c):
            flags.append(f"Overall Score spread {_spread(c)}")
        if c["verdict_differences"]:
            flags.append(f"{len(c['verdict_differences'])} changed Verdict(s)")
        if c["failed_evaluations"]:
            flags.append(f"{len(c['failed_evaluations'])} Failed Evaluation(s)")
        lines += [f"### {c['resume']} — {', '.join(flags) or 'stable'}", ""]

        if c["ok_evaluations"]:
            overall = c["overall_score"]
            lines += [
                "**Outcome**",
                "",
                f"- Match Recommendation: {_values_line(c['match_recommendation'])}",
                f"- Must-have Rejection: {_values_line(c['must_have_rejection'])}",
                f"- Overall Score: {overall['min']}–{overall['max']}: {_values_line(overall['values'])}"
                if overall and overall["spread"] else
                f"- Overall Score: {_values_line(overall['values']) if overall else MISSING}",
                "",
            ]
        if c["category_score_differences"]:
            lines += ["**Category Scores**", ""]
            lines += [f"- {d['category']}: {_values_line(d['values'])}" for d in c["category_score_differences"]]
            lines.append("")
        if c["verdict_differences"]:
            lines += ["**Verdict differences**", ""]
            for d in c["verdict_differences"]:
                lines.append(f"- {d['category']} — {d['criterion']} ({d['importance']})")
                if d["criterion_scores"]:
                    lines.append("  - Criterion Score: " + ", ".join(
                        f"{score} (eval {n})" for n, score in sorted(d["criterion_scores"].items())))
                for v in d["values"]:
                    reasoning = " ".join(str(v["reasoning"]).split()) or "(no reasoning)"
                    lines.append(f"  - **{v['value']}** — {_evals(v['evaluations'])}: {reasoning}")
            lines.append("")
        if c["failed_evaluations"]:
            lines += ["**Failed Evaluations**", ""]
            for f in c["failed_evaluations"]:
                cats = f" in {', '.join(f['failed_categories'])}" if f.get("failed_categories") else ""
                lines.append(f"- Eval {f['evaluation']} failed{cats}: {f['error']}")
            lines.append("")
    return "\n".join(lines)


def main():
    args = parse_args()
    set_reference_date(args.reference_date)

    if not os.path.isdir(args.dir):
        print(f"[Error] Directory not found: {args.dir}", file=sys.stderr)
        sys.exit(1)
    pdf_files = sorted(f for f in os.listdir(args.dir) if f.lower().endswith(".pdf"))
    if not pdf_files:
        print(f"[Error] No PDF resumes found in {args.dir}", file=sys.stderr)
        sys.exit(1)

    evaluator = ResumeEvaluator(model_name=args.model_name, vllm_url=args.vllm_url)
    standard_req, hidden_req = load_hr_rag_requirements(evaluator)

    scanned, to_extract = [], []
    for fname in pdf_files:
        name = os.path.splitext(fname)[0]
        if is_scanned_pdf(os.path.join(args.dir, fname)):
            print(f"Skipping {fname}: Scanned Resume", file=sys.stderr)
            scanned.append(name)
        else:
            to_extract.append((name, os.path.join(args.dir, fname)))

    start = time.time()
    extractor = ResumeExtractor(model_name=args.model_name, vllm_url=args.vllm_url)
    extractor.load_model()
    print(f"[{args.set_name}] Extracting {len(to_extract)} resumes once each.", file=sys.stderr)
    with ThreadPoolExecutor(max_workers=max(1, args.extract_workers)) as executor:
        extractions = dict(zip(
            (name for name, _ in to_extract),
            executor.map(lambda item: extract_once(extractor, *item), to_extract)
        ))
    extraction_failures = [{"resume": name, "error": r["error"]} for name, r in extractions.items() if "error" in r]
    for f in extraction_failures:
        print(f"Skipping {f['resume']}: {f['error']}", file=sys.stderr)
    to_evaluate = {name: r["data"] for name, r in extractions.items() if "data" in r}

    evaluator.load_model()
    tasks = [(name, n) for name in to_evaluate for n in range(1, REPEAT_EVALUATIONS + 1)]
    total = len(tasks)
    print(f"[{args.set_name}] {len(to_evaluate)} resumes x {REPEAT_EVALUATIONS} Repeat Evaluations = {total} "
          f"evaluations.", file=sys.stderr)

    results = {name: [] for name in to_evaluate}
    done = 0

    with ThreadPoolExecutor(max_workers=max(1, args.workers)) as executor:
        futures = {
            executor.submit(run_evaluation, evaluator, name, to_evaluate[name], n, standard_req, hidden_req): name
            for name, n in tasks
        }
        for future in as_completed(futures):
            name, result = futures[future], future.result()
            results[name].append(result)
            done += 1
            if "error" in result:
                status = f"FAILED ({result['error']})"
            else:
                rep = result["report"]
                status = f"{rep.get('status')}, {rep.get('overall_score')} {rep.get('match_recommendation')}"
            print(f"[{done}/{total}] {name} eval {result['evaluation']}: {status}", file=sys.stderr)

    mode = "Combined Extraction"
    compared = [compare_resume(name, sorted(evals, key=lambda r: r["evaluation"])) for name, evals in results.items()]
    report = build_report(args.set_name, mode, get_reference_date().isoformat(), standard_req, hidden_req, compared, scanned,
                          extraction_failures)

    json_path = os.path.join(RUN_DIR, "evaluator_consistency_report.json")
    md_path = os.path.join(RUN_DIR, "evaluator_consistency_report.md")
    with open(json_path, "w", encoding="utf-8") as f:
        json.dump(report, f, ensure_ascii=False, indent=2)
    with open(md_path, "w", encoding="utf-8") as f:
        f.write(render_markdown(report))

    counts = report["counts"]
    print(f"\n[{args.set_name}] Done in {time.time() - start:.1f}s: {counts['stable']}/{counts['resumes']} stable, "
          f"{counts['recommendation_changed']} with a changed Match Recommendation, {counts['verdict_changed']} with "
          f"a changed Verdict, {counts['with_failed_evaluation']} with a Failed Evaluation.", file=sys.stderr)
    print(f"[{args.set_name}] Report: {md_path}", file=sys.stderr)

    # A request that failed measures the server, not the model: the report is kept, the job fails
    crashed = sum(1 for r in extractions.values() if r.get("raised"))
    crashed += sum(
        1 for evals in results.values() for r in evals
        if r.get("raised") or ("report" in r and crashed_categories(r["report"]))
    )
    if crashed:
        print(f"[{args.set_name}] [Error] {crashed} extractions or evaluations raised (a request failed: server down, "
              f"timeout, or rejected; or a Category crashed). See the report's failed extractions and Failed "
              f"Evaluations for each error.", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
