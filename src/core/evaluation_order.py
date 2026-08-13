"""
Candidate Evaluation Order & Identifiers Service
"""
import os
import sys
import json
import re
from typing import Dict, List, Optional, Any, Set

from src.core.config import ROOT_DIR, EVAL_RESULTS_DIR, EVALUATION_JSON_DIR

SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def load_evaluation_order() -> dict:
    """
    Locates and reads the secret file 'evaluation_order.txt' or 'evaluation_order'
    from project root, cwd, or subdirectories.
    Returns parsed tier1 and tier2 email/name/filename lists.
    """
    search_dirs = [
        ROOT_DIR,
        os.getcwd(),
        SRC_DIR,
        os.path.dirname(ROOT_DIR)
    ]
    
    possible_names = [
        "evaluation_order.txt",
        "evaluation_order",
        ".evaluation_order",
        "evaluation_order.md",
        "evaluation-order.txt",
        "evaluation-order"
    ]

    found_path = None
    # 1. Check search_dirs directly
    for d in search_dirs:
        if not d or not os.path.isdir(d):
            continue
        for pname in possible_names:
            p = os.path.join(d, pname)
            if os.path.isfile(p):
                found_path = p
                break
        if found_path:
            break
            
        # Case-insensitive dir scan
        try:
            for fname in os.listdir(d):
                if fname.lower() in possible_names:
                    found_path = os.path.join(d, fname)
                    break
        except Exception:
            pass
        if found_path:
            break

    # 2. Recursive search in workspace if not found
    if not found_path:
        for d in search_dirs:
            if not d or not os.path.isdir(d):
                continue
            for root, _, files in os.walk(d):
                for fname in files:
                    if fname.lower() in possible_names or fname.lower().startswith("evaluation_order"):
                        found_path = os.path.join(root, fname)
                        break
                if found_path:
                    break
            if found_path:
                break

    tier1: List[str] = []
    tier2: List[str] = []
    if not found_path:
        print(f"[SERVER EVALUATION ORDER] Secret file not found in search dirs: {search_dirs}", file=sys.stderr)
        return {"tier1": tier1, "tier2": tier2, "file_found": False, "file_path": None}

    try:
        with open(found_path, "r", encoding="utf-8", errors="replace") as f:
            lines = f.readlines()
        
        current_tier = 1
        for line in lines:
            stripped = line.strip()
            if not stripped or stripped.startswith("#"):
                continue
            
            # Check for separator: '---', '--- tier 2 ---', 'tier 2', etc.
            if stripped.startswith("---") or "tier 2" in stripped.lower() or "tier2" in stripped.lower():
                current_tier = 2
                continue

            # Extract bracketed items like Name <email@domain.com>
            if "<" in stripped and ">" in stripped:
                m = re.search(r'<([^>]+)>', stripped)
                if m:
                    stripped = m.group(1).strip()
            
            clean_item = stripped.strip("\"' ").lower()
            if not clean_item:
                continue

            if current_tier == 1:
                if clean_item not in tier1:
                    tier1.append(clean_item)
            else:
                if clean_item not in tier2:
                    tier2.append(clean_item)

        print(f"[SERVER EVALUATION ORDER] Loaded secret file from '{found_path}': Tier 1={len(tier1)} items, Tier 2={len(tier2)} items", file=sys.stderr)
        return {"tier1": tier1, "tier2": tier2, "file_found": True, "file_path": found_path}
    except Exception as e:
        print(f"[SERVER EVALUATION ORDER] Error reading file {found_path}: {e}", file=sys.stderr)
        return {"tier1": tier1, "tier2": tier2, "file_found": False, "file_path": found_path}


