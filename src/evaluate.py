#!/usr/bin/env python3
import os
import sys
import json
import argparse
import re
import numpy as np

# ---------------------------------------------------------
# PyTorch & Transformers Import Check and Fallback
# ---------------------------------------------------------
HAS_TORCH_TRANSFORMERS = False
try:
    import torch
    from transformers import AutoTokenizer, AutoModel
    HAS_TORCH_TRANSFORMERS = True
except ImportError:
    pass

# ---------------------------------------------------------
# Embedding Model Helpers
# ---------------------------------------------------------

# Mean Pooling - Take attention mask into account for correct averaging
def mean_pooling(model_output, attention_mask):
    token_embeddings = model_output[0]  # First element contains all token embeddings
    input_mask_expanded = attention_mask.unsqueeze(-1).expand(token_embeddings.size()).float()
    return torch.sum(token_embeddings * input_mask_expanded, 1) / torch.clamp(input_mask_expanded.sum(1), min=1e-9)

class EmbeddingEvaluator:
    def __init__(self, model_name_or_path='AITeamVN/Vietnamese_Embedding'):
        print(f"Loading embedding model: {model_name_or_path}...", file=sys.stderr)
        self.tokenizer = AutoTokenizer.from_pretrained(model_name_or_path)
        self.model = AutoModel.from_pretrained(model_name_or_path)
        
        # GPU / MPS detection
        if torch.cuda.is_available():
            self.device = torch.device("cuda")
        elif torch.backends.mps.is_available():
            self.device = torch.device("mps")
        else:
            self.device = torch.device("cpu")
            
        self.model = self.model.to(self.device)
        self.model.eval()
        self.cache = {}
        print(f"Embedding model loaded on device: {self.device}", file=sys.stderr)

    def get_embeddings(self, texts):
        if not texts:
            return []
        
        # Filter for uncached texts
        uncached = list(set(t for t in texts if t not in self.cache))
        
        # Process in batches
        batch_size = 16
        for i in range(0, len(uncached), batch_size):
            batch = uncached[i:i+batch_size]
            inputs = self.tokenizer(batch, padding=True, truncation=True, return_tensors='pt', max_length=512)
            inputs = {k: v.to(self.device) for k, v in inputs.items()}
            with torch.no_grad():
                outputs = self.model(**inputs)
            embeddings = mean_pooling(outputs, inputs['attention_mask']).cpu().numpy()
            for text, emb in zip(batch, embeddings):
                self.cache[text] = emb
                
        return [self.cache[t] for t in texts]

    def get_embedding(self, text):
        cleaned = str(text).strip()
        if not cleaned:
            # Return zero vector matching the model's hidden dimension
            hidden_size = self.model.config.hidden_size
            return np.zeros(hidden_size)
        return self.get_embeddings([cleaned])[0]

class LexicalEvaluator:
    def __init__(self):
        print("Warning: torch or transformers not found locally. Falling back to LexicalEvaluator (difflib SequenceMatcher).", file=sys.stderr)
        self.device = torch.device("cpu") if HAS_TORCH_TRANSFORMERS else "cpu"

    def get_embeddings(self, texts):
        return []

    def get_embedding(self, text):
        return None

# ---------------------------------------------------------
# Similarity & Normalization Metrics
# ---------------------------------------------------------

def cosine_similarity(v1, v2):
    norm_v1 = np.linalg.norm(v1)
    norm_v2 = np.linalg.norm(v2)
    if norm_v1 == 0 or norm_v2 == 0:
        return 0.0
    return float(np.dot(v1, v2) / (norm_v1 * norm_v2))

def normalize_email(email):
    if not email:
        return ""
    email = str(email).strip().lower()
    email = re.sub(r'^mailto:', '', email)
    return email

def normalize_phone(phone):
    if not phone:
        return ""
    phone = str(phone).strip()
    # Keep only digits
    phone = re.sub(r'\D', '', phone)
    # Convert Vietnamese international/local format prefix
    if phone.startswith('84'):
        phone = '0' + phone[2:]
    return phone

def evaluate_email(gt_email, pred_email):
    return 1.0 if normalize_email(gt_email) == normalize_email(pred_email) else 0.0

def evaluate_phone(gt_phone, pred_phone):
    gt_p = normalize_phone(gt_phone)
    pred_p = normalize_phone(pred_phone)
    if not gt_p and not pred_p:
        return 1.0
    return 1.0 if gt_p == pred_p else 0.0

