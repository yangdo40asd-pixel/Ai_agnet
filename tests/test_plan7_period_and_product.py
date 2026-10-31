"""계획7: 기간 표기가 낀 %p 변동폭 문장과 한글 제품명 숫자가 근거와 정확히 같을 때만 허용되는지 검사."""

import re
import unittest

from src.agents.financial_numbers import mask_verified_comparisons
from src.agents.literal_numbers import mask_literal_source_numbers


def _cost():
    return {"CMP_COST": {"kind": "annual_comparison", "status": "ok", "stock_code": "005930", "years": [2024, 2025],
                         "fs_div": "CFS", "item": "cost_of_sales_ratio", "previous": "62.00741452",
                         "current": "60.62107713", "delta_pp": "-1.38633739", "cost_bridge_reconciled": True}}


class PeriodPhraseTests(unittest.TestCase):
    def test_pp_change_with_period_phrase_is_accepted_when_exact(self):
        text = "매출원가율은 2024년 대비 2025년 기준 1.39%p 하락하며 개선되었습니다."
        self.assertFalse(re.search(r"\d", mask_verified_comparisons(text, _cost())))

    def test_pp_change_with_wrong_value_or_direction_or_years_is_rejected(self):
        for text in ("매출원가율은 2024년 대비 2025년 기준 1.50%p 하락했습니다.",
                     "매출원가율은 2024년 대비 2025년 기준 1.39%p 상승했습니다.",
                     "매출원가율은 2023년 대비 2024년 기준 1.39%p 하락했습니다."):
            with self.subTest(text=text):
                try:
                    leftover = bool(re.search(r"\d", mask_verified_comparisons(text, _cost())))
                except Exception:
                    leftover = True
                self.assertTrue(leftover)


class HangulProductTests(unittest.TestCase):
    EV = {"NEWS_2": {"url": "https://x", "text": "삼성전자, 갤럭시 Z 폴드8 캠페인", "excerpt": "", "excerpt_scope": "title"}}

    def test_product_number_in_source_is_allowed(self):
        self.assertFalse(re.search(r"\d", mask_literal_source_numbers("갤럭시 Z 폴드8 마케팅 이슈입니다.", self.EV)))

    def test_product_number_not_in_source_is_kept(self):
        self.assertTrue(re.search(r"\d", mask_literal_source_numbers("갤럭시 Z 폴드9 마케팅 이슈입니다.", self.EV)))


if __name__ == "__main__":
    unittest.main()

class YearLinkTests(unittest.TestCase):
    def _ev(self):
        return {"CMP_REV": {"kind": "annual_comparison", "status": "ok", "stock_code": "005930", "years": [2024, 2025],
                            "fs_div": "CFS", "item": "revenue", "previous": "300870900000000",
                            "current": "333605940000000", "change_pct": "10.8826"}}

    def test_year_with_basis_word_before_claim_is_accepted(self):
        for text in ("2025년 기준 매출은 3,008,709.0억원에서 3,336,059.4억원으로 10.88% 증가했습니다.",
                     "2024년 대비 매출은 3,008,709.0억원에서 3,336,059.4억원으로 10.88% 증가했습니다."):
            with self.subTest(text=text):
                self.assertFalse(re.search(r"\d", mask_verified_comparisons(text, self._ev())))

    def test_unrelated_or_wrong_year_is_still_rejected(self):
        for text in ("2026년 기준 매출은 3,008,709.0억원에서 3,336,059.4억원으로 10.88% 증가했습니다.",
                     "2025년 신규 계약으로 매출은 3,008,709.0억원에서 3,336,059.4억원으로 10.88% 증가했습니다."):
            with self.subTest(text=text):
                try:
                    leftover = bool(re.search(r"\d", mask_verified_comparisons(text, self._ev())))
                except Exception:
                    leftover = True
                self.assertTrue(leftover)
