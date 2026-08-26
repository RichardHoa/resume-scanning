"""
Base classes, data models, and shared utilities for bias & positional order sensitivity detection.
"""
from abc import ABC, abstractmethod
import os
import json
import itertools
import random
from typing import Dict, List, Any, Tuple, Optional, Set


class BaseCategoryBiasBuilder(ABC):
    """
    Abstract Base Class for category-specific bias & positional order sensitivity experiment builders.
    Each evaluation dimension (e.g. technical_skills, seniority_title, education_certifications,
    work_experience) inherits from this class and provides its exact domain chunking and permutation logic.
    """

    @property
    @abstractmethod
    def category_key(self) -> str:
        """Machine-readable key corresponding to CATEGORY_LABELS (e.g. 'technical_skills')."""
        pass

    @property
    @abstractmethod
    def category_label(self) -> str:
        """Human-readable dimension label (e.g. 'Technical Skills & Competencies')."""
        pass

    @abstractmethod
    def extract_candidate_data(self, resume_dict: Dict[str, Any]) -> Dict[str, Any]:
        """Extracts the relevant resume sections for this evaluation dimension."""
        pass

    @abstractmethod
    def build_atomic_chunks(
        self,
        criteria_list: List[str],
        candidate_data: Dict[str, Any]
    ) -> List[Tuple[str, str]]:
        """Decomposes the criteria and candidate data into atomic XML chunks for granular interleaving."""
        pass

    @abstractmethod
    def build_experiments(
        self,
        criteria_list: List[str],
        candidate_data: Dict[str, Any],
        seed: int = 42,
        atomic_sample_size: int = 300
    ) -> List[Tuple[str, str, Any]]:
        """
        Generates all strictly unique experiment iterations across all required test groups:
        Baseline, Macro Permutations, Criteria Intra-Permutations, Candidate Intra-Permutations,
        Spatial Interleaving, and Atomic Interleaving.
        Returns list of (experiment_type, condition_label, permutation_metadata).
        """
        pass

    @abstractmethod
    def render_prompt(
        self,
        exp_type: str,
        perm_meta: Any,
        criteria_list: List[str],
        candidate_data: Dict[str, Any],
        atomic_chunks: List[Tuple[str, str]],
        model_name: str
    ) -> Tuple[str, str]:
        """
        Renders the user prompt and returns a 2-tuple: (prompt_text, order_description).
        """
        pass

    # =========================================================================
    # Shared Helper Utilities
    # =========================================================================
    @staticmethod
    def sanitize_xml(text: str, tag: str) -> str:
        """Escapes closing XML tags within user input content."""
        if not text:
            return ""
        closing_tag = f"</{tag}>"
        escaped_tag = f"&lt;/{tag}&gt;"
        return str(text).replace(closing_tag, escaped_tag)

    @staticmethod
    def render_macro_permutation(
        category_name: str,
        criteria_list: List[str],
        candidate_data: Dict[str, Any],
        order_code: str
    ) -> str:
        """
        Renders the standard 3-block macro permutation prompt (C: Criteria, R: Resume, I: Instructions).
        """
        criteria_str = "\n".join([f"- {c}" for c in criteria_list]).replace("</job_criteria>", "&lt;/job_criteria&gt;")
        snippet_str = json.dumps(candidate_data, ensure_ascii=False, indent=2).replace("</candidate_resume_data>", "&lt;/candidate_resume_data&gt;")

        sec_criteria = f"### JOB REQUIREMENT CRITERIA:\n<job_criteria>\n{criteria_str}\n</job_criteria>"
        sec_candidate = f"### CANDIDATE RESUME SECTION:\n<candidate_resume_data>\n{snippet_str}\n</candidate_resume_data>"
        sec_instructions = (
            f"### INSTRUCTIONS:\n"
            f"Evaluate the candidate resume section inside <candidate_resume_data> against the job requirement criteria "
            f"inside <job_criteria> for the '{category_name}' dimension following your system instructions. "
            f"Return exclusively a valid JSON object."
        )

        block_map = {
            "C": sec_criteria,
            "R": sec_candidate,
            "I": sec_instructions
        }

        selected_blocks = [block_map[k] for k in order_code.split("_")]
        return f"Evaluating dimension: '{category_name}'\n\n" + "\n\n".join(selected_blocks)
