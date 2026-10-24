"""
Candidate scoring: every rule from a run's Verdicts to the Match Recommendation. Pure: no LLM call, no file I/O.
"""
import re
import sys
import statistics
from collections import Counter
from typing import Dict, List, Any, Literal, NamedTuple, Optional

from src.core.config import (
    CATEGORY_LABELS, IMPORTANCE_WEIGHTS, DEFAULT_IMPORTANCE, MUST_HAVE, DIMENSION_WEIGHTS, FALLBACK_ERROR_SCORE,
    MATCH_THRESHOLDS
)
from src.core.language import is_english
from src.core.importance import normalize_importance, base_weight, criterion_max_points
from src.pipelines.evaluator_utils import clean_and_deduplicate_list


class CategoryOutcome(NamedTuple):
    name: str
    # The Criterion texts retrieved for the Category; empty makes it Not Applicable
    retrieved: List[str]
    # Each run's dict from score_run, or the failed-run dict once retries ran out
    runs: List[Dict[str, Any]]
    # Wall-clock seconds for the retrieval and every run; 0.0 when the Category crashed
    elapsed: float
    # The exception text, when the Category crashed
    error: Optional[str] = None


class CandidateScore(NamedTuple):
    dimension_scores: Dict[str, Any]
    category_timings: Dict[str, float]
    overall_score: float
    # Already MUST_HAVE_REJECTED when a Must-have Rejection applies
    match_recommendation: Literal["STRONG_MATCH", "POTENTIAL_MATCH", "LOW_MATCH", "REJECT", "MUST_HAVE_REJECTED"]
    status: Literal["ok", "error"]
    must_have_rejection: List[Dict[str, str]]
    # Keys of the Categories that failed; any one makes this a Failed Evaluation
    failed_categories: List[str]


EMPTY_QUOTE_PLACEHOLDERS = ("null", "none", "n/a", "na", "", "không có", "không", "none.", "nil")


def _not_one_verdict_per_criterion(importance_map: Dict[str, str], echoed_criteria: List[str]) -> bool:
    """True unless every Criterion in importance_map got exactly one Verdict and no Verdict names another text."""
    return Counter(echoed_criteria) != Counter(importance_map.keys())


