"""
Technical Skills & Competencies Bias & Positional Sensitivity Experiment Builder.
Permutes the raw keys production judges the Category on: skills, work_experience, projects, languages.
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


class TechnicalSkillsBiasBuilder(BaseCategoryBiasBuilder):
    """
    Bias & Positional Order Sensitivity Builder for Technical Skills & Competencies.
    """

    @property
    def category_key(self) -> str:
        return "technical_skills"

    @property
    def category_label(self) -> str:
        return "Technical Skills & Competencies"

    def build_atomic_chunks(
        self,
        criteria_list: List[str],
        candidate_data: Dict[str, Any]
    ) -> List[Tuple[str, str]]:
        atomic_chunks: List[Tuple[str, str]] = []

        # Atomic Criteria Chunks
        for idx, crit in enumerate(criteria_list, start=1):
            clean_crit = self.sanitize_xml(crit, "job_criterion")
            atomic_chunks.append((
                f"Crit_{idx}",
                f"<job_criterion id=\"{idx}\">\n- {clean_crit}\n</job_criterion>"
            ))

        # The skills section, one chunk
        if candidate_data.get("skills"):
            skills_str = self.sanitize_xml(json.dumps(candidate_data["skills"], ensure_ascii=False, indent=2), "candidate_skills")
            atomic_chunks.append(("Skills", f"<candidate_skills>\n{skills_str}\n</candidate_skills>"))

        # Atomic Candidate Job Chunks: work_experience is split entry by entry
        work_exp = candidate_data.get("work_experience", [])
        if isinstance(work_exp, list):
            for idx, job in enumerate(work_exp, start=1):
                clean_job = self.sanitize_xml(json.dumps(job, ensure_ascii=False, indent=2), "candidate_job")
                atomic_chunks.append((
                    f"Job_{idx}",
                    f"<candidate_job id=\"{idx}\">\n{clean_job}\n</candidate_job>"
                ))

        if candidate_data.get("projects"):
            proj_str = self.sanitize_xml(json.dumps(candidate_data["projects"], ensure_ascii=False, indent=2), "candidate_projects")
            atomic_chunks.append(("Projects", f"<candidate_projects>\n{proj_str}\n</candidate_projects>"))

        if candidate_data.get("languages"):
            lang_str = json.dumps(candidate_data["languages"], ensure_ascii=False)
            atomic_chunks.append(("Lang", f"<candidate_languages>\n{lang_str}\n</candidate_languages>"))

        # Instruction Chunk
        atomic_chunks.append((
            "INS",
            f"<evaluation_instructions>\n"
            f"Evaluate all candidate skills/items against all job criteria items listed above "
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

        # Group 1: 6 Macro Section Permutations (All 3! = 6 combinations)
        for idx, (order_code, _) in enumerate(MACRO_PERMUTATION_ORDERS, start=1):
            experiments.append(("Macro_Permutation", f"macro_perm_{idx:02d}_{order_code}", order_code))

        # Group 2: Criteria Intra-Permutations (N! combinations, e.g. 7! = 5,040)
        num_criteria = len(criteria_list)
        if num_criteria > 1:
            crit_all_perms = self.capped_permutations(range(num_criteria), max_per_kind)
            for idx, perm in enumerate(crit_all_perms, start=1):
                experiments.append(("Criteria_Permutation", f"crit_perm_{idx:04d}", perm))

        # Group 3: Candidate Job Intra-Permutations (M! combinations, e.g. 5! = 120 for 5 jobs)
        job_perms = self.capped_permutations(range(self.list_length(candidate_data, "work_experience")), max_per_kind)
        for idx, perm in enumerate(job_perms, start=1):
            experiments.append(("Candidate_Jobs_Order", f"cand_jobs_perm_{idx:03d}", perm))

        # Group 4: Balanced Interleaved Placement (5! = 120 combinations)
        balanced_all_perms = self.capped_permutations(range(5), max_per_kind)
        for idx, perm in enumerate(balanced_all_perms, start=1):
            experiments.append(("Balanced_Interleave", f"bal_perm_{idx:03d}", perm))

        # Group 5: Atomic Item-Level Interleaving (Sampled combinations)
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
            order_meta = "Criteria -> Candidate -> Instructions"
            return user_prompt, order_meta

        elif exp_type == "Macro_Permutation":
            order_code = perm_meta
            user_prompt = self.render_macro_permutation(
                category_name,
                criteria_list,
                candidate_data,
                order_code
            )
            order_meta = order_code
            return user_prompt, order_meta

        elif exp_type == "Criteria_Permutation":
            perm_tuple = perm_meta
            reordered_criteria = [criteria_list[i] for i in perm_tuple]
            user_prompt = get_category_evaluation_prompt(
                category_name,
                model_name,
                reordered_criteria,
                candidate_data
            )
            order_meta = f"Perm_{list(perm_tuple)}"
            return user_prompt, order_meta

        elif exp_type == "Candidate_Jobs_Order":
            perm_tuple = perm_meta
            snip_copy = self.permute_list(candidate_data, "work_experience", perm_tuple)
            user_prompt = get_category_evaluation_prompt(
                category_name,
                model_name,
                criteria_list,
                snip_copy
            )
            order_meta = f"Jobs_Perm_{list(perm_tuple)}"
            return user_prompt, order_meta

        elif exp_type == "Balanced_Interleave":
            perm_indices = perm_meta
            # 1. Split Criteria into 2 halves
            mid_c = max(1, len(criteria_list) // 2)
            crit_str1 = "\n".join([f"- {c}" for c in criteria_list[:mid_c]])
            crit_str2 = "\n".join([f"- {c}" for c in criteria_list[mid_c:]])

            # 2. Split the candidate slice into 2 halves at the middle of work_experience: skills and the first jobs,
            # then the later jobs, projects and languages; each key keeps its raw name
            jobs_part1, jobs_part2 = self.split_into(candidate_data.get("work_experience", []), 2)
            snip_part1: Dict[str, Any] = {}
            snip_part2: Dict[str, Any] = {}
            if "skills" in candidate_data:
                snip_part1["skills"] = candidate_data["skills"]
            if "work_experience" in candidate_data:
                snip_part1["work_experience"] = jobs_part1
                snip_part2["work_experience"] = jobs_part2
            for key in ("projects", "languages"):
                if key in candidate_data:
                    snip_part2[key] = candidate_data[key]

            snip_str1 = json.dumps(snip_part1, ensure_ascii=False, indent=2)
            snip_str2 = json.dumps(snip_part2, ensure_ascii=False, indent=2)

            chunks = [
                ("C1", "### JOB REQUIREMENT CRITERIA (PART 1):\n<job_criteria_part_1>\n" + crit_str1 + "\n</job_criteria_part_1>"),
                ("C2", "### JOB REQUIREMENT CRITERIA (PART 2):\n<job_criteria_part_2>\n" + crit_str2 + "\n</job_criteria_part_2>"),
                ("R1", "### CANDIDATE RESUME SECTION (PART 1):\n<candidate_resume_part_1>\n" + snip_str1 + "\n</candidate_resume_part_1>"),
                ("R2", "### CANDIDATE RESUME SECTION (PART 2):\n<candidate_resume_part_2>\n" + snip_str2 + "\n</candidate_resume_part_2>"),
                ("INS", (
                    f"### INSTRUCTIONS:\n"
                    f"<evaluation_instructions>\n"
                    f"Evaluate all candidate resume parts against all job requirement criteria parts "
                    f"for the '{category_name}' dimension following your system instructions. Return exclusively a valid JSON object.\n"
                    f"</evaluation_instructions>"
                ))
            ]

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
                f"### DISTRIBUTED JOB CRITERIA & CANDIDATE DATA CHUNKS:\n" +
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