def text_similarity(t1, t2, evaluator):
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

# ---------------------------------------------------------
# Set-Based Evaluation
# ---------------------------------------------------------

def get_tokens(skills_list):
    """Converts a list of skills into a set of normalized word tokens"""
    tokens = set()
    for skill in skills_list:
        clean_skill = str(skill).strip().lower()
        # Replace common punctuation with space to split cleanly, keeping +, #, -
        clean_skill = re.sub(r'[^\w\s\+\#\-]', ' ', clean_skill)
        for token in clean_skill.split():
            if token.strip():
                tokens.add(token.strip())
    return tokens

def evaluate_skills(gt_skills, pred_skills, evaluator=None, threshold=0.80):
    """
    Hybrid Skills Evaluator:
    - If running offline (LexicalEvaluator), falls back to Token Jaccard.
    - If running online (EmbeddingEvaluator), checks if skills match semantically (cosine sim >= threshold)
      OR match via token overlap (token Jaccard >= 0.50).
    """
    if not gt_skills and not pred_skills:
        return 1.0
    if not gt_skills or not pred_skills:
        return 0.0

    gt_list = [str(s).strip() for s in gt_skills if str(s).strip()]
    pred_list = [str(s).strip() for s in pred_skills if str(s).strip()]

    if not gt_list or not pred_list:
        return 0.0

    # Token overlap fallback if offline
    if evaluator is None or isinstance(evaluator, LexicalEvaluator):
        gt_tokens = get_tokens(gt_list)
        pred_tokens = get_tokens(pred_list)
        if not gt_tokens and not pred_tokens:
            return 1.0
        intersection = gt_tokens.intersection(pred_tokens)
        union = gt_tokens.union(pred_tokens)
        return len(intersection) / len(union) if union else 0.0

    # Batch embed everything to optimize GPU usage
    evaluator.get_embeddings(gt_list + pred_list)

    m = len(gt_list)
    n = len(pred_list)
    sim_matrix = np.zeros((m, n))
    
    for i, gt_skill in enumerate(gt_list):
        for j, pred_skill in enumerate(pred_list):
            emb_sim = text_similarity(gt_skill, pred_skill, evaluator)
            
            # Compute token Jaccard for this pair
            t_gt = get_tokens([gt_skill])
            t_pred = get_tokens([pred_skill])
            tok_jaccard = len(t_gt.intersection(t_pred)) / len(t_gt.union(t_pred)) if t_gt.union(t_pred) else 0.0
            
            # Match condition: semantic similarity >= threshold OR token Jaccard >= 0.50
            if emb_sim >= threshold or tok_jaccard >= 0.50:
                sim_matrix[i, j] = max(emb_sim, tok_jaccard)
            else:
                sim_matrix[i, j] = 0.0

    # Solve assignment
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

# ---------------------------------------------------------
# Bipartite Alignment for Nested Structures
# ---------------------------------------------------------

def solve_assignment(cost_matrix):
    """Solves linear sum assignment using SciPy Hungarian if available, fallback to Greedy"""
    try:
        from scipy.optimize import linear_sum_assignment
        return linear_sum_assignment(cost_matrix)
    except ImportError:
        # Robust Greedy Matcher
        m, n = cost_matrix.shape
        row_ind = []
        col_ind = []
        assigned_rows = set()
        assigned_cols = set()
        
        entries = []
        for r in range(m):
            for c in range(n):
                entries.append((cost_matrix[r, c], r, c))
        entries.sort() # ascending cost
        
        for cost, r, c in entries:
            if r not in assigned_rows and c not in assigned_cols:
                row_ind.append(r)
                col_ind.append(c)
                assigned_rows.add(r)
                assigned_cols.add(c)
                if len(assigned_rows) == m or len(assigned_cols) == n:
                    break
        return row_ind, col_ind

