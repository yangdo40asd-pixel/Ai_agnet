import unittest
from src.agents.chat import validate_answer
from src.agents.literal_numbers import mask_question_quarters
from src.agents.request import looks_like_clause, scope_hits

CMP = {"CMP": {"kind": "annual_comparison", "item": "revenue", "years": [2024, 2025], "change_pct": "46.76285", "change_state": "증가",
               "text": "매출액: 2024년 661,929.6억원 → 2025년 971,466.8억원 (46.76% 증가)", "value_text": "2024년 661,929.6억원 → 2025년 971,466.8억원 (46.76% 증가)",
               "previous": "66192960000000", "current": "97146675000000", "status": "ok", "source": "OpenDART", "period": "2024년 → 2025년 연간",
               "verified_sentence": "매출은 661,929.6억원에서 971,466.8억원으로 46.76% 증가했습니다."}}


class Plan7QuestionEcho(unittest.TestCase):
    def test_quarter_in_question_is_allowed_only_for_same_quarter(self):
        self.assertEqual(mask_question_quarters("3분기 4분기", "3분기 실적은?"), "분기 4분기")

    def test_comparison_years_allowed_in_the_sentence_that_states_the_rate(self):
        text = "2024년 대비 2025년 연간 실적을 비교하면 매출은 661,929.6억원에서 971,466.8억원으로 46.76% 증가했습니다."
        out, _ = validate_answer({"text": text, "evidence_ids": ["CMP"], "follow_up": ""}, CMP)
        self.assertEqual(out, text)

    def test_clause_is_not_a_company_name(self):
        self.assertTrue(looks_like_clause("실적 좋은데"))
        self.assertTrue(looks_like_clause("영업일이 줄면"))
        self.assertFalse(looks_like_clause("삼성전자"))
        self.assertFalse(looks_like_clause("LG에너지솔루션"))

    def test_multi_scope_followup_hits(self):
        self.assertGreaterEqual(len(scope_hits("실적 좋은데 주가도 올랐어?")), 2)


if __name__ == "__main__":
    unittest.main()