def score_run(parsed: Any, importance_map: Optional[Dict[str, str]] = None) -> Optional[Dict[str, Any]]:
    """
    One run's Category score from its parsed reply, or None when the reply is invalid.
    If criteria_evaluations list is present, computes score deterministically from atomic criteria coverage: the
    Must-have and Standard Verdicts weighted by each Criterion's Importance from importance_map ({criterion_text:
    importance}, looked up by the exact text the schema forces) make up the 100, and Nice-to-have Verdicts only add
    to it, capped at 100. Each Criterion gets its Criterion Points (max_points, earned_points). Without a map every
    Criterion is Standard, i.e. a plain mean.
    Otherwise, validates the numeric score (0-100) and required output fields.
    Invalid (None, so the run is retried) unless every Criterion in importance_map got exactly one Verdict: a skipped
    or doubled Criterion changes the score and could hide a Must-have Rejection.
    """
    if not isinstance(parsed, dict) or not parsed:
        return None

    # 1. Process atomic criteria_evaluations if present for deterministic scoring
    cleaned_criteria = []
    all_criteria_quotes: List[str] = []
    deterministic_score: Optional[int] = None
    raw_criteria = parsed.get("criteria_evaluations")
    bonus_capped = False
    if isinstance(raw_criteria, list) and len(raw_criteria) > 0:
        total_score_acc = 0.0
        for item in raw_criteria:
            if isinstance(item, dict):
                crit_text = str(item.get("criterion", "")).strip()
                verdict = str(item.get("verdict", "")).strip().upper()
                # Current format lists quotes under "evidence_quotes"; older outputs hold one string in "evidence_quote"
                raw_quotes = item.get("evidence_quotes", item.get("evidence_quote"))
                if not isinstance(raw_quotes, list):
                    raw_quotes = [] if raw_quotes is None else [raw_quotes]

                # Filter out null, none, n/a, or empty placeholders
                item_quotes = clean_and_deduplicate_list(
                    [q for q in raw_quotes if q is not None and str(q).strip().lower() not in EMPTY_QUOTE_PLACEHOLDERS],
                    max_items=6
                )
                all_criteria_quotes.extend(item_quotes)
                quote_str: Optional[str] = " | ".join(item_quotes) or None

                # Strict discrete verdict scoring mapping based on prompt specification
                if verdict == "STRONG_EVIDENCE":
                    s = 1.0
                elif verdict == "PARTIAL_EVIDENCE":
                    s = 0.5
                else:
                    s = 0.0

                importance = normalize_importance(importance_map.get(crit_text)) if importance_map else DEFAULT_IMPORTANCE
                total_score_acc += IMPORTANCE_WEIGHTS[importance] * s
                cleaned_criteria.append({
                    "criterion": crit_text,
                    "importance": importance,
                    "verdict": verdict if verdict in ("STRONG_EVIDENCE", "PARTIAL_EVIDENCE", "NO_EVIDENCE") else ("STRONG_EVIDENCE" if s >= 0.9 else "PARTIAL_EVIDENCE" if s >= 0.4 else "NO_EVIDENCE"),
                    "score": round(s, 2),
                    "evidence_quote": quote_str,
                    "evidence_quotes": item_quotes,
                    # The model's reasoning written before the verdict; absent from outputs older than that format
                    "reasoning": str(item.get("reasoning", "")).strip()
                })

        if importance_map and _not_one_verdict_per_criterion(importance_map, [c["criterion"] for c in cleaned_criteria]):
            print(f"[Eval Validation] Not every Criterion got exactly one Verdict: {[c['criterion'] for c in cleaned_criteria]}", file=sys.stderr)
            return None

        category_base_weight = base_weight(c["importance"] for c in cleaned_criteria)
        if category_base_weight > 0:
            raw_score = total_score_acc / category_base_weight * 100.0
            # The Nice-to-haves met push past the Category's 100, so the Criterion rows add up to more than the gauge
            bonus_capped = raw_score > 100.0
            deterministic_score = int(round(min(100.0, raw_score)))
            for c in cleaned_criteria:
                max_points = criterion_max_points(c["importance"], category_base_weight)
                c["max_points"] = round(max_points, 1)
                c["earned_points"] = round(max_points * c["score"], 1)

    # 2. Determine final score (deterministic calculation preferred, fallback to explicit score)
    score: Optional[int] = None
    if deterministic_score is not None:
        score = deterministic_score
    else:
        score_val = parsed.get("score")
        if score_val is not None:
            try:
                score_str = str(score_val).strip()
                if not score_str.startswith("<") and any(c.isdigit() for c in score_str):
                    clean_num = re.sub(r'[^0-9.]', '', score_str)
                    if clean_num:
                        score = int(round(float(clean_num)))
            except (ValueError, TypeError):
                score = None

    if score is None or not (0 <= score <= 100):
        return None

    strengths = clean_and_deduplicate_list(parsed.get("strengths", []), max_items=10)
    gaps = clean_and_deduplicate_list(parsed.get("gaps", []), max_items=8)
    quotes = clean_and_deduplicate_list(parsed.get("evidence_quotes", []), max_items=6)
    if not quotes and cleaned_criteria:
        quotes = clean_and_deduplicate_list(all_criteria_quotes, max_items=6)
    reasoning = str(parsed.get("reasoning_summary", "")).strip()

    result: Dict[str, Any] = {
        "score": score,
        "strengths": strengths,
        "gaps": gaps,
        "evidence_quotes": quotes,
        "reasoning_summary": reasoning
    }
    if cleaned_criteria:
        result["criteria_evaluations"] = cleaned_criteria
        result["bonus_capped"] = bonus_capped

    return result