def evaluate_nested_list(gt_list, pred_list, field_weights, evaluator, threshold=0.60):
    """
    Hungarian bipartite alignment for list-of-objects fields.
    Computes matching entity F1 times the average matched content similarity.
    """
    if not gt_list and not pred_list:
        return 1.0
    if not gt_list or not pred_list:
        return 0.0

    m = len(gt_list)
    n = len(pred_list)

    # Pre-extract and batch-embed all textual properties for speed
    all_texts = []
    for item in gt_list + pred_list:
        for field in field_weights:
            val = item.get(field, "")
            if isinstance(val, str) and val.strip():
                all_texts.append(val.strip())
            elif isinstance(val, list):
                all_texts.append(json.dumps(val, ensure_ascii=False))
    evaluator.get_embeddings(all_texts)

    # Compute similarity matrix
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

    # Convert to cost matrix (Hungarian minimizes)
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
    # Score is the harmonic matching F1 penalized by the content similarity
    return f1_match * avg_sim

# ---------------------------------------------------------
# Schema Evaluator
# ---------------------------------------------------------

def evaluate_json_pair(gt, pred, evaluator):
    scores = {}
    
    # 1. position_applied
    gt_pa = gt.get("position_applied", {})
    pred_pa = pred.get("position_applied", {})
    scores["position_applied.title"] = text_similarity(gt_pa.get("title", ""), pred_pa.get("title", ""), evaluator)
    
    gt_lvl = str(gt_pa.get("level", "")).strip().lower()
    pred_lvl = str(pred_pa.get("level", "")).strip().lower()
    scores["position_applied.level"] = 1.0 if gt_lvl == pred_lvl else 0.0
    
    scores["position_applied"] = 0.5 * scores["position_applied.title"] + 0.5 * scores["position_applied.level"]

    # 2. self_evaluation
    scores["self_evaluation"] = text_similarity(gt.get("self_evaluation", ""), pred.get("self_evaluation", ""), evaluator)

    # 3. basic_information
    gt_bi = gt.get("basic_information", {})
    pred_bi = pred.get("basic_information", {})
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

    # 4. skills_and_specialties
    scores["skills_and_specialties"] = evaluate_skills(
        gt.get("skills_and_specialties", []), pred.get("skills_and_specialties", []), evaluator
    )

    # 5. certifications
    cert_weights = {"name": 0.5, "issuing_organization": 0.3, "duration": 0.2}
    scores["certifications"] = evaluate_nested_list(
        gt.get("certifications", []), pred.get("certifications", []), cert_weights, evaluator
    )

    # 6. languages
    lang_weights = {"language": 0.5, "proficiency": 0.3, "certificates": 0.2}
    scores["languages"] = evaluate_nested_list(
        gt.get("languages", []), pred.get("languages", []), lang_weights, evaluator
    )

    # 7. work_experience
    work_weights = {
        "company_name": 0.25,
        "company_description": 0.10,
        "position": 0.25,
        "duration": 0.20,
        "responsibilities": 0.20
    }
    scores["work_experience"] = evaluate_nested_list(
        gt.get("work_experience", []), pred.get("work_experience", []), work_weights, evaluator
    )

    # 8. education_background
    edu_weights = {
        "university_name": 0.30,
        "degree": 0.20,
        "field_of_study": 0.20,
        "graduation_year": 0.15,
        "gpa": 0.15
    }
    scores["education_background"] = evaluate_nested_list(
        gt.get("education_background", []), pred.get("education_background", []), edu_weights, evaluator
    )

    # 9. projects
    proj_weights = {"project_name": 0.40, "description": 0.40, "duration": 0.20}
    scores["projects"] = evaluate_nested_list(
        gt.get("projects", []), pred.get("projects", []), proj_weights, evaluator
    )

    # Overall Aggregate Score
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

# ---------------------------------------------------------
# Main Execution
# ---------------------------------------------------------

