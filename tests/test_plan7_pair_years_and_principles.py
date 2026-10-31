import unittest
from src.agents.financial_numbers import mask_verified_comparisons
from src.agents.literal_numbers import mask_evidence_years
from src.agents.interpretation import decisions_for
from src.agents.knowledge import MECHANISM_CONCEPTS
from src.models import AppError

EVIDENCE = {"M": {"kind": "annual_comparison", "status": "ok", "item": "operating_margin", "years": [2024, 2025],
                  "previous": "10.88", "current": "13.07", "delta_pp": "2.19", "change_pct": None,
                  "currency": "KRW", "fs_div": "CFS", "verified_sentence": "x"}}


class Plan7PairYearLabelTests(unittest.TestCase):
    def test_year_labels_inside_pair_must_match_evidence_years(self):
        ok = "영업이익률은 2024년 10.88%에서 2025년 13.07%로 2.19%p 상승했습니다."
        self.assertNotRegex(mask_verified_comparisons(ok, EVIDENCE), r"\d")
        for bad in ("영업이익률은 2023년 10.88%에서 2025년 13.07%로 2.19%p 상승했습니다.",
                    "영업이익률은 2024년 10.88%에서 2026년 13.07%로 2.19%p 상승했습니다."):
            with self.assertRaises(AppError):
                mask_verified_comparisons(bad, EVIDENCE)

    def test_result_label_year_pass_skips_rate_sentences(self):
        evidence = {"R": {"kind": "annual_comparison", "years": [2024, 2025], "change_pct": "20.00"}}
        self.assertIn("2024", mask_evidence_years("2024년 매출은 15% 증가했습니다.", evidence))
        self.assertNotIn("2025", mask_evidence_years("2025년 확정 실적 기준 매출은 규모가 큽니다.", evidence))


class Plan7PrincipleTests(unittest.TestCase):
    def test_principle_concepts_exist_and_hold_no_company_facts(self):
        self.assertIn("영업일과 매출", MECHANISM_CONCEPTS)
        self.assertFalse(any(ch.isdigit() for text in MECHANISM_CONCEPTS.values() for ch in text))


if __name__ == "__main__":
    unittest.main()