def extract_candidate_identifiers(data: dict, fname: str) -> dict:
    """
    Extracts all possible identifiers (emails, names, filenames) for a candidate resume
    to match against items in evaluation_order.txt.
    """
    emails: Set[str] = set()
    names: Set[str] = set()
    
    base_name = os.path.splitext(fname)[0].lower()
    fname_lower = fname.lower()
    
    if isinstance(data, dict):
        data_str = json.dumps(data).lower()
        found_emails = re.findall(r'[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}', data_str)
        for em in found_emails:
            emails.add(em.strip().lower())
            prefix = em.split("@")[0].strip().lower()
            if len(prefix) > 2:
                names.add(prefix)

        basic = data.get("basic_information") or data.get("basic_info") or {}
        if isinstance(basic, dict):
            for k in ["name", "full_name", "email", "location"]:
                v = basic.get(k)
                if v and isinstance(v, str):
                    names.add(v.strip().lower())
                    
        pos = data.get("position_applied") or {}
        if isinstance(pos, dict):
            t = pos.get("title")
            if t and isinstance(t, str):
                names.add(t.strip().lower())
                
    main_email = list(emails)[0] if emails else "N/A"
    return {
        "email": main_email,
        "all_emails": emails,
        "all_names": names,
        "filename": fname_lower,
        "base_name": base_name
    }


def get_candidate_tier(data: dict, fname: str, order_data: dict) -> dict:
    """
    Computes candidate tier (1, 2, or 3) and exact evaluation order index
    matching email, username, filename, or name against evaluation_order.txt items.
    """
    tier1 = order_data.get("tier1", [])
    tier2 = order_data.get("tier2", [])
    
    c_info = extract_candidate_identifiers(data, fname)
    c_email = c_info["email"]
    all_emails = c_info["all_emails"]
    all_names = c_info["all_names"]
    fname_lower = c_info["filename"]
    base_name = c_info["base_name"]

    def matches(target_list):
        for idx, item in enumerate(target_list):
            item_clean = item.strip().lower()
            if not item_clean or len(item_clean) < 2:
                continue
                
            # 1. Exact match with any candidate email or email username/prefix
            for em in all_emails:
                em_prefix = em.split("@")[0].strip().lower() if "@" in em else ""
                if item_clean == em or (em_prefix and item_clean == em_prefix):
                    return idx

            # 2. Exact match with filename or base name
            if item_clean == fname_lower or item_clean == base_name:
                return idx

            # 3. Exact match with candidate name or position title
            for nm in all_names:
                if item_clean == nm:
                    return idx
        return -1

    idx1 = matches(tier1)
    if idx1 >= 0:
        return {
            "tier": 1,
            "tier_name": "Resume Tier 1",
            "tier_order": idx1,
            "resolved_email": c_email
        }

    idx2 = matches(tier2)
    if idx2 >= 0:
        return {
            "tier": 2,
            "tier_name": "Resume Tier 2",
            "tier_order": idx2,
            "resolved_email": c_email
        }

    return {
        "tier": 3,
        "tier_name": "Resume Tier 3",
        "tier_order": 9999,
        "resolved_email": c_email
    }


def get_eval_search_dirs() -> List[str]:
    """Returns valid directories where evaluation JSON result files are stored."""
    dirs = [
        EVAL_RESULTS_DIR,
        EVALUATION_JSON_DIR,
        os.path.join(ROOT_DIR, "eval_results"),
        os.path.join(ROOT_DIR, "evaluation_json"),
        os.path.join(os.getcwd(), "eval_results"),
        os.path.join(os.getcwd(), "evaluation_json")
    ]
    valid_dirs: List[str] = []
    for d in dirs:
        if d and os.path.isdir(d) and d not in valid_dirs:
            valid_dirs.append(d)
    return valid_dirs


def find_eval_file(filename: str) -> Optional[str]:
    """Finds exact path of an evaluation JSON file given its filename."""
    safe_filename = os.path.basename(filename)
    for folder in get_eval_search_dirs():
        fpath = os.path.join(folder, safe_filename)
        if os.path.isfile(fpath):
            return fpath
    return None