def main():
    parser = argparse.ArgumentParser(description="Structured JSON Accuracy Evaluator for Resume Extraction")
    parser.add_argument("--gt-dir", type=str, default="approved_jsons",
                        help="Path to directory containing ground truth JSON files")
    parser.add_argument("--pred-dir", type=str, default="output_jsons",
                        help="Path to directory containing generated predicted JSON files")
    parser.add_argument("--model-name", type=str, default="AITeamVN/Vietnamese_Embedding",
                        help="Hugging Face embedding model or local directory path")
    args = parser.parse_args()

    if not os.path.exists(args.gt_dir):
        print(f"Error: Ground truth directory '{args.gt_dir}' does not exist.", file=sys.stderr)
        sys.exit(1)
        
    if not os.path.exists(args.pred_dir):
        print(f"Error: Predictions directory '{args.pred_dir}' does not exist.", file=sys.stderr)
        sys.exit(1)

    # Conditionally initialize Evaluator based on HF torch/transformers presence
    if HAS_TORCH_TRANSFORMERS:
        evaluator = EmbeddingEvaluator(args.model_name)
    else:
        evaluator = LexicalEvaluator()

    gt_files = [f for f in os.listdir(args.gt_dir) if f.lower().endswith('.json')]
    if not gt_files:
        print(f"No JSON files found in ground truth directory '{args.gt_dir}'.", file=sys.stderr)
        sys.exit(0)

    gt_files.sort()
    
    file_scores = {}
    missing_predictions = []

    print("\nComparing predicted JSONs against ground truth...", file=sys.stderr)
    
    for filename in gt_files:
        gt_path = os.path.join(args.gt_dir, filename)
        pred_path = os.path.join(args.pred_dir, filename)
        
        try:
            with open(gt_path, 'r', encoding='utf-8') as f:
                gt_data = json.load(f)
        except Exception as e:
            print(f"Error reading ground truth '{filename}': {e}", file=sys.stderr)
            continue
            
        if not os.path.exists(pred_path):
            missing_predictions.append(filename)
            # Default to 0.0 scores for completely missing prediction
            file_scores[filename] = {
                "position_applied": 0.0,
                "self_evaluation": 0.0,
                "basic_information": 0.0,
                "skills_and_specialties": 0.0,
                "certifications": 0.0,
                "languages": 0.0,
                "work_experience": 0.0,
                "education_background": 0.0,
                "projects": 0.0,
                "overall": 0.0
            }
            continue

        try:
            with open(pred_path, 'r', encoding='utf-8') as f:
                pred_data = json.load(f)
        except Exception as e:
            print(f"Warning: Failed to parse prediction '{filename}' as JSON: {e}", file=sys.stderr)
            file_scores[filename] = {
                "position_applied": 0.0,
                "self_evaluation": 0.0,
                "basic_information": 0.0,
                "skills_and_specialties": 0.0,
                "certifications": 0.0,
                "languages": 0.0,
                "work_experience": 0.0,
                "education_background": 0.0,
                "projects": 0.0,
                "overall": 0.0
            }
            continue

        # Evaluate match
        scores = evaluate_json_pair(gt_data, pred_data, evaluator)
        file_scores[filename] = scores
        print(f"  Processed {filename}: Overall Score = {scores['overall']:.4f}", file=sys.stderr)

    # Compute aggregate statistics
    categories = [
        "position_applied",
        "self_evaluation",
        "basic_information",
        "skills_and_specialties",
        "certifications",
        "languages",
        "work_experience",
        "education_background",
        "projects",
        "overall"
    ]
    
    aggregates = {cat: [] for cat in categories}
    for filename, scores in file_scores.items():
        for cat in categories:
            aggregates[cat].append(scores[cat])

    # Print per-file detailed scores
    print("\n" + "="*80)
    print(" DETAILED PER-FILE SCORES")
    print("="*80)
    for filename in sorted(file_scores.keys()):
        scores = file_scores[filename]
        print(f"File: {filename}")
        print(f"  Overall Score: {scores['overall']:.4f}")
        for cat in categories[:-1]:  # categories excluding 'overall'
            display_name = cat.replace("_", " ").title()
            print(f"    - {display_name:<25}: {scores[cat]:.4f}")
        print("-" * 50)

    print("\n" + "="*80)
    print(" EVALUATION RESULTS SUMMARY")
    print("="*80)
    print(f"Total Ground Truth Files : {len(gt_files)}")
    print(f"Matched Predictions      : {len(gt_files) - len(missing_predictions)}")
    print(f"Missing Predictions      : {len(missing_predictions)}")
    if missing_predictions:
        print(f"  Missing files: {', '.join(missing_predictions)}")
    print("-"*80)
    
    # Print table header
    print(f"{'Category/Section':<28} | {'Average Accuracy/F1 Score':<25}")
    print("-"*80)
    for cat in categories:
        avg_score = np.mean(aggregates[cat])
        # Capitalize and clean category name for displaying
        display_name = cat.replace("_", " ").title()
        if cat == "overall":
            print("-"*80)
            print(f"{display_name:<28} | {avg_score:.4f}")
        else:
            print(f"{display_name:<28} | {avg_score:.4f}")
            
    print("="*80)

if __name__ == "__main__":
    main()
