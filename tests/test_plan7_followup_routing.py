"""계획7 P7-B-0b: 직전 대화를 가리키는 지시어("방금", "아까 그")가 회사명으로 오인되지 않는지 회귀 검사."""

import unittest

from src.agents.request import company_to_lookup, route_message


class FollowUpDeicticRoutingTests(unittest.TestCase):
    def test_deictic_words_are_not_company_names(self):
        for text in (
            "방금 이슈 두 문장으로 요약해줘",
            "방금 이슈 세 줄로 요약해줘",
            "아까 그 이슈 요약해줘",
            "조금 전 이슈 요약해줘",
            "앞서 말한 뉴스 정리해줘",
            "해당 이슈 다시 설명해줘",
            "그 이슈 요약해줘",
        ):
            with self.subTest(text=text):
                self.assertEqual(company_to_lookup(text), "")

    def test_deictic_prefix_is_removed_but_real_company_is_kept(self):
        self.assertEqual(company_to_lookup("방금 삼성전자 이슈 요약해줘"), "삼성전자")
        self.assertEqual(company_to_lookup("삼성전자 주요 이슈 알려줘"), "삼성전자")
        self.assertEqual(company_to_lookup("SK하이닉스 최근 실적은 어때?"), "SK하이닉스")
        # 이름 안에 지시어 글자가 들어 있는 실제 회사명은 건드리지 않는다.
        self.assertEqual(company_to_lookup("위메이드 주요 이슈 알려줘"), "위메이드")
        self.assertEqual(company_to_lookup("이마트 실적 알려줘"), "이마트")
        self.assertEqual(company_to_lookup("해당화 뉴스 알려줘"), "해당화")

    def test_evaluative_followups_are_not_company_names(self):
        for text in ("그 정도면 괜찮은 실적이야?", "왜 영업이익이 매출보다 많이 늘어난 거야?",
                     "그 정도 영업이익이면 괜찮은 거야?"):
            with self.subTest(text=text):
                self.assertEqual(company_to_lookup(text), "")
                intent = route_message(text, None, "005930", [], None)
                self.assertEqual((intent.action, intent.code), ("answer", "005930"))

    def test_followup_with_selected_stock_routes_to_answer(self):
        intent = route_message("방금 이슈 두 문장으로 요약해줘", None, "005930", [], None)
        self.assertEqual((intent.action, intent.code), ("answer", "005930"))
        intent = route_message("아까 그 이슈 요약해줘", None, "005930", [], None)
        self.assertEqual((intent.action, intent.code), ("answer", "005930"))


if __name__ == "__main__":
    unittest.main()