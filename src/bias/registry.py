"""
Category Bias Builder Registry and Factory.
"""
from typing import Dict, List, Optional

from src.bias.base import BaseCategoryBiasBuilder
from src.bias.technical_skills import TechnicalSkillsBiasBuilder
from src.bias.seniority_title import SeniorityTitleBiasBuilder
from src.bias.education_certifications import EducationCertificationsBiasBuilder
from src.bias.work_experience import WorkExperienceBiasBuilder


ALL_CATEGORIES: List[str] = [
    "technical_skills",
    "seniority_title",
    "education_certifications",
    "work_experience"
]

_BUILDER_MAP: Dict[str, BaseCategoryBiasBuilder] = {
    "technical_skills": TechnicalSkillsBiasBuilder(),
    "seniority_title": SeniorityTitleBiasBuilder(),
    "education_certifications": EducationCertificationsBiasBuilder(),
    "work_experience": WorkExperienceBiasBuilder()
}


def get_bias_builder(category_key: str) -> BaseCategoryBiasBuilder:
    """Returns the dedicated bias experiment builder for a given category key."""
    norm_key = category_key.strip().lower().replace("-", "_")
    if norm_key not in _BUILDER_MAP:
        available = ", ".join(_BUILDER_MAP.keys())
        raise ValueError(f"Unknown bias category '{category_key}'. Available categories: [{available}]")
    return _BUILDER_MAP[norm_key]


def get_all_category_keys() -> List[str]:
    """Returns the 4 Categories the Bias Check covers (not hidden_culture)."""
    return list(ALL_CATEGORIES)
