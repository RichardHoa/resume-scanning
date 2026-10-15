"""
Criterion Importance helpers: reading a Criterion that may be a plain string or {"text", "importance"}
"""
from typing import Any, Tuple

from src.core.config import IMPORTANCE_WEIGHTS, DEFAULT_IMPORTANCE


def normalize_importance(value: Any) -> str:
    """A valid Importance key; anything missing or unknown (old HR RAG, plain strings) reads as Standard."""
    key = str(value or "").strip().lower()
    return key if key in IMPORTANCE_WEIGHTS else DEFAULT_IMPORTANCE


def split_criterion_item(item: Any) -> Tuple[str, str]:
    """(text, importance) of a Criterion given as a plain string or as {"text": ..., "importance": ...}."""
    if isinstance(item, dict):
        return str(item.get("text") or "").strip(), normalize_importance(item.get("importance"))
    if item is None:
        return "", DEFAULT_IMPORTANCE
    return str(item).strip(), DEFAULT_IMPORTANCE