def _count_must_have_no_evidence(eval_runs: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    For each must-have Criterion judged in a Category's runs, the number of runs that gave it NO_EVIDENCE, as
    [{"criterion", "no_evidence_runs"}]. Every run echoes each Criterion's exact text (the schema forces it), so
    runs are matched by that text; a run that echoes one twice counts once.
    """
    counts: Dict[str, Dict[str, Any]] = {}
    for run in eval_runs:
        no_evidence_in_run = set()
        for crit in run.get("criteria_evaluations") or []:
            if not isinstance(crit, dict) or crit.get("importance") != MUST_HAVE:
                continue
            key = str(crit.get("criterion", "")).strip()
            entry = counts.setdefault(key, {"criterion": str(crit.get("criterion", "")).strip(), "no_evidence_runs": 0})
            if str(crit.get("verdict", "")).upper() == "NO_EVIDENCE" and key not in no_evidence_in_run:
                no_evidence_in_run.add(key)
                entry["no_evidence_runs"] += 1
    return list(counts.values())


def _collect_must_have_rejection(dimension_results: Dict[str, Any]) -> List[Dict[str, str]]:
    """
    Every must-have Criterion that got NO_EVIDENCE in a majority of its Category's runs (more than half; with one
    run, that run), as [{"category", "criterion"}]. Reads each Category's must_have_no_evidence_counts and
    evaluation_runs_count, not the reported median run, so rejection never hangs on which run sorts into the middle.
    Any one makes a Must-have Rejection: the candidate is out (PARTIAL never counts).
    """
    missing: List[Dict[str, str]] = []
    for cat_key, dim in (dimension_results or {}).items():
        if not isinstance(dim, dict) or dim.get("not_applicable"):
            continue
        runs = dim.get("evaluation_runs_count") or 0
        for entry in dim.get("must_have_no_evidence_counts") or []:
            if entry.get("no_evidence_runs", 0) * 2 > runs:
                missing.append({"category": cat_key, "criterion": entry.get("criterion", "")})
    return missing


def _combine_category(outcome: CategoryOutcome, num_evaluations: int, language: str) -> Dict[str, Any]:
    """One Category's result: the crashed-Category entry, the Not Applicable entry, or the lower median of its runs."""
    is_en = is_english(language)

    if outcome.error is not None:
        err_gap = f"Evaluation dimension processing error: {outcome.error}" if is_en else f"Lỗi xử lý mục đánh giá: {outcome.error}"
        return {
            "score": FALLBACK_ERROR_SCORE,
            "strengths": [],
            "gaps": [err_gap],
            "evidence_quotes": [],
            "reasoning_summary": f"Evaluation execution error: {outcome.error}",
            "error": outcome.error,
            "all_scores": [],
            "median_score": float(FALLBACK_ERROR_SCORE),
            "failed": True
        }

    if not outcome.retrieved:
        reasoning_msg = "No HR requirements specified for this dimension in RAG (Not applicable)." if is_en else "Không có tiêu chí từ HR trong RAG cho mục này (Không áp dụng)."
        return {
            "score": 0,
            "strengths": [],
            "gaps": [],
            "evidence_quotes": [],
            "reasoning_summary": reasoning_msg,
            "all_scores": [0] * num_evaluations,
            "median_score": 0.0,
            "not_applicable": True
        }

    eval_runs = outcome.runs
    has_category_failure = any(r.get("failed", False) for r in eval_runs)
    scores = [r.get("score", FALLBACK_ERROR_SCORE) for r in eval_runs]
    sorted_runs = sorted(eval_runs, key=lambda r: r.get("score", FALLBACK_ERROR_SCORE))
    # The lower median, so with an even run count the score is the shown run's own, matching its Criterion
    # Points and cap note
    med_score = int(statistics.median_low(scores))
    median_idx = (len(sorted_runs) - 1) // 2

    cat_res = dict(sorted_runs[median_idx])
    # The Must-have gate counts NO_EVIDENCE across every run, not just the median one shown to HR
    cat_res["must_have_no_evidence_counts"] = _count_must_have_no_evidence(eval_runs)
    cat_res["score"] = med_score
    cat_res["median_score"] = float(med_score)
    cat_res["all_scores"] = scores
    if has_category_failure:
        cat_res["failed"] = True
    return cat_res


