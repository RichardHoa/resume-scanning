"""
Education & Certifications Bias & Positional Sensitivity Experiment Builder.
Corresponds to Part 3 of docs/bias_detection_plan.md (549 to 667 unique iterations).
"""
import copy
import itertools
import json
import math
import random
from typing import Dict, List, Any, Tuple, Set

from src.bias.base import BaseCategoryBiasBuilder
from src.prompts.evaluator_prompts import get_category_evaluation_prompt


MACRO_PERMUTATION_ORDERS = [
    ("C_R_I", "Criteria -> Candidate -> Instructions"),
    ("C_I_R", "Criteria -> Instructions -> Candidate"),
    ("R_C_I", "Candidate -> Criteria -> Instructions"),
    ("R_I_C", "Candidate -> Instructions -> Criteria"),
    ("I_C_R", "Instructions -> Criteria -> Candidate"),
    ("I_R_C", "Instructions -> Candidate -> Criteria"),
]


class EducationCertificationsBiasBuilder(BaseCategoryBiasBuilder):
    """
    Bias & Positional Order Sensitivity Builder for Education & Certifications.
    """

    @property
    def category_key(self) -> str:
        return "education_certifications"

    @property
    def category_label(self) -> str:
        return "Education & Certifications"

    def extract_candidate_data(self, resume_dict: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "education_background": resume_dict.get("education_background", []),
            "certifications": resume_dict.get("certifications", []),
            "languages": resume_dict.get("languages", [])
        }

    def build_atomic_chunks(
        self,
        criteria_list: List[str],
        candidate_data: Dict[str, Any]
    ) -> List[Tuple[str, str]]:
        atomic_chunks: List[Tuple[str, str]] = []

        # 1. Criteria Chunks
        for idx, crit in enumerate(criteria_list, start=1):
            clean_crit = self.sanitize_xml(crit, "job_criterion")
            atomic_chunks.append((
                f"Crit_{idx}",
                f"<job_criterion id=\"{idx}\">\n- {clean_crit}\n</job_criterion>"
            ))

        # 2. Education Degrees
        edu_list = candidate_data.get("education_background", [])
        if isinstance(edu_list, list):
            for idx, edu in enumerate(edu_list, start=1):
                edu_str = json.dumps(edu, ensure_ascii=False, indent=2)
                clean_edu = self.sanitize_xml(edu_str, "candidate_education")
                atomic_chunks.append((
                    f"Edu_{idx}",
                    f"<candidate_education id=\"{idx}\">\n{clean_edu}\n</candidate_education>"
                ))

        # 3. Certifications
        cert_list = candidate_data.get("certifications", [])
        if isinstance(cert_list, list):
            for idx, cert in enumerate(cert_list, start=1):
                cert_str = json.dumps(cert, ensure_ascii=False, indent=2)
                clean_cert = self.sanitize_xml(cert_str, "candidate_certification")
                atomic_chunks.append((
                    f"Cert_{idx}",
                    f"<candidate_certification id=\"{idx}\">\n{clean_cert}\n</candidate_certification>"
                ))

        # 4. Languages (if present and non-empty)
        lang_list = candidate_data.get("languages", [])
        if isinstance(lang_list, list) and lang_list:
            lang_str = json.dumps(lang_list, ensure_ascii=False, indent=2)
            atomic_chunks.append((
                "Lang",
                f"<candidate_languages>\n{lang_str}\n</candidate_languages>"
            ))

        # 5. Instructions Chunk
        atomic_chunks.append((
            "INS",
            f"<evaluation_instructions>\n"
            f"Evaluate candidate academic degrees and certifications against the job requirement criteria "
            f"for the '{self.category_label}' dimension following your system instructions. Return exclusively a valid JSON object.\n"
            f"</evaluation_instructions>"
        ))

        return atomic_chunks

    def build_experiments(
        self,
        criteria_list: List[str],
        candidate_data: Dict[str, Any],
        seed: int = 42,
        atomic_sample_size: int = 300
    ) -> List[Tuple[str, str, Any]]:
        experiments: List[Tuple[str, str, Any]] = [
            ("Baseline", "00_baseline", "baseline")
        ]

        # Group 1: Macro Permutations (3! = 6 runs)
        for idx, (order_code, _) in enumerate(MACRO_PERMUTATION_ORDERS, start=1):
            experiments.append(("Macro_Permutation", f"macro_perm_{idx:02d}_{order_code}", order_code))

        # Group 2: Criteria Intra-Permutations (N! combinations if multiple criteria)
        num_criteria = len(criteria_list)
        if num_criteria > 1:
            crit_all_perms = list(itertools.permutations(range(num_criteria)))
            for idx, perm in enumerate(crit_all_perms, start=1):
                experiments.append(("Criteria_Permutation", f"crit_perm_{idx:04d}", perm))

        # Group 3: Candidate Intra-Permutations
        # 3a. Certifications Shuffled (5! = 120 runs)
        certs = candidate_data.get("certifications", [])
        num_certs = len(certs) if isinstance(certs, list) and certs else 1
        cert_perms = list(itertools.permutations(range(num_certs)))
        for idx, perm in enumerate(cert_perms, start=1):
            experiments.append(("Candidate_Certifications_Order", f"cand_cert_perm_{idx:03d}", perm))

        # 3b. Top-Level Section Key Reordering (3! = 6 runs if all 3 keys present)
        all_keys = [k for k in ["education_background", "certifications", "languages"] if k in candidate_data]
        if len(all_keys) >= 2:
            key_perms = list(itertools.permutations(all_keys))
            for idx, perm in enumerate(key_perms, start=1):
                experiments.append(("Candidate_Key_Order", f"cand_key_order_{idx:02d}", perm))

        # Group 4: 5-Chunk Spatial Interleaving (5! = 120 runs)
        # C + R1 (Degree) + R2 (Certs Part 1) + R3 (Certs Part 2) + INS
        spatial_perms = list(itertools.permutations(range(5)))
        for idx, perm in enumerate(spatial_perms, start=1):
            experiments.append(("Spatial_Interleave_5Chunk", f"spat_perm_{idx:03d}", perm))

        # Group 5: Atomic Item-Level Interleaving (300 sampled runs)
        atomic_chunks = self.build_atomic_chunks(criteria_list, candidate_data)
        num_atomic = len(atomic_chunks)
        atomic_rng = random.Random(seed)
        seen_atomic: Set[Tuple[int, ...]] = set()
        atomic_sampled_perms: List[Tuple[int, ...]] = []
        max_possible = math.factorial(num_atomic)
        target_sample = min(atomic_sample_size, max_possible)
        while len(atomic_sampled_perms) < target_sample:
            sampled_p = tuple(atomic_rng.sample(range(num_atomic), num_atomic))
            if sampled_p not in seen_atomic:
                seen_atomic.add(sampled_p)
                atomic_sampled_perms.append(sampled_p)

        for idx, perm in enumerate(atomic_sampled_perms, start=1):
            experiments.append(("Atomic_Interleave", f"atom_perm_{idx:03d}", perm))

        return experiments

    def _get_5_spatial_chunks(
        self,
        criteria_list: List[str],
        candidate_data: Dict[str, Any]
    ) -> List[Tuple[str, str]]:
        crit_str = "\n".join([f"- {c}" for c in criteria_list])
        chunk_c = ("C", f"### JOB REQUIREMENT CRITERIA:\n<job_criteria>\n{crit_str}\n</job_criteria>")

        # R1: Education Degree
        edu_list = candidate_data.get("education_background", [])
        edu_str = json.dumps({"education_background": edu_list}, ensure_ascii=False, indent=2)
        chunk_r1 = ("R1", f"### CANDIDATE FORMAL EDUCATION:\n<candidate_education>\n{edu_str}\n</candidate_education>")

        # R2 & R3: Certifications Partitioned into 2 halves
        certs = candidate_data.get("certifications", [])
        if isinstance(certs, list) and len(certs) > 1:
            mid = max(1, len(certs) // 2)
            c_part1 = certs[:mid]
            c_part2 = certs[mid:]
        else:
            c_part1 = certs if isinstance(certs, list) else []
            c_part2 = []

        c_str1 = json.dumps({"certifications_part_1": c_part1}, ensure_ascii=False, indent=2)
        chunk_r2 = ("R2", f"### CANDIDATE CERTIFICATIONS (PART 1):\n<candidate_certifications_part_1>\n{c_str1}\n</candidate_certifications_part_1>")

        c_str2 = json.dumps({"certifications_part_2": c_part2}, ensure_ascii=False, indent=2)
        chunk_r3 = ("R3", f"### CANDIDATE CERTIFICATIONS (PART 2):\n<candidate_certifications_part_2>\n{c_str2}\n</candidate_certifications_part_2>")

        chunk_ins = ("INS", (
            f"### INSTRUCTIONS:\n"
            f"<evaluation_instructions>\n"
            f"Evaluate candidate academic degrees and certifications against the job requirement criteria "
            f"for the '{self.category_label}' dimension following your system instructions. Return exclusively a valid JSON object.\n"
            f"</evaluation_instructions>"
        ))

        return [chunk_c, chunk_r1, chunk_r2, chunk_r3, chunk_ins]

    def render_prompt(
        self,
        exp_type: str,
        perm_meta: Any,
        criteria_list: List[str],
        candidate_data: Dict[str, Any],
        atomic_chunks: List[Tuple[str, str]],
        model_name: str
    ) -> Tuple[str, str]:
        category_name = self.category_label

        if exp_type == "Baseline":
            user_prompt = get_category_evaluation_prompt(
                category_name,
                model_name,
                criteria_list,
                candidate_data
            )
            return user_prompt, "Criteria -> Candidate -> Instructions"

        elif exp_type == "Macro_Permutation":
            order_code = perm_meta
            user_prompt = self.render_macro_permutation(
                category_name,
                criteria_list,
                candidate_data,
                order_code
            )
            return user_prompt, order_code

        elif exp_type == "Criteria_Permutation":
            perm_tuple = perm_meta
            reordered_criteria = [criteria_list[i] for i in perm_tuple]
            user_prompt = get_category_evaluation_prompt(
                category_name,
                model_name,
                reordered_criteria,
                candidate_data
            )
            return user_prompt, f"Perm_{list(perm_tuple)}"

        elif exp_type == "Candidate_Certifications_Order":
            perm_tuple = perm_meta
            snip_copy = copy.deepcopy(candidate_data)
            certs = snip_copy.get("certifications", [])
            if isinstance(certs, list) and len(certs) == len(perm_tuple):
                snip_copy["certifications"] = [certs[i] for i in perm_tuple]

            user_prompt = get_category_evaluation_prompt(
                category_name,
                model_name,
                criteria_list,
                snip_copy
            )
            return user_prompt, f"Cert_Perm_{list(perm_tuple)}"

        elif exp_type == "Candidate_Key_Order":
            ordered_keys = perm_meta
            reordered_dict = {k: candidate_data[k] for k in ordered_keys if k in candidate_data}
            user_prompt = get_category_evaluation_prompt(
                category_name,
                model_name,
                criteria_list,
                reordered_dict
            )
            return user_prompt, f"KeyOrder_{list(ordered_keys)}"

        elif exp_type == "Spatial_Interleave_5Chunk":
            perm_indices = perm_meta
            chunks = self._get_5_spatial_chunks(criteria_list, candidate_data)
            reordered_chunks = [chunks[i] for i in perm_indices]
            order_repr = " -> ".join([c[0] for c in reordered_chunks])
            prompt_text = f"Evaluating dimension: '{category_name}'\n\n" + "\n\n".join([c[1] for c in reordered_chunks])
            return prompt_text, order_repr

        elif exp_type == "Atomic_Interleave":
            perm_indices = perm_meta
            reordered = [atomic_chunks[i] for i in perm_indices]
            order_repr = " -> ".join([c[0] for c in reordered])
            prompt_text = (
                f"Evaluating dimension: '{category_name}'\n\n"
                f"### DISTRIBUTED JOB CRITERIA & CANDIDATE EDUCATION CHUNKS:\n" +
                "\n\n".join([c[1] for c in reordered])
            )
            return prompt_text, order_repr

        else:
            user_prompt = get_category_evaluation_prompt(
                category_name,
                model_name,
                criteria_list,
                candidate_data
            )
            return user_prompt, "Default"
