"""
Work Experience & Project Relevance Bias & Positional Sensitivity Experiment Builder.
Corresponds to Part 4 of docs/bias_detection_plan.md (5,589 unique iterations).
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

    def extract_candidate_data(self, resume_dict: Dict[str, Any]) -> Dict[str, Any]:
        return {
            "work_experience": resume_dict.get("work_experience", []),
            "projects": resume_dict.get("projects", []),
            "skills_and_specialties": resume_dict.get("skills_and_specialties", [])
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

        # 3. Candidate Skills Highlights
        skills = candidate_data.get("skills_and_specialties", [])
        if isinstance(skills, list):
            for idx, skill in enumerate(skills, start=1):
                clean_skill = self.sanitize_xml(str(skill), "candidate_skill")
                atomic_chunks.append((
                    f"Skill_{idx}",
                    f"<candidate_skill id=\"{idx}\">\n{clean_skill}\n</candidate_skill>"
                ))

        # 4. Candidate Projects (if present)
        projects = candidate_data.get("projects", [])
        if isinstance(projects, list) and projects:
            for idx, proj in enumerate(projects, start=1):
                proj_str = json.dumps(proj, ensure_ascii=False, indent=2)
                clean_proj = self.sanitize_xml(proj_str, "candidate_project")
                atomic_chunks.append((
                    f"Proj_{idx}",
                    f"<candidate_project id=\"{idx}\">\n{clean_proj}\n</candidate_project>"
                ))

        # 5. Instructions Chunk
        atomic_chunks.append((
            "INS",
            f"<evaluation_instructions>\n"
            f"Evaluate the candidate employment history, role relevance, and skill application against the job criteria "
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
        # 3a. 5 Jobs Shuffled (5! = 120 runs)
        work_exp = candidate_data.get("work_experience", [])
        num_jobs = len(work_exp) if isinstance(work_exp, list) and work_exp else 1
        job_perms = list(itertools.permutations(range(num_jobs)))
        for idx, perm in enumerate(job_perms, start=1):
            experiments.append(("Candidate_Jobs_Order", f"cand_jobs_perm_{idx:03d}", perm))

        # 3b. 5 Skills Shuffled (5! = 120 runs)
        skills = candidate_data.get("skills_and_specialties", [])
        num_skills = len(skills) if isinstance(skills, list) and skills else 1
        skill_perms = list(itertools.permutations(range(num_skills)))
        for idx, perm in enumerate(skill_perms, start=1):
            experiments.append(("Candidate_Skills_Order", f"cand_skills_perm_{idx:03d}", perm))

        # 3c. Section Keys Reordering (2! = 2 runs: work_experience vs skills_and_specialties)
        valid_keys = [k for k in ["work_experience", "skills_and_specialties"] if candidate_data.get(k)]
        if len(valid_keys) >= 2:
            key_perms = list(itertools.permutations(valid_keys))
            for idx, perm in enumerate(key_perms, start=1):
                experiments.append(("Candidate_Key_Order", f"cand_key_order_{idx:02d}", perm))

        # Group 4: 7-Chunk Spatial Interleaving (7! = 5,040 runs)
        # C + R1..R5 (5 jobs) + R6 (skills) + INS = 7 discrete chunks (or with fixed INS)
        spatial_perms = list(itertools.permutations(range(7)))
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

        # R1..R5: 5 Employment Roles
        work_exp = candidate_data.get("work_experience", [])
        if not isinstance(work_exp, list) or not work_exp:
            work_exp = [{}]

        r_chunks: List[Tuple[str, str]] = []
        num_jobs = len(work_exp)
        for i in range(5):
            idx = i + 1
            job_item = work_exp[i] if i < num_jobs else {}
            job_str = json.dumps(job_item, ensure_ascii=False, indent=2)
            r_chunks.append((
                f"R{idx}",
                f"### CANDIDATE EMPLOYMENT ROLE (PART {idx}):\n<candidate_experience_part_{idx}>\n{job_str}\n</candidate_experience_part_{idx}>"
            ))

        # R6: Skills Highlights (or Project data)
        skills = candidate_data.get("skills_and_specialties", [])
        skills_str = json.dumps({"skills_and_specialties": skills}, ensure_ascii=False, indent=2)
        chunk_r6 = ("R6", f"### CANDIDATE CORE COMPETENCIES:\n<candidate_competencies>\n{skills_str}\n</candidate_competencies>")

        # INS: Instruction block
        chunk_ins = ("INS", (
            f"### INSTRUCTIONS:\n"
            f"<evaluation_instructions>\n"
            f"Evaluate all candidate experience roles and competencies against the job criteria "
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
            snip_copy = copy.deepcopy(candidate_data)
            jobs = snip_copy.get("work_experience", [])
            if isinstance(jobs, list) and len(jobs) == len(perm_tuple):
                snip_copy["work_experience"] = [jobs[i] for i in perm_tuple]

            user_prompt = get_category_evaluation_prompt(
                category_name,
                model_name,
                criteria_list,
                snip_copy
            )
            return user_prompt, f"Jobs_Perm_{list(perm_tuple)}"

        elif exp_type == "Candidate_Skills_Order":
            perm_tuple = perm_meta
            snip_copy = copy.deepcopy(candidate_data)
            skills = snip_copy.get("skills_and_specialties", [])
            if isinstance(skills, list) and len(skills) == len(perm_tuple):
                snip_copy["skills_and_specialties"] = [skills[i] for i in perm_tuple]

            user_prompt = get_category_evaluation_prompt(
                category_name,
                model_name,
                criteria_list,
                snip_copy
            )
            return user_prompt, f"Skills_Perm_{list(perm_tuple)}"

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
                "\n\n".join([c[1] for c in reordered_chunks]) +
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