def score_candidate(outcomes: Dict[str, CategoryOutcome], num_evaluations: int, language: str) -> CandidateScore:
    """
    Combines each Category's runs, then the Categories into the Overall Score and Match Recommendation, then applies
    the Must-have gate. outcomes maps each Category key to its CategoryOutcome.
    """
    dimension_results = {}
    category_timings = {}
    weighted_total = 0.0
    any_evaluation_failed = False
    failed_category_names = []
    failed_category_keys = []

    # 1. Identify categories existing vs non-existing in RAG
    existing_cat_keys = []
    non_existing_cat_keys = []

    for cat_key in CATEGORY_LABELS.keys():
        if cat_key in outcomes:
            retrieved = outcomes[cat_key].retrieved
            if retrieved and len(retrieved) > 0:
                existing_cat_keys.append(cat_key)
            else:
                non_existing_cat_keys.append(cat_key)
        else:
            non_existing_cat_keys.append(cat_key)

    # 2. Calculate adjusted weights
    # Divide the percentage sum of non-existing categories equally among existing categories
    non_existing_weight_sum = sum(DIMENSION_WEIGHTS.get(ck, 0.20) for ck in non_existing_cat_keys)

    adjusted_weights = {}
    if non_existing_cat_keys and existing_cat_keys:
        addon = non_existing_weight_sum / len(existing_cat_keys)
        for ck in CATEGORY_LABELS.keys():
            if ck in existing_cat_keys:
                adjusted_weights[ck] = DIMENSION_WEIGHTS.get(ck, 0.20) + addon
            else:
                adjusted_weights[ck] = 0.0
    else:
        for ck in CATEGORY_LABELS.keys():
            adjusted_weights[ck] = DIMENSION_WEIGHTS.get(ck, 0.20)

    # 3. Process each category with adjusted weights
    for cat_key, cat_name in CATEGORY_LABELS.items():
        if cat_key in outcomes:
            outcome = outcomes[cat_key]
            cat_name, retrieved, elapsed_cat = outcome.name, outcome.retrieved, outcome.elapsed
            cat_res = _combine_category(outcome, num_evaluations, language)
        else:
            cat_res = {
                "score": FALLBACK_ERROR_SCORE,
                "strengths": [],
                "gaps": ["Lỗi xử lý mục đánh giá"],
                "evidence_quotes": [],
                "reasoning_summary": "Evaluation error.",
                "all_scores": [],
                "median_score": float(FALLBACK_ERROR_SCORE),
                "failed": True
            }
            retrieved = []
            elapsed_cat = 0.0

        if cat_res.get("failed", False):
            any_evaluation_failed = True
            failed_category_names.append(cat_name)
            failed_category_keys.append(cat_key)

        category_timings[cat_key] = round(elapsed_cat, 2)
        weight = round(adjusted_weights.get(cat_key, 0.20), 4)

        if cat_key in non_existing_cat_keys:
            score = 0
            weighted_score = 0.0
        else:
            score = cat_res.get("score", FALLBACK_ERROR_SCORE)
            weighted_score = round(score * weight, 2)

        dimension_results[cat_key] = {
            "category_name": cat_name,
            "weight": weight,
            "score": score,
            "weighted_score": weighted_score,
            "strengths": cat_res.get("strengths", []),
            "gaps": cat_res.get("gaps", []),
            "evidence_quotes": cat_res.get("evidence_quotes", []),
            "reasoning_summary": cat_res.get("reasoning_summary", ""),
            # Per-criterion verdicts with the resume quotes given for each, from the median run
            "criteria_evaluations": cat_res.get("criteria_evaluations", []),
            # The Nice-to-haves met pushed that run past the Category's 100, so the gauge is capped below its rows
            "bonus_capped": cat_res.get("bonus_capped", False),
            # How many runs gave each must-have Criterion NO_EVIDENCE; a majority makes a Must-have Rejection
            "must_have_no_evidence_counts": cat_res.get("must_have_no_evidence_counts", []),
            "retrieved_criteria": retrieved,
            "processing_time_seconds": round(elapsed_cat, 2),
            "evaluation_runs_count": num_evaluations,
            "all_run_scores": cat_res.get("all_scores", []),
            "median_score": cat_res.get("median_score", float(score))
        }
        # A Not Applicable Category: HR's requirements gave it no Criterion, so it is never shown to HR
        if cat_res.get("not_applicable"):
            dimension_results[cat_key]["not_applicable"] = True
        weighted_total += score * weight

    if any_evaluation_failed:
        # Failed categories zeroed; partial scores kept for debugging
        for cat_key, cat_data in dimension_results.items():
            if cat_data.get("score") == FALLBACK_ERROR_SCORE and cat_key in [
                ck for ck, cn in CATEGORY_LABELS.items() if cn in failed_category_names
            ]:
                dimension_results[cat_key]["score"] = 0
                dimension_results[cat_key]["weighted_score"] = 0.0
                dimension_results[cat_key]["median_score"] = 0.0
                dimension_results[cat_key]["all_run_scores"] = []

    # Recompute weighted_total from final dimension scores (post-failure adjustment)
    weighted_total = sum(
        d["score"] * d["weight"] for d in dimension_results.values()
    )

    overall_score = round(weighted_total, 1)
    if overall_score >= MATCH_THRESHOLDS["STRONG"]:
        recommendation = "STRONG_MATCH"
    elif overall_score >= MATCH_THRESHOLDS["POTENTIAL"]:
        recommendation = "POTENTIAL_MATCH"
    elif overall_score >= MATCH_THRESHOLDS["LOW"]:
        recommendation = "LOW_MATCH"
    else:
        recommendation = "REJECT"

    # A Failed Evaluation keeps its partial scores for debugging, but is never ranked or shown as a result.
    # The Must-have gate applies only to a fully scored evaluation: a Failed Evaluation needs a rerun first
    must_have_rejection = [] if failed_category_keys else _collect_must_have_rejection(dimension_results)

    return CandidateScore(
        dimension_scores=dimension_results,
        category_timings=category_timings,
        overall_score=overall_score,
        # A Must-have Rejection replaces the recommendation, so every consumer sees the candidate is out;
        # the overall and Category scores stay as computed for HR to see
        match_recommendation="MUST_HAVE_REJECTED" if must_have_rejection else recommendation,
        status="error" if failed_category_keys else "ok",
        must_have_rejection=must_have_rejection,
        failed_categories=failed_category_keys
    )
