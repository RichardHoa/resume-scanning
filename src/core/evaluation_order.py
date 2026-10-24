"""
Candidate Evaluation Order & Identifiers Service
"""
import os
import sys
import json
import re
from typing import Dict, List, Optional, Any, Set

from src.core.config import ROOT_DIR, RESUME_JSON_DIRS, EVALUATION_JSON_DIRS

SRC_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# The Tech resume set has its own secret file, evaluation_order_tech.txt: the top 10 candidates' emails in rank
# order, with everyone else outside the list. A server started with --tech reads only that file and one started
# with --cnb only evaluation_order.txt, so neither dataset is ranked by the other's answer key. A server started
# with neither has no resume set and reads no order file at all
CNB_RESUME_SET = "cnb"
TECH_RESUME_SET = "tech"
_resume_set: Optional[str] = None
_tech_mode = False


def set_resume_set(resume_set: Optional[str]) -> None:
    """The server's resume set: CNB_RESUME_SET, TECH_RESUME_SET, or None for no dataset."""
    global _resume_set, _tech_mode
    _resume_set = resume_set
    _tech_mode = resume_set == TECH_RESUME_SET


def is_tech_mode() -> bool:
    return _tech_mode


def _is_order_file_name(fname: str) -> bool:
    """Whether a file name found by the recursive search is this mode's secret file (a text file, never code)."""
    name = fname.lower()
    if os.path.splitext(name)[1] not in ("", ".txt", ".md"):
        return False
    if _tech_mode:
        return name.startswith("evaluation_order_tech") or name.startswith("evaluation-order-tech")
    return name.startswith("evaluation_order") and "tech" not in name


def load_evaluation_order() -> dict:
    """
    Locates and reads the secret file 'evaluation_order.txt' (or 'evaluation_order_tech.txt' in tech mode)
    from project root, cwd, or subdirectories.
    Returns parsed tier1 and tier2 email/name/filename lists, both empty when the server has no resume set.
    """
    if _resume_set is None:
        return {"tier1": [], "tier2": [], "file_found": False, "file_path": None, "tech_mode": False}

    search_dirs = [
        ROOT_DIR,
        os.getcwd(),
        SRC_DIR,
        os.path.dirname(ROOT_DIR)
    ]
    
    if _tech_mode:
        possible_names = [
            "evaluation_order_tech.txt",
            "evaluation_order_tech",
            "evaluation_order_tech.md",
            "evaluation-order-tech.txt",
            "evaluation-order-tech"
        ]
    else:
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
                    if fname.lower() in possible_names or _is_order_file_name(fname):
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
        return {"tier1": tier1, "tier2": tier2, "file_found": False, "file_path": None, "tech_mode": _tech_mode}

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
        return {"tier1": tier1, "tier2": tier2, "file_found": True, "file_path": found_path, "tech_mode": _tech_mode}
    except Exception as e:
        print(f"[SERVER EVALUATION ORDER] Error reading file {found_path}: {e}", file=sys.stderr)
        return {"tier1": tier1, "tier2": tier2, "file_found": False, "file_path": found_path, "tech_mode": _tech_mode}


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


def _source_resume_paths(report: dict) -> List[str]:
    """
    Where the extracted resume behind an evaluation report may be, most likely first: the report's
    resume_path, then its resume_name in approved_jsons/ and the run folders' extraction JSONs.
    """
    candidates: List[str] = []
    resume_path = report.get("resume_path")
    if isinstance(resume_path, str) and resume_path:
        candidates.append(resume_path)
        candidates += [os.path.join(d, os.path.basename(resume_path)) for d in RESUME_JSON_DIRS]
    resume_name = report.get("resume_name")
    if isinstance(resume_name, str) and resume_name:
        json_name = os.path.splitext(os.path.basename(resume_name))[0] + ".json"
        candidates += [os.path.join(d, json_name) for d in RESUME_JSON_DIRS]
    return candidates


def find_source_resume_path(report: dict) -> Optional[str]:
    """The extracted resume JSON file an evaluation report was made from, or None when it is gone."""
    for path in _source_resume_paths(report):
        if os.path.isfile(path):
            return path
    return None


def _load_source_resume(report: dict) -> Optional[tuple]:
    """The extracted resume an evaluation report was made from, as (data, filename), or None when it is gone."""
    for path in _source_resume_paths(report):
        if not os.path.isfile(path):
            continue
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception:
            continue
        if isinstance(data, dict):
            return data, os.path.basename(path)
    return None


def get_report_tier(report: dict, fname: str, order_data: dict) -> dict:
    """
    Tier of the candidate behind an evaluation report. Reports no longer carry the candidate's email
    (candidate_identifier is now the extracted name), so matching runs against the source resume,
    falling back to the report itself when that resume is gone.
    """
    source = _load_source_resume(report)
    if source:
        resume_data, resume_fname = source
        return get_candidate_tier(resume_data, resume_fname, order_data)
    return get_candidate_tier(report, fname, order_data)


def get_eval_search_dirs() -> List[str]:
    """Directories of the evaluation JSON files read, the active run folder's first so its copy wins."""
    return [d for d in EVALUATION_JSON_DIRS if os.path.isdir(d)]


def find_eval_file(filename: str) -> Optional[str]:
    """Finds exact path of an evaluation JSON file given its filename."""
    safe_filename = os.path.basename(filename)
    for folder in get_eval_search_dirs():
        fpath = os.path.join(folder, safe_filename)
        if os.path.isfile(fpath):
            return fpath
    return None
