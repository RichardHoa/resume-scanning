"""
Work Experience & Project Relevance Bias & Positional Sensitivity Experiment Builder.
Permutes the raw keys production judges the Category on: work_experience, projects.
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


class WorkExperienceBiasBuilder(BaseCategoryBiasBuilder):
    """
    Bias & Positional Order Sensitivity Builder for Work Experience & Project Relevance.
    """

    @property
    def category_key(self) -> str:
        return "work_experience"

    @property
    def category_label(self) -> str:
        return "Work Experience & Project Relevance"

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

        # 2. Candidate Job Entries
        work_exp = candidate_data.get("work_experience", [])
        if isinstance(work_exp, list):
            for idx, job in enumerate(work_exp, start=1):
                job_str = json.dumps(job, ensure_ascii=False, indent=2)
                clean_job = self.sanitize_xml(job_str, "candidate_job")
                atomic_chunks.append((
                    f"Job_{idx}",
                    f"<candidate_job id=\"{idx}\">\n{clean_job}\n</candidate_job>"
                ))

        # 3. Candidate Projects (if present)
        projects = candidate_data.get("projects", [])
        if isinstance(projects, list) and projects:
            for idx, proj in enumerate(projects, start=1):
                proj_str = json.dumps(proj, ensure_ascii=False, indent=2)
                clean_proj = self.sanitize_xml(proj_str, "candidate_project")
                atomic_chunks.append((
                    f"Proj_{idx}",
                    f"<candidate_project id=\"{idx}\">\n{clean_proj}\n</candidate_project>"
                ))

        # 4. Instructions Chunk
        atomic_chunks.append((
            "INS",
            f"<evaluation_instructions>\n"
            f"Evaluate the candidate employment history, role relevance, and projects against the job criteria "
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

        # Group 2: Criteria Intra-Permutations (N! combinations if multiple criteria)
        num_criteria = len(criteria_list)
        if num_criteria > 1:
            crit_all_perms = self.capped_permutations(range(num_criteria), max_per_kind)
            for idx, perm in enumerate(crit_all_perms, start=1):
                experiments.append(("Criteria_Permutation", f"crit_perm_{idx:04d}", perm))

        # Group 3: Candidate Intra-Permutations
        # 3a. Jobs Shuffled (5! = 120 runs for 5 jobs)
        job_perms = self.capped_permutations(range(self.list_length(candidate_data, "work_experience")), max_per_kind)
        for idx, perm in enumerate(job_perms, start=1):
            experiments.append(("Candidate_Jobs_Order", f"cand_jobs_perm_{idx:03d}", perm))

        # 3b. Projects Shuffled (5! = 120 runs for 5 projects)
        project_perms = self.capped_permutations(range(self.list_length(candidate_data, "projects")), max_per_kind)
        for idx, perm in enumerate(project_perms, start=1):
            experiments.append(("Candidate_Projects_Order", f"cand_projects_perm_{idx:03d}", perm))

        # 3c. Section Keys Reordering (2! = 2 runs: work_experience vs projects)
        valid_keys = [k for k in ["work_experience", "projects"] if k in candidate_data]
        if len(valid_keys) >= 2:
            key_perms = self.capped_permutations(valid_keys, max_per_kind)
            for idx, perm in enumerate(key_perms, start=1):
                experiments.append(("Candidate_Key_Order", f"cand_key_order_{idx:02d}", perm))

        # Group 4: 7-Chunk Spatial Interleaving (7! = 5,040 runs)
        # C + R1..R5 (the jobs in 5 parts) + R6 (projects) = 7 shuffled chunks, INS fixed at the end
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
    ) -> Tuple[List[Tuple[str, str]], Tuple[str, str]]:
        crit_str = "\n".join([f"- {c}" for c in criteria_list])
        chunk_c = ("C", f"### JOB REQUIREMENT CRITERIA:\n<job_criteria>\n{crit_str}\n</job_criteria>")

        # R1..R5: the Employment Roles in 5 parts, in order, so no Shuffle Kind drops a job
        r_chunks: List[Tuple[str, str]] = []
        for i, group in enumerate(self.split_into(candidate_data.get("work_experience", []), 5)):
            idx = i + 1
            job_str = json.dumps(group, ensure_ascii=False, indent=2)
            r_chunks.append((
                f"R{idx}",
                f"### CANDIDATE EMPLOYMENT ROLE (PART {idx}):\n<candidate_experience_part_{idx}>\n{job_str}\n</candidate_experience_part_{idx}>"
            ))

        # R6: Projects; empty when the slice has none, so no Shuffle Kind adds content the Baseline lacks
        chunk_r6 = ("R6", "")
        if "projects" in candidate_data:
            projects_str = json.dumps({"projects": candidate_data["projects"]}, ensure_ascii=False, indent=2)
            chunk_r6 = ("R6", f"### CANDIDATE PROJECTS:\n<candidate_projects>\n{projects_str}\n</candidate_projects>")

        # INS: Instruction block
        chunk_ins = ("INS", (
            f"### INSTRUCTIONS:\n"
            f"<evaluation_instructions>\n"
            f"Evaluate all candidate experience roles and projects against the job criteria "
            f"for the '{self.category_label}' dimension following your system instructions. Return exclusively a valid JSON object.\n"
            f"</evaluation_instructions>"
        ))

        data_chunks = [chunk_c, r_chunks[0], r_chunks[1], r_chunks[2], r_chunks[3], r_chunks[4], chunk_r6]
        return data_chunks, chunk_ins

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

        elif exp_type == "Candidate_Jobs_Order":
            perm_tuple = perm_meta
            snip_copy = self.permute_list(candidate_data, "work_experience", perm_tuple)
            user_prompt = get_category_evaluation_prompt(
                category_name,
                model_name,
                criteria_list,
                snip_copy
            )
            return user_prompt, f"Jobs_Perm_{list(perm_tuple)}"

        elif exp_type == "Candidate_Projects_Order":
            perm_tuple = perm_meta
            snip_copy = self.permute_list(candidate_data, "projects", perm_tuple)
            user_prompt = get_category_evaluation_prompt(
                category_name,
                model_name,
                criteria_list,
                snip_copy
            )
            return user_prompt, f"Projects_Perm_{list(perm_tuple)}"

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
            data_chunks, chunk_ins = self._get_7_spatial_chunks(criteria_list, candidate_data)
            reordered_chunks = [data_chunks[i] for i in perm_indices]
            order_repr = " -> ".join([c[0] for c in reordered_chunks]) + " -> INS"
            prompt_text = (
                f"Evaluating dimension: '{category_name}'\n\n" +
                "\n\n".join([c[1] for c in reordered_chunks if c[1]]) +
                "\n\n" + chunk_ins[1]
            )
            return prompt_text, order_repr

        elif exp_type == "Atomic_Interleave":
            perm_indices = perm_meta
            reordered = [atomic_chunks[i] for i in perm_indices]
            order_repr = " -> ".join([c[0] for c in reordered])
            prompt_text = (
                f"Evaluating dimension: '{category_name}'\n\n"
                f"### DISTRIBUTED JOB CRITERIA & CANDIDATE EXPERIENCE CHUNKS:\n" +
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
