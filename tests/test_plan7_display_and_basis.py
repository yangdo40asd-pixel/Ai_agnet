import unittest
from src.agents.literal_numbers import mask_data_basis_terms, mask_literal_source_numbers
from src.agents.chat import humanize_amounts


class DisplayAndBasisTests(unittest.TestCase):
    def test_amount_over_10000_eok_is_shown_in_jo_only(self):
        self.assertEqual(humanize_amounts("매출은 3,336,059.4억원이고 이익은 5,000억원입니다."),
                         "매출은 333.6조 원이고 이익은 5,000억원입니다.")

    def test_basis_terms_only_match_evidence_period_fields(self):
        ev = {"EPS": {"text": "x", "period": "최근 12개월(TTM, 2026-06-30 종료)"}}
        self.assertEqual(mask_data_basis_terms("최근 12개월 EPS, 2026년 6월 30일 기준", ev), "최근 개월 EPS, 년 월 일 기준")
        self.assertIn("15", mask_data_basis_terms("15개월 EPS", ev))
        self.assertIn("2025", mask_data_basis_terms("2025년 5월 값", ev))

    def test_year_without_suffix_in_source_matches(self):
        ev = {"NEWS_1": {"url": "u", "text": "2026 KS-QEI 1위"}}
        self.assertNotRegex(mask_literal_source_numbers("2026년 평가", ev), r"\d")
        self.assertRegex(mask_literal_source_numbers("2027년 평가", ev), r"\d")


if __name__ == "__main__":
    unittest.main()

class RelativeYearTests(unittest.TestCase):
    def test_relative_year_matches_today_only(self):
        import datetime
        from src.agents.literal_numbers import mask_relative_years
        today = datetime.date(2026, 10, 28)
        self.assertEqual(mask_relative_years("올해(2026년) 내년 2027년 작년(2025년)", today), "올해(년) 내년 년 작년(년)")
        self.assertIn("2027", mask_relative_years("올해(2027년)", today))



if __name__ == "__main__":
    unittest.main()
