"""계획7: 검증 문장(verified_sentence)과 단독 금액 허용(_AMOUNT)이 검증기와 같은 기준으로 동작하는지 검사."""

import re
import unittest

from src.agents.financial_numbers import mask_verified_comparisons, use_rate_sentences, verified_sentence
from src.agents.request import request_scope


def _fact(item, previous, current, **extra):
    base = {"kind": "annual_comparison", "status": "ok", "stock_code": "005930", "years": [2024, 2025],
            "fs_div": "CFS", "item": item, "previous": previous, "current": current}
    base.update(extra)
    return base


def _evidence():
    return {
        "CMP_OP": _fact("operating_income", "32725960000000", "43601050000000", change_pct="33.2326"),
        "CMP_COST": _fact("cost_of_sales_ratio", "62.00741452", "60.62107713", delta_pp="-1.38633739",
                          cost_bridge_reconciled=True),
        "CMP_SGA": _fact("selling_expenses_ratio", "27.1155", "27.1155", delta_pp="0", cost_bridge_reconciled=True),
    }


class VerifiedSentenceTests(unittest.TestCase):
    def test_cost_ratio_sentence_uses_validator_format(self):
        ev = _evidence()
        self.assertEqual(verified_sentence(ev["CMP_COST"]), "매출원가율은 62.01%에서 60.62%로 하락했습니다.")
        masked = mask_verified_comparisons(verified_sentence(ev["CMP_COST"]), {"CMP_COST": ev["CMP_COST"]})
        self.assertFalse(re.search(r"\d", masked))

    def test_cost_ratio_sentence_requires_reconciled_bridge_and_a_change(self):
        ev = _evidence()
        self.assertIsNone(verified_sentence(ev["CMP_SGA"]))
        unreconciled = dict(ev["CMP_COST"], cost_bridge_reconciled=False)
        self.assertIsNone(verified_sentence(unreconciled))

    def test_standalone_amount_accepts_exact_current_and_previous_values_only(self):
        ev = {"CMP_OP": _evidence()["CMP_OP"]}
        ok = mask_verified_comparisons("2025년 영업이익은 436,010.5억원입니다.", ev)
        self.assertFalse(re.search(r"\d", ok))
        past = mask_verified_comparisons("2024년 영업이익은 327,259.6억원이었습니다.", ev)
        self.assertFalse(re.search(r"\d", past))
        wrong = "2025년 영업이익은 327,259.6억원입니다."
        try:
            leftover = bool(re.search(r"\d", mask_verified_comparisons(wrong, ev)))
        except Exception:
            leftover = True
        self.assertTrue(leftover)

    def test_rate_sentence_mode_needs_single_basis(self):
        self.assertTrue(use_rate_sentences({"CMP_OP": _evidence()["CMP_OP"]}))


class NewsScopeTests(unittest.TestCase):
    def test_issue_and_report_words_request_news(self):
        for text in ("삼성전자 최근 주요 이슈 알려줘", "삼성전자 소식 알려줘", "삼성전자 관련 보도 정리해줘"):
            with self.subTest(text=text):
                self.assertEqual(request_scope(text), "news")

    def test_financial_question_scope_is_unchanged(self):
        self.assertEqual(request_scope("삼성전자 영업이익 얼마야?"), "financials")


if __name__ == "__main__":
    unittest.main()