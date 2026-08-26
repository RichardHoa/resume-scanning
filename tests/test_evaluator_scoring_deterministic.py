import os
import sys
import unittest

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from src.pipelines.evaluator_utils import validate_category_evaluation
from src.prompts.evaluator_prompts import get_evaluator_system_prompt


class TestEvaluatorScoringDeterministic(unittest.TestCase):

    def test_streamlined_schema_with_automatic_score_and_quote_aggregation(self):
        # LLM outputs NO root score and NO root evidence_quotes
        parsed = {
            "criteria_evaluations": [
                {"criterion": "Payroll calculation", "verdict": "STRONG_EVIDENCE", "evidence_quote": "5 years payroll calculation for 500 staff"},
                {"criterion": "PIT tax compliance", "verdict": "STRONG_EVIDENCE", "evidence_quote": "Managed annual PIT finalization"},
                {"criterion": "Social insurance (BHXH)", "verdict": "STRONG_EVIDENCE", "evidence_quote": "Full BHXH reporting"},
                {"criterion": "Labor law compliance", "verdict": "PARTIAL_EVIDENCE", "evidence_quote": "Assisted HR Manager with labor disputes"},
                {"criterion": "3P Salary Scheme", "verdict": "NO_EVIDENCE", "evidence_quote": None}
            ],
            "strengths": ["Strong payroll depth", "Tax compliance"],
            "gaps": ["No independent 3P salary scheme design experience"],
            "reasoning_summary": "Ứng viên có kinh nghiệm vận hành C&B vững vàng, đáp ứng 3.5/5 tiêu chí (70%)."
        }
        result = validate_category_evaluation(parsed)
        self.assertIsNotNone(result)
        # Score computed: (1 + 1 + 1 + 0.5 + 0) / 5 = 3.5/5 -> 70
        self.assertEqual(result["score"], 70)
        # Quotes automatically aggregated from criteria_evaluations
        self.assertEqual(len(result["evidence_quotes"]), 4)
        self.assertIn("5 years payroll calculation for 500 staff", result["evidence_quotes"])
        self.assertEqual(len(result["criteria_evaluations"]), 5)

    def test_deterministic_scoring_full_match(self):
        parsed = {
            "criteria_evaluations": [
                {"criterion": "Payroll calculation", "verdict": "STRONG_EVIDENCE", "evidence_quote": "5 years payroll"},
                {"criterion": "PIT tax compliance", "verdict": "STRONG_EVIDENCE", "evidence_quote": "Managed PIT filings"},
                {"criterion": "Social insurance (BHXH)", "verdict": "STRONG_EVIDENCE", "evidence_quote": "Full BHXH reporting"},
                {"criterion": "Labor law compliance", "verdict": "STRONG_EVIDENCE", "evidence_quote": "Resolved disputes"}
            ],
            "strengths": ["Strong payroll depth", "Full tax compliance"],
            "gaps": [],
            "reasoning_summary": "Ứng viên đáp ứng đầy đủ tất cả các tiêu chí yêu cầu."
        }
        result = validate_category_evaluation(parsed)
        self.assertIsNotNone(result)
        self.assertEqual(result["score"], 100)
        self.assertEqual(len(result["criteria_evaluations"]), 4)
        self.assertEqual(result["criteria_evaluations"][0]["score"], 1.0)
        self.assertEqual(len(result["evidence_quotes"]), 4)

    def test_legacy_fallback_without_criteria_evaluations(self):
        parsed = {
            "score": 85,
            "strengths": ["Strong domain knowledge"],
            "gaps": ["Minor tool gap"],
            "evidence_quotes": ["Direct quote"],
            "reasoning_summary": "Ứng viên có năng lực tốt."
        }
        result = validate_category_evaluation(parsed)
        self.assertIsNotNone(result)
        self.assertEqual(result["score"], 85)
        self.assertNotIn("criteria_evaluations", result)

    def test_evaluator_system_prompt_contains_uniform_directives_and_no_benchmark(self):
        prompt_vi = get_evaluator_system_prompt("vietnamese")
        self.assertIn("STRICT LITERAL ADHERENCE", prompt_vi)
        self.assertIn("UNBIASED ATOMIC VERIFICATION", prompt_vi)
        self.assertIn("STRONG_EVIDENCE", prompt_vi)
        self.assertIn("PARTIAL_EVIDENCE", prompt_vi)
        self.assertIn("NO_EVIDENCE", prompt_vi)
        self.assertIn("criteria_evaluations", prompt_vi)
        # Verify scoring benchmark was removed from LLM prompt
        self.assertNotIn("SCORING BENCHMARK", prompt_vi)
        self.assertNotIn("quantifiable achievements", prompt_vi)

        prompt_en = get_evaluator_system_prompt("english")
        self.assertIn("STRICT LITERAL ADHERENCE", prompt_en)
        self.assertIn("UNBIASED ATOMIC VERIFICATION", prompt_en)
        self.assertNotIn("SCORING BENCHMARK", prompt_en)
        self.assertNotIn("quantifiable achievements", prompt_en)


    def test_placeholder_quotes_are_filtered(self):
        parsed = {
            "criteria_evaluations": [
                {"criterion": "Python", "verdict": "STRONG_EVIDENCE", "evidence_quote": "5 years Python development"},
                {"criterion": "FastAPI", "verdict": "PARTIAL_EVIDENCE", "evidence_quote": "None"},
                {"criterion": "Kubernetes", "verdict": "NO_EVIDENCE", "evidence_quote": "N/A"},
                {"criterion": "PostgreSQL", "verdict": "NO_EVIDENCE", "evidence_quote": "không có"}
            ],
            "strengths": ["Python expertise"],
            "gaps": ["Lacks K8s and SQL depth"],
            "reasoning_summary": "Phù hợp một phần."
        }
        result = validate_category_evaluation(parsed)
        self.assertIsNotNone(result)
        # Only 1 valid quote should remain, "None", "N/A", "không có" filtered out
        self.assertEqual(len(result["evidence_quotes"]), 1)
        self.assertEqual(result["evidence_quotes"], ["5 years Python development"])
        # Criteria score: (1.0 + 0.5 + 0.0 + 0.0) / 4 = 1.5 / 4 = 37.5 -> 38
        self.assertEqual(result["score"], 38)
        self.assertIsNone(result["criteria_evaluations"][1]["evidence_quote"])
        self.assertIsNone(result["criteria_evaluations"][2]["evidence_quote"])
        self.assertIsNone(result["criteria_evaluations"][3]["evidence_quote"])


if __name__ == "__main__":
    unittest.main()

