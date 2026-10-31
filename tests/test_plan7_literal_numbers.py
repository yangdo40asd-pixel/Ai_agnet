"""계획7 P7-B: 근거 원문에 그대로 있는 서수·기간·연도·제품명 숫자는 허용하고, 값·단위가 바뀐 숫자와 근거에 없는 숫자는 계속 거절한다."""

import unittest

from src.agents.chat import validate_answer
from src.models import AppError


def news(text, url="https://example.com/a"):
    return {"text": text, "url": url, "scope": "headline_only", "stock_name": "삼성전자", "structured_facts": []}


def check(text, evidence, ids):
    return validate_answer({"text": text, "evidence_ids": ids, "follow_up": ""}, evidence)


class LiteralSourceNumberTests(unittest.TestCase):
    def setUp(self):
        self.evidence = {
            "NEWS_1": news("삼성전자, 2026 한국품질만족지수 TV 17년 연속 1위"),
            "NEWS_2": news("삼성전자 HBM4 양산 앞두고 3나노 공정 점검, 항소심 2심 재판 진행"),
            "NEWS_3": news("다른 회사 2025년 5분기 연속 1위 확정", url="https://example.com/c"),
        }

    def assert_rejected(self, text, ids):
        with self.assertRaises(AppError) as ctx:
            check(text, self.evidence, ids)
        self.assertEqual(ctx.exception.code, "chat_numbers", text)

    def test_numbers_written_verbatim_in_cited_news_are_allowed(self):
        for text in (
            "삼성전자는 2026 한국품질만족지수에서 TV 부문 17년 연속 1위에 선정되었다고 보도되었습니다.",
            "삼성전자는 2026 한국품질만족지수에서 TV 부문 1위에 올랐습니다.",
        ):
            with self.subTest(text=text):
                answer, _ = check(text, self.evidence, ["NEWS_1"])
                self.assertEqual(answer, text)
        answer, _ = check("삼성전자는 HBM4 양산과 3나노 공정 점검, 2심 재판이 보도되었습니다.", self.evidence, ["NEWS_2"])
        self.assertIn("HBM4", answer)

    def test_number_in_provided_article_excerpt_is_allowed_but_unprovided_is_not(self):
        evidence = {"NEWS_1": dict(news("솔리다임, 미국 낸드 공장 추진"), scope="article_excerpt",
                                   excerpt="투자 규모는 450억달러 수준으로 알려졌다.", excerpt_scope="article_excerpt")}
        answer, _ = check("솔리다임은 450억달러 규모 투자를 협의 중이라고 보도되었습니다.", evidence, ["NEWS_1"])
        self.assertIn("450억달러", answer)
        with self.assertRaises(AppError) as ctx:
            check("솔리다임은 500억달러 규모 투자를 협의 중이라고 보도되었습니다.", evidence, ["NEWS_1"])
        self.assertEqual(ctx.exception.code, "chat_numbers")

    def test_changed_number_or_unit_is_rejected(self):
        self.assert_rejected("삼성전자는 TV 부문 18년 연속 1위에 선정되었습니다.", ["NEWS_1"])
        self.assert_rejected("삼성전자는 TV 부문 7년 연속 1위에 선정되었습니다.", ["NEWS_1"])  # 17년의 일부(7년)로 통과하면 안 됨
        self.assert_rejected("삼성전자는 2025 한국품질만족지수에서 1위에 선정되었습니다.", ["NEWS_1"])
        self.assert_rejected("삼성전자 재판은 3심까지 진행되었습니다.", ["NEWS_2"])  # 2심을 3심으로 바꿈
        self.assert_rejected("삼성전자는 2나노 공정을 점검했습니다.", ["NEWS_2"])
        self.assert_rejected("삼성전자는 HBM5 양산을 앞두고 있습니다.", ["NEWS_2"])

    def test_number_only_in_uncited_evidence_is_rejected(self):
        self.assert_rejected("삼성전자는 5분기 연속 1위를 기록했습니다.", ["NEWS_1"])

    def test_amount_ratio_and_multiple_verbatim_in_title_are_allowed(self):
        evidence = {"NEWS_9": news("삼성전자 신제품 선주문 10% 확대, 매출 2조원 돌파, 이재용 5조 2천억원 순취득, 50개국 수출")}
        for text in (
            "삼성전자 신제품 선주문이 10% 확대되었다고 보도되었습니다.",
            "삼성전자 매출은 2조원을 돌파했다고 보도되었습니다.",
            "이재용 회장이 5조 2천억원을 순취득했다고 보도되었습니다.",
            "삼성전자는 50개국에 수출한다고 보도되었습니다.",
        ):
            with self.subTest(text=text):
                answer, _ = check(text, evidence, ["NEWS_9"])
                self.assertEqual(answer, text)

    def test_changed_amount_ratio_or_unit_is_rejected(self):
        evidence = {"NEWS_9": news("삼성전자 신제품 선주문 10% 확대, 매출 12조원 돌파, 3배 성장")}
        for text in (
            "삼성전자 신제품 선주문이 11% 확대되었다고 보도되었습니다.",
            "삼성전자 신제품 선주문이 110% 확대되었다고 보도되었습니다.",
            "삼성전자 매출은 2조원을 돌파했다고 보도되었습니다.",  # 12조원의 일부
            "삼성전자 매출은 12억원을 돌파했다고 보도되었습니다.",
            "삼성전자는 10배 성장했다고 보도되었습니다.",
            "삼성전자 신제품 선주문이 10배 확대되었다고 보도되었습니다.",  # 10%를 10배로 바꿈
        ):
            with self.subTest(text=text):
                with self.assertRaises(AppError) as ctx:
                    check(text, evidence, ["NEWS_9"])
                self.assertEqual(ctx.exception.code, "chat_numbers")
        answer, _ = check("삼성전자는 3배 성장했다고 보도되었습니다.", evidence, ["NEWS_9"])
        self.assertIn("3배", answer)

    def test_currency_suffix_on_scale_amount_is_same_value_but_not_a_longer_amount(self):
        evidence = {"NEWS_8": news('삼성전자 "200억 과징금 불복", 이재용 5조 2천억 순취득')}
        answer, _ = check("삼성전자는 200억 원의 과징금에 불복했다고 보도되었습니다.", evidence, ["NEWS_8"])
        self.assertIn("200억 원", answer)
        for text in ("삼성전자는 20억 원의 과징금에 불복했다고 보도되었습니다.",
                     "이재용 회장이 5조원을 순취득했다고 보도되었습니다."):  # 5조 2천억의 일부
            with self.subTest(text=text), self.assertRaises(AppError):
                check(text, evidence, ["NEWS_8"])

    def test_non_source_evidence_is_not_a_literal_source(self):
        evidence = {"PRICE": {"text": "삼성전자 · PRICE: 2026.00원", "value_text": "2026.00원", "value": 2026, "unit": "원", "status": "ok"}}
        with self.assertRaises(AppError):
            check("삼성전자는 2026 한국품질만족지수에서 1위를 했습니다.", evidence, ["PRICE"])


if __name__ == "__main__":
    unittest.main()