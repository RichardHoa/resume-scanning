"""
Resume Upload & Extraction FastAPI Router
"""
import os
import sys
import json
import time
from fastapi import APIRouter, UploadFile, File, Form, HTTPException
from fastapi.responses import JSONResponse

from src.core.config import APPROVED_DIR, OUTPUT_DIR
from src.core.state import state
from src.core.evaluation_order import load_evaluation_order, get_candidate_tier

router = APIRouter(prefix="/api", tags=["extraction"])


@router.post("/extract")
async def extract_resume(file: UploadFile = File(...), language: str = Form("vietnamese")):
    """Handles PDF resume uploads, extracts details, and returns JSON."""
    if not file.filename.lower().endswith(".pdf"):
        raise HTTPException(status_code=400, detail="Only PDF files are supported.")

    safe_filename = os.path.basename(file.filename)
    temp_file_path = os.path.join(state.temp_dir, safe_filename)
    try:
        with open(temp_file_path, "wb") as buffer:
            content = await file.read()
            buffer.write(content)
            
        print(f"Received file: {safe_filename}, processing extraction (language: {language})...", file=sys.stderr)
        
        start_time = time.time()
        formatted_json_str = state.extractor.extract(temp_file_path, language=language)
        elapsed_time = time.time() - start_time
        
        try:
            extracted_data = json.loads(formatted_json_str)
            headers = {"X-Extraction-Time": f"{elapsed_time:.2f}"}

            if isinstance(extracted_data, dict) and "error" in extracted_data:
                return JSONResponse(content=extracted_data, status_code=400, headers=headers)

            output_dir = OUTPUT_DIR
            os.makedirs(output_dir, exist_ok=True)
            base_name = os.path.splitext(safe_filename)[0]
            with open(os.path.join(output_dir, f"{base_name}.json"), "w", encoding="utf-8") as f:
                json.dump(extracted_data, f, ensure_ascii=False, indent=2)

            return JSONResponse(content=extracted_data, headers=headers)
        except json.JSONDecodeError:
            headers = {"X-Extraction-Time": f"{elapsed_time:.2f}"}
            return JSONResponse(
                content={"error": "Failed to parse model output as JSON", "raw_output": formatted_json_str},
                status_code=500,
                headers=headers
            )
            
    except Exception as e:
        print(f"Error during extraction of {safe_filename}: {e}", file=sys.stderr)
        raise HTTPException(status_code=500, detail=str(e))
        
    finally:
        if os.path.exists(temp_file_path):
            try:
                os.remove(temp_file_path)
            except Exception as cleanup_err:
                print(f"Warning: Failed to delete temp file {temp_file_path}: {cleanup_err}", file=sys.stderr)


@router.get("/scanned_resumes")
def get_scanned_resumes():
    """Lists all scanned/extracted JSON resumes available in approved_jsons and output_jsons, sorted by secret evaluation_order."""
    order_data = load_evaluation_order()
    search_dirs = [
        APPROVED_DIR,
        OUTPUT_DIR
    ]
    
    resumes = []
    seen_names = set()

    for sdir in search_dirs:
        if not os.path.exists(sdir):
            continue
        for fname in sorted(os.listdir(sdir)):
            if fname.endswith(".json") and fname not in seen_names:
                seen_names.add(fname)
                fpath = os.path.join(sdir, fname)
                try:
                    with open(fpath, "r", encoding="utf-8") as f:
                        data = json.load(f)
                    
                    pos_info = data.get("position_applied", {}) if isinstance(data, dict) else {}
                    skills = data.get("skills_and_specialties", []) if isinstance(data, dict) else []
                    
                    tier_info = get_candidate_tier(data, fname, order_data)
                    
                    resumes.append({
                        "filename": fname,
                        "path": fpath,
                        "title": pos_info.get("title", "N/A"),
                        "level": pos_info.get("level", "unknown"),
                        "email": tier_info["resolved_email"],
                        "skills_count": len(skills),
                        "skills_preview": skills[:5],
                        "tier": tier_info["tier"],
                        "tier_name": tier_info["tier_name"],
                        "tier_order": tier_info["tier_order"]
                    })
                except Exception as e:
                    print(f"Warning: Failed to load {fpath}: {e}", file=sys.stderr)

    # Sort resumes by Evaluation Order: Tier 1 (exact order) -> Tier 2 (exact order) -> Tier 3
    resumes.sort(key=lambda r: (r["tier"], r["tier_order"], r["filename"]))
    return {
        "resumes": resumes,
        "evaluation_order_active": order_data["file_found"],
        "evaluation_order_path": order_data["file_path"],
        "tier1_count": len(order_data["tier1"]),
        "tier2_count": len(order_data["tier2"])
    }
