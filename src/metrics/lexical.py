"""
Lexical matching, email/phone normalization, skill matching, and Hungarian assignment logic.
"""
import os
import sys

# Ensure repository root is in sys.path for 'src' package imports
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import re
import json
from typing import Any, Union, List, Set, Dict, Optional
import numpy as np
from src.metrics.embedding import LexicalEvaluator


def cosine_similarity(v1, v2) -> float:
    norm_v1 = np.linalg.norm(v1)
    norm_v2 = np.linalg.norm(v2)
    if norm_v1 == 0 or norm_v2 == 0:
        return 0.0
    return float(np.dot(v1, v2) / (norm_v1 * norm_v2))


def normalize_email(email: str) -> str:
    if not email:
        return ""
    email = str(email).strip().lower()
    email = re.sub(r'^mailto:', '', email)
    return email


def normalize_phone(phone: str) -> str:
    if not phone:
        return ""
    phone = str(phone).strip()
    phone = re.sub(r'\D', '', phone)
    if phone.startswith('84'):
        phone = '0' + phone[2:]
    return phone


def evaluate_email(gt_email: str, pred_email: str) -> float:
    return 1.0 if normalize_email(gt_email) == normalize_email(pred_email) else 0.0


def evaluate_phone(gt_phone: str, pred_phone: str) -> float:
    gt_p = normalize_phone(gt_phone)
    pred_p = normalize_phone(pred_phone)
    if not gt_p and not pred_p:
        return 1.0
    return 1.0 if gt_p == pred_p else 0.0


def text_similarity(t1: str, t2: str, evaluator: Union[LexicalEvaluator, Any]) -> float:
    t1_clean = str(t1).strip()
    t2_clean = str(t2).strip()
    if not t1_clean and not t2_clean:
        return 1.0
    if not t1_clean or not t2_clean:
        return 0.0
    if t1_clean.lower() == t2_clean.lower():
        return 1.0
    
    if isinstance(evaluator, LexicalEvaluator):
        from difflib import SequenceMatcher
        return SequenceMatcher(None, t1_clean.lower(), t2_clean.lower()).ratio()
        
    v1 = evaluator.get_embedding(t1_clean)
    v2 = evaluator.get_embedding(t2_clean)
    return cosine_similarity(v1, v2)


def get_tokens(skills_list: list) -> set:
    """Converts a list of skills into a set of normalized word tokens"""
    tokens = set()
    for skill in skills_list:
        clean_skill = str(skill).strip().lower()
        clean_skill = re.sub(r'[^\w\s\+\#\-]', ' ', clean_skill)
        for token in clean_skill.split():
            if token.strip():
                tokens.add(token.strip())
    return tokens


def solve_assignment(cost_matrix):
    """Solves linear sum assignment using SciPy Hungarian if available, fallback to Greedy"""
    try:
        from scipy.optimize import linear_sum_assignment
        return linear_sum_assignment(cost_matrix)
    except ImportError:
        m, n = cost_matrix.shape
        row_ind = []
        col_ind = []
        assigned_rows = set()
        assigned_cols = set()
        
        entries = []
        for r in range(m):
            for c in range(n):
                entries.append((cost_matrix[r, c], r, c))
        entries.sort()
        
        for cost, r, c in entries:
            if r not in assigned_rows and c not in assigned_cols:
                row_ind.append(r)
                col_ind.append(c)
                assigned_rows.add(r)
                assigned_cols.add(c)
                if len(assigned_rows) == m or len(assigned_cols) == n:
                    break
        return row_ind, col_ind


def evaluate_skills(gt_skills: list, pred_skills: list, evaluator=None, threshold: float = 0.80) -> float:
    gt_list = [str(s).strip() for s in (gt_skills or []) if str(s).strip()]
    pred_list = [str(s).strip() for s in (pred_skills or []) if str(s).strip()]

    if not gt_list and not pred_list:
        return 1.0
    if not gt_list or not pred_list:
        return 0.0

    if evaluator is None or isinstance(evaluator, LexicalEvaluator):
        gt_tokens = get_tokens(gt_list)
        pred_tokens = get_tokens(pred_list)
        if not gt_tokens and not pred_tokens:
            return 1.0
        intersection = gt_tokens.intersection(pred_tokens)
        union = gt_tokens.union(pred_tokens)
        return len(intersection) / len(union) if union else 0.0

    evaluator.get_embeddings(gt_list + pred_list)

    m = len(gt_list)
    n = len(pred_list)
    sim_matrix = np.zeros((m, n))
    
    for i, gt_skill in enumerate(gt_list):
        for j, pred_skill in enumerate(pred_list):
            emb_sim = text_similarity(gt_skill, pred_skill, evaluator)
            
            t_gt = get_tokens([gt_skill])
            t_pred = get_tokens([pred_skill])
            tok_jaccard = len(t_gt.intersection(t_pred)) / len(t_gt.union(t_pred)) if t_gt.union(t_pred) else 0.0
            
            if emb_sim >= threshold or tok_jaccard >= 0.50:
                sim_matrix[i, j] = max(emb_sim, tok_jaccard)
            else:
                sim_matrix[i, j] = 0.0

    cost_matrix = 1.0 - sim_matrix
    row_ind, col_ind = solve_assignment(cost_matrix)

    tp = 0
    for r, c in zip(row_ind, col_ind):
        if sim_matrix[r, c] > 0.0:
            tp += 1

    precision = tp / n
    recall = tp / m
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return f1


