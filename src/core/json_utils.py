"""
JSON Utilities: Schema loading, JSON extraction, cleanup, and auto-repair.
"""
import os
import sys

# Ensure repository root is in sys.path for 'src' package imports
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

import json
import re
from typing import Dict, Any, Optional
from src.core.config import SCHEMAS_DIR


def load_schema_from_file(model_name: str = "qwen") -> dict:
    """Loads the canonical Qwen schema dictionary from the schemas/ directory."""
    schema_path = os.path.join(SCHEMAS_DIR, "qwen_schema.json")
    try:
        with open(schema_path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Warning: Failed to load schema from {schema_path} ({e}). Falling back to empty object.", file=sys.stderr)
        return {}



def extract_json_substring(text: str) -> str:
    """
    Strips out thinking blocks (e.g. <think>...</think>), markdown code blocks,
    and isolates the actual JSON string by finding the first '{' and last '}'.
    """
    if not text:
        return ""
    cleaned = text.strip()

    cleaned = re.sub(r'<think>.*?</think>', '', cleaned, flags=re.DOTALL)
    cleaned = re.sub(r'^Thinking Process:.*?(?=\n\s*\{)', '', cleaned, flags=re.DOTALL | re.IGNORECASE)

    start_idx = cleaned.find('{')
    if start_idx == -1:
        return cleaned

    end_idx = cleaned.rfind('}')
    if end_idx == -1:
        return cleaned[start_idx:]

    return cleaned[start_idx:end_idx + 1]


def repair_truncated_json(text: str) -> str:
    """
    Best-effort repair of a JSON string truncated mid-stream (e.g. due to token limits).
    """
    if not text or not text.strip():
        return text

    in_string = False
    escape_next = False
    stack = []
    ctx_stack = []
    last_safe_end = 0

    i = 0
    n = len(text)
    while i < n:
        ch = text[i]

        if escape_next:
            escape_next = False
            i += 1
            continue

        if ch == '\\' and in_string:
            escape_next = True
            i += 1
            continue

        if ch == '"':
            if in_string:
                in_string = False
                ctx = ctx_stack[-1] if ctx_stack else None
                if ctx and ctx[0] == 'o':
                    if ctx[1] == 'expect_value':
                        last_safe_end = i + 1
                        ctx_stack[-1] = ('o', 'after_value')
                    elif ctx[1] == 'expect_key':
                        ctx_stack[-1] = ('o', 'expect_colon')
                elif ctx and ctx[0] == 'a':
                    last_safe_end = i + 1
            else:
                in_string = True
                ctx = ctx_stack[-1] if ctx_stack else None
                if ctx and ctx[0] == 'o' and ctx[1] == 'after_value':
                    ctx_stack[-1] = ('o', 'expect_key')
            i += 1
            continue

        if in_string:
            i += 1
            continue

        if ch == '{':
            stack.append('o')
            ctx_stack.append(('o', 'expect_key'))
        elif ch == '[':
            stack.append('a')
            ctx_stack.append(('a', 'value'))
        elif ch == '}':
            if stack:
                stack.pop()
                ctx_stack.pop()
            last_safe_end = i + 1
            if ctx_stack:
                parent = ctx_stack[-1]
                if parent[0] == 'o' and parent[1] == 'expect_value':
                    ctx_stack[-1] = ('o', 'after_value')
        elif ch == ']':
            if stack:
                stack.pop()
                ctx_stack.pop()
            last_safe_end = i + 1
            if ctx_stack:
                parent = ctx_stack[-1]
                if parent[0] == 'o' and parent[1] == 'expect_value':
                    ctx_stack[-1] = ('o', 'after_value')
        elif ch == ':':
            if ctx_stack and ctx_stack[-1] == ('o', 'expect_colon'):
                ctx_stack[-1] = ('o', 'expect_value')
        elif ch == ',':
            last_safe_end = i + 1
            if ctx_stack:
                parent = ctx_stack[-1]
                if parent[0] == 'o':
                    ctx_stack[-1] = ('o', 'expect_key')

        i += 1

    safe_text = text[:last_safe_end]

    stack2 = []
    in_str2 = False
    esc2 = False
    for ch in safe_text:
        if esc2:
            esc2 = False
            continue
        if ch == '\\' and in_str2:
            esc2 = True
            continue
        if ch == '"':
            in_str2 = not in_str2
            continue
        if in_str2:
            continue
        if ch == '{':
            stack2.append('o')
        elif ch == '[':
            stack2.append('a')
        elif ch in ('}', ']'):
            if stack2:
                stack2.pop()

    closing = ''.join('}' if s == 'o' else ']' for s in reversed(stack2))
    repaired = safe_text.rstrip().rstrip(',') + closing

    REQUIRED_KEYS = {
        "position_applied":       '{"title": ""}',
        "self_evaluation":        '""',
        "skills_and_specialties": '[]',
        "languages":              '[]',
        "certifications":         '[]',
        "work_experience":        '[]',
        "basic_information":      '{"email": "", "phone": "", "location": "", "other_info": ""}',
        "education_background":   '[]',
        "projects":               '[]',
    }
    try:
        obj = json.loads(repaired)
        for key, default_str in REQUIRED_KEYS.items():
            if key not in obj:
                obj[key] = json.loads(default_str)
        return json.dumps(obj, ensure_ascii=False)
    except json.JSONDecodeError:
        return repaired


def fix_array_key_value_syntax(text: str) -> str:
    """
    Fixes invalid LLM JSON outputs where key-value pairs are placed inside string arrays:
      ["item1", "key": "value"] -> ["item1", "key: value"]
    """
    def repair_kv(match):
        key = match.group(1)
        val = match.group(2).strip()
        if val.startswith('"') and val.endswith('"') and len(val) >= 2:
            val = val[1:-1]
        return f'"{key}: {val}"'

    def replace_array_content(match):
        array_body = match.group(1)
        fixed_body = re.sub(
            r'"([a-zA-Z0-9_-]+)"\s*:\s*("[^"\r\n]*?"|\d+|true|false|null)',
            repair_kv,
            array_body
        )
        return f"[{fixed_body}]"

    return re.sub(r'\[\s*(.*?)\s*\]', replace_array_content, text, flags=re.DOTALL)


def sanitize_json_string_newlines(text: str) -> str:
    """
    Replaces unescaped literal linebreaks (\n, \r, \t) inside JSON string literals with escaped equivalents.
    """
    if not text:
        return ""
    result = []
    in_string = False
    escape = False
    for ch in text:
        if escape:
            result.append(ch)
            escape = False
            continue
        if ch == '\\' and in_string:
            result.append(ch)
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            result.append(ch)
            continue
        if in_string:
            if ch == '\n':
                result.append('\\n')
            elif ch == '\r':
                result.append('\\r')
            elif ch == '\t':
                result.append('\\t')
            else:
                result.append(ch)
        else:
            result.append(ch)
    return "".join(result)


def clean_and_parse_json(text: str) -> Optional[Dict[str, Any]]:
    """
    Safely extracts and parses JSON dict from LLM string output.
    Strips thinking tags (<think>...</think>), markdown code blocks, fixes unescaped newlines,
    and isolates JSON candidate blocks from right-to-left.
    """
    if not text or not text.strip():
        return None

    # Step 1: Strip thinking tags and process header markers
    cleaned = re.sub(r'<think>.*?</think>', '', text, flags=re.DOTALL)
    cleaned = re.sub(r'<think>.*?(?=\s*\{)', '', cleaned, flags=re.DOTALL)  # Handle unclosed <think> by stripping up to first {
    cleaned = re.sub(r'^Thinking Process:.*?(?=\n\s*[\{`])', '', cleaned, flags=re.DOTALL | re.IGNORECASE)
    cleaned = re.sub(r'```(?:json)?\s*', '', cleaned)
    cleaned = cleaned.replace('```', '').strip()

    def _try_parse(raw_str: str) -> Optional[Dict[str, Any]]:
        if not raw_str or not raw_str.strip():
            return None
        
        # 1. Direct parse
        try:
            p = json.loads(raw_str)
            if isinstance(p, dict):
                return p
        except Exception:
            pass

        # 2. Trailing comma cleanup
        cleaned_str = re.sub(r',\s*([}\]])', r'\1', raw_str)
        try:
            p = json.loads(cleaned_str)
            if isinstance(p, dict):
                return p
        except Exception:
            pass

        # 3. Sanitize unescaped newlines inside string literals
        sanitized = sanitize_json_string_newlines(cleaned_str)
        try:
            p = json.loads(sanitized)
            if isinstance(p, dict):
                return p
        except Exception:
            pass

        # 4. Key-value array syntax fix
        kv_fixed = fix_array_key_value_syntax(sanitized)
        try:
            p = json.loads(kv_fixed)
            if isinstance(p, dict):
                return p
        except Exception:
            pass

        # 5. Internal unescaped double quote repair
        try:
            quote_fixed = re.sub(r'(?<=[a-zA-Z0-9_])"(?=[a-zA-Z0-9_])', "'", kv_fixed)
            p = json.loads(quote_fixed)
            if isinstance(p, dict):
                return p
        except Exception:
            pass

        return None

    # Try direct parse on entire cleaned text first
    res = _try_parse(cleaned)
    if res:
        return res

    # Step 2: Extract candidate JSON object blocks by finding '{' from right to left
    brace_indices = [m.start() for m in re.finditer(r'\{', cleaned)]
    end_idx = cleaned.rfind('}')

    if brace_indices and end_idx != -1:
        # Search backwards from the last '{' to the first '{'
        for start_idx in reversed(brace_indices):
            if start_idx >= end_idx:
                continue
            candidate = cleaned[start_idx:end_idx + 1]
            res = _try_parse(candidate)
            if res:
                return res

    # Step 3: Fallback to repair_truncated_json
    try:
        repaired = repair_truncated_json(extract_json_substring(text))
        res = _try_parse(repaired)
        if res:
            return res
    except Exception:
        pass

    return None

