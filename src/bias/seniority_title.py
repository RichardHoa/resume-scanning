"""
Seniority & Title Bias & Positional Sensitivity Experiment Builder.
Permutes the raw keys production judges the Category on: position_applied, self_evaluation, work_experience.
"""
import json
import math
import random
from typing import Dict, List, Any, Optional, Tuple, Set

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


class SeniorityTitleBiasBuilder(BaseCategoryBiasBuilder):
    """
    Bias & Positional Order Sensitivity Builder for Position & Seniority Match.
    """

    @property
    def category_key(self) -> str:
        return "seniority_title"

    @property
    def category_label(self) -> str:
        return "Position & Seniority Match"

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

        # 2. Position Applied
        if "position_applied" in candidate_data:
            pos_str = json.dumps(candidate_data["position_applied"], ensure_ascii=False)
            atomic_chunks.append((
                "Applied_Title",
                f"<candidate_target_position>\n{pos_str}\n</candidate_target_position>"
            ))

        # 3. Self Evaluation
        self_eval = candidate_data.get("self_evaluation", "")
        if self_eval:
            clean_eval = self.sanitize_xml(str(self_eval), "candidate_self_evaluation")
            atomic_chunks.append((
                "Self_Eval",
                f"<candidate_self_evaluation>\n{clean_eval}\n</candidate_self_evaluation>"
            ))

        # 4. Work Experience Entries
        details_list = candidate_data.get("work_experience", [])
        if isinstance(details_list, list):
            for idx, item in enumerate(details_list, start=1):
                item_str = json.dumps(item, ensure_ascii=False, indent=2)
                clean_item = self.sanitize_xml(item_str, "work_experience_entry")
                atomic_chunks.append((
                    f"Detail_{idx}",
                    f"<work_experience_entry id=\"{idx}\">\n{clean_item}\n</work_experience_entry>"
                ))

        # 5. Evaluation Instructions
        atomic_chunks.append((
            "INS",
            f"<evaluation_instructions>\n"
            f"Evaluate the candidate seniority, position alignment, and career progression against the job criteria "
            f"for the '{self.category_label}' dimension following your system instructions. Return exclusively a valid JSON object.\n"
            f"</evaluation_instructions>"
        ))

        return atomic_chunks

    def build_experiments(
        self,
        criteria_list: List[str],
        candidate_data: Dict[str, Any],
        seed: int = 42,
        atomic_sample_size: int = 300,
        max_per_kind: Optional[int] = None
    ) -> List[Tuple[str, str, Any]]:
        experiments: List[Tuple[str, str, Any]] = [
            ("Baseline", "00_baseline", "baseline")
        ]

        # Group 1: Macro Permutations (3! = 6 runs)
        for idx, (order_code, _) in enumerate(MACRO_PERMUTATION_ORDERS, start=1):
            experiments.append(("Macro_Permutation", f"macro_perm_{idx:02d}_{order_code}", order_code))

        # Group 2: Criteria Intra-Permutations (N! combinations, e.g. 1! = 1 if single criterion)
        num_criteria = len(criteria_list)
        if num_criteria > 1:
            crit_all_perms = self.capped_permutations(range(num_criteria), max_per_kind)
            for idx, perm in enumerate(crit_all_perms, start=1):
                experiments.append(("Criteria_Permutation", f"crit_perm_{idx:04d}", perm))

        # Group 3: Candidate Intra-Permutations
        # 3a. Job Chronology Permutations (5! = 120 runs for 5 jobs)
        job_perms = self.capped_permutations(range(self.list_length(candidate_data, "work_experience")), max_per_kind)
        for idx, perm in enumerate(job_perms, start=1):
            experiments.append(("Candidate_Job_Chronology", f"cand_chrono_{idx:03d}", perm))

        # 3b. Top-Level Section Key Permutations (3! = 6 runs when position_applied, self_evaluation and
        # work_experience are all present)
        top_keys = list(candidate_data.keys())
        if len(top_keys) >= 2:
            key_perms = self.capped_permutations(top_keys, max_per_kind)
            for idx, perm in enumerate(key_perms, start=1):
                experiments.append(("Candidate_Key_Order", f"cand_key_order_{idx:02d}", perm))

        # Group 4: 7-Chunk Spatial Interleaving (7! = 5,040 runs)
        # C + R1..R5 + INS = 7 discrete blocks
        spatial_perms = self.capped_permutations(range(7), max_per_kind)
        for idx, perm in enumerate(spatial_perms, start=1):
            experiments.append(("Spatial_Interleave_7Chunk", f"spat_perm_{idx:04d}", perm))

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

    def _get_7_spatial_chunks(
        self,
        criteria_list: List[str],
        candidate_data: Dict[str, Any]
    ) -> List[Tuple[str, str]]:
        """Constructs 7 discrete chunks: C, R1..R5, INS."""
        crit_str = "\n".join([f"- {c}" for c in criteria_list])
        chunk_c = ("C", f"### JOB REQUIREMENT CRITERIA:\n<job_criteria>\n{crit_str}\n</job_criteria>")

        pos_applied = candidate_data.get("position_applied", {})
        self_eval = candidate_data.get("self_evaluation", "")
        # Every job lands in one of the 5 parts, in order, so no Shuffle Kind drops a job
        job_groups = self.split_into(candidate_data.get("work_experience", []), 5)

        r_chunks: List[Tuple[str, str]] = []
        for i, group in enumerate(job_groups):
            idx = i + 1
            job_dict: Dict[str, Any] = {"experience_items": group}

            if i == 0 and pos_applied:
                job_dict["target_position_applied"] = pos_applied
            if i == 4 and self_eval:
                job_dict["candidate_self_evaluation"] = self_eval

            job_str = json.dumps(job_dict, ensure_ascii=False, indent=2)
            r_chunks.append((
                f"R{idx}",
                f"### CANDIDATE CAREER BLOCK (PART {idx}):\n<candidate_career_part_{idx}>\n{job_str}\n</candidate_career_part_{idx}>"
            ))

        chunk_ins = ("INS", (
            f"### INSTRUCTIONS:\n"
            f"<evaluation_instructions>\n"
            f"Evaluate all candidate career blocks against the job criteria "
            f"for the '{self.category_label}' dimension following your system instructions. Return exclusively a valid JSON object.\n"
            f"</evaluation_instructions>"
        ))

        return [chunk_c, r_chunks[0], r_chunks[1], r_chunks[2], r_chunks[3], r_chunks[4], chunk_ins]

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

        elif exp_type == "Candidate_Job_Chronology":
            perm_tuple = perm_meta
            snip_copy = self.permute_list(candidate_data, "work_experience", perm_tuple)
            user_prompt = get_category_evaluation_prompt(
                category_name,
                model_name,
                criteria_list,
                snip_copy
            )
            return user_prompt, f"Chrono_Perm_{list(perm_tuple)}"

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

        elif exp_type == "Spatial_Interleave_7Chunk":
            perm_indices = perm_meta
            chunks = self._get_7_spatial_chunks(criteria_list, candidate_data)
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
                f"### DISTRIBUTED JOB CRITERIA & CANDIDATE SENIORITY CHUNKS:\n" +
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