def evaluate_nested_list(gt_list: list, pred_list: list, field_weights: dict, evaluator: Any, threshold: float = 0.60) -> float:
    if not gt_list and not pred_list:
        return 1.0
    if not gt_list or not pred_list:
        return 0.0

    m = len(gt_list)
    n = len(pred_list)

    all_texts = []
    for item in gt_list + pred_list:
        for field in field_weights:
            val = item.get(field, "")
            if isinstance(val, str) and val.strip():
                all_texts.append(val.strip())
            elif isinstance(val, list):
                all_texts.append(json.dumps(val, ensure_ascii=False))
    evaluator.get_embeddings(all_texts)

    sim_matrix = np.zeros((m, n))
    for i, gt_item in enumerate(gt_list):
        for j, pred_item in enumerate(pred_list):
            score = 0.0
            for field, weight in field_weights.items():
                v_gt = gt_item.get(field, "")
                v_pred = pred_item.get(field, "")
                
                if isinstance(v_gt, list) or isinstance(v_pred, list):
                    str_gt = json.dumps(v_gt, ensure_ascii=False) if isinstance(v_gt, list) else str(v_gt)
                    str_pred = json.dumps(v_pred, ensure_ascii=False) if isinstance(v_pred, list) else str(v_pred)
                    f_sim = text_similarity(str_gt, str_pred, evaluator)
                else:
                    f_sim = text_similarity(str(v_gt), str(v_pred), evaluator)
                    
                score += weight * f_sim
            sim_matrix[i, j] = score

    cost_matrix = 1.0 - sim_matrix
    row_ind, col_ind = solve_assignment(cost_matrix)

    tp = 0
    matched_sims = []
    for r, c in zip(row_ind, col_ind):
        sim = sim_matrix[r, c]
        if sim >= threshold:
            tp += 1
            matched_sims.append(sim)

    precision = tp / n
    recall = tp / m
    f1_match = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0

    if f1_match == 0:
        return 0.0

    avg_sim = sum(matched_sims) / len(matched_sims) if matched_sims else 0.0
    return f1_match * avg_sim


def evaluate_json_pair(gt: dict, pred: dict, evaluator: Any) -> dict:
    scores = {}
    gt = gt if isinstance(gt, dict) else {}
    pred = pred if isinstance(pred, dict) else {}
    
    gt_pa = gt.get("position_applied") or {}
    pred_pa = pred.get("position_applied") or {}
    scores["position_applied.title"] = text_similarity(gt_pa.get("title", ""), pred_pa.get("title", ""), evaluator)
    
    gt_lvl = str(gt_pa.get("level", "")).strip().lower()
    pred_lvl = str(pred_pa.get("level", "")).strip().lower()
    scores["position_applied.level"] = 1.0 if gt_lvl == pred_lvl else 0.0
    
    scores["position_applied"] = 0.5 * scores["position_applied.title"] + 0.5 * scores["position_applied.level"]

    scores["self_evaluation"] = text_similarity(gt.get("self_evaluation", ""), pred.get("self_evaluation", ""), evaluator)

    gt_bi = gt.get("basic_information") or {}
    pred_bi = pred.get("basic_information") or {}
    scores["basic_information.email"] = evaluate_email(gt_bi.get("email", ""), pred_bi.get("email", ""))
    scores["basic_information.phone"] = evaluate_phone(gt_bi.get("phone", ""), pred_bi.get("phone", ""))
    scores["basic_information.location"] = text_similarity(gt_bi.get("location", ""), pred_bi.get("location", ""), evaluator)
    scores["basic_information.other_info"] = text_similarity(gt_bi.get("other_info", ""), pred_bi.get("other_info", ""), evaluator)
    
    scores["basic_information"] = (
        0.25 * scores["basic_information.email"] + 
        0.25 * scores["basic_information.phone"] + 
        0.25 * scores["basic_information.location"] + 
        0.25 * scores["basic_information.other_info"]
    )

    scores["skills_and_specialties"] = evaluate_skills(
        gt.get("skills_and_specialties") or [], pred.get("skills_and_specialties") or [], evaluator
    )

    cert_weights = {"name": 0.5, "issuing_organization": 0.3, "duration": 0.2}
    scores["certifications"] = evaluate_nested_list(
        gt.get("certifications") or [], pred.get("certifications") or [], cert_weights, evaluator
    )

    lang_weights = {"language": 0.5, "proficiency": 0.3, "certificates": 0.2}
    scores["languages"] = evaluate_nested_list(
        gt.get("languages") or [], pred.get("languages") or [], lang_weights, evaluator
    )

    work_weights = {
        "company_name": 0.25,
        "company_description": 0.10,
        "position": 0.25,
        "duration": 0.20,
        "responsibilities": 0.20
    }
    scores["work_experience"] = evaluate_nested_list(
        gt.get("work_experience") or [], pred.get("work_experience") or [], work_weights, evaluator
    )

    edu_weights = {
        "university_name": 0.30,
        "degree": 0.20,
        "field_of_study": 0.20,
        "graduation_year": 0.15,
        "gpa": 0.15
    }
    scores["education_background"] = evaluate_nested_list(
        gt.get("education_background") or [], pred.get("education_background") or [], edu_weights, evaluator
    )

    proj_weights = {"project_name": 0.40, "description": 0.40, "duration": 0.20}
    scores["projects"] = evaluate_nested_list(
        gt.get("projects") or [], pred.get("projects") or [], proj_weights, evaluator
    )

    categories = [
        "position_applied",
        "self_evaluation",
        "basic_information",
        "skills_and_specialties",
        "certifications",
        "languages",
        "work_experience",
        "education_background",
        "projects"
    ]
    scores["overall"] = sum(scores[cat] for cat in categories) / len(categories)
    return scores
