"""
Criterion Importance helpers: reading a Criterion that may be a plain string or {"text", "importance"}
"""
from typing import Any, Iterable, Tuple

from src.core.config import IMPORTANCE_WEIGHTS, DEFAULT_IMPORTANCE, NICE_TO_HAVE


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


def is_bonus(importance: str) -> bool:
    """A Nice-to-have: it only adds points to its Category, and lacking it never costs any."""
    return normalize_importance(importance) == NICE_TO_HAVE


def base_weight(importances: Iterable[str]) -> int:
    """The weight the Must-have and Standard Criteria share a Category's 100 points by; 0 when all are Nice-to-have."""
    return sum(IMPORTANCE_WEIGHTS[normalize_importance(i)] for i in importances if not is_bonus(i))


def criterion_max_points(importance: str, category_base_weight: int) -> float:
    """
    The Criterion Points one Criterion is worth out of its Category's 100: its share of the Must-have and Standard
    weight, or for a Nice-to-have the bonus it adds at most. The criteria editor's live preview repeats this formula.
    """
    if category_base_weight <= 0:
        return 0.0
    return IMPORTANCE_WEIGHTS[normalize_importance(importance)] / category_base_weight * 100.0
