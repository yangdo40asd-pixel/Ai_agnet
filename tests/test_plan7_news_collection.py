"""계획7: 뉴스 보완 조회 정렬과 회사 주체 문구 판정을 네트워크 없이 확인한다."""
import unittest
from unittest.mock import Mock, patch
from urllib.parse import quote

from src.config import Settings
from src.models import NewsArticle, NewsData, StockCandidate, now_kst
from src.data.news import fetch_news
import src.agents.news_relevance as policy


def page(titles, total=50):
    return Mock(status_code=200, json=Mock(return_value={"total": total, "items": [
        {"title": t, "description": "발췌", "originallink": "https://example.com/" + str(i) + quote(t),
         "pubDate": "Tue, 27 Oct 2026 09:00:00 +0900"} for i, t in enumerate(titles)]}))


class SupplementSortTest(unittest.TestCase):
    def test_supplement_uses_relevance_sort_when_default_is_date(self):
        settings = Settings("t", "t", "id", "secret")
        with patch("src.data.news.requests.get", side_effect=[page(["다른 소식%d" % i for i in range(10)]),
                                                            page(["가상회사 기사%d" % i for i in range(10)])]) as get:
            news = fetch_news("가상회사", "가상회사", settings)
        first, second = (c.kwargs["params"] for c in get.call_args_list)
        self.assertEqual((first["sort"], first["start"]), ("date", 1))
        self.assertEqual((second["sort"], second["start"]), ("sim", 1))
        self.assertEqual(len(news.articles), 20)

    def test_relevance_default_keeps_paging(self):
        settings = Settings("t", "t", "id", "secret", news_sort="sim")
        with patch("src.data.news.requests.get", side_effect=[page(["다른 소식%d" % i for i in range(10)]),
                                                            page(["가상회사 기사%d" % i for i in range(10)])]) as get:
            fetch_news("가상회사", "가상회사", settings)
        second = get.call_args_list[1].kwargs["params"]
        self.assertEqual((second["sort"], second["start"]), ("sim", 11))


class CompanySubjectTest(unittest.TestCase):
    def _admit(self, title, subject):
        stock = StockCandidate("삼성전자", "005930")
        news = NewsData((NewsArticle(1, title, None, None, None),), now_kst(), "ok", "")
        payload = {"assessments": [{"id": 1, "relation": "company", "subject_quote": subject, "support_quote": title}]}
        return policy.parse_assessments(payload, news, stock, "삼성전자")[0]

    def test_subject_phrase_containing_company_name_is_accepted(self):
        result = self._admit("이재용 삼성전자 회장, 올해 주식 순취득 1위", "이재용 삼성전자 회장")
        self.assertTrue(result.accepted)

    def test_longer_company_name_is_not_the_same_company(self):
        result = self._admit("삼성전자서비스 노조 파업", "삼성전자서비스")
        self.assertFalse(result.accepted)

    def test_curly_vs_straight_quotes_do_not_break_title_match(self):
        title = '블룸버그 “BYD가 현대차·기아 안방까지 위협”…현대차 임원 “절망감...'
        stock = StockCandidate("현대차", "005380")
        news = NewsData((NewsArticle(1, title, None, None, None),), now_kst(), "ok", "")
        payload = {"assessments": [{"id": 1, "relation": "company", "subject_quote": "현대차", "support_quote": '임원 "절망감...'}]}
        self.assertTrue(policy.parse_assessments(payload, news, stock, "현대차")[0].accepted)

    def test_changed_wording_in_quote_is_still_rejected(self):
        title = "삼성전자 신제품 공개"
        stock = StockCandidate("삼성전자", "005930")
        news = NewsData((NewsArticle(1, title, None, None, None),), now_kst(), "ok", "")
        payload = {"assessments": [{"id": 1, "relation": "company", "subject_quote": "삼성전자", "support_quote": "삼성전자 신제품 발표"}]}
        with self.assertRaises(Exception) as ctx:
            policy.parse_assessments(payload, news, stock, "삼성전자")
        self.assertEqual(ctx.exception.code, "news_relation_evidence")

    def test_subject_without_company_name_is_not_accepted(self):
        result = self._admit("이재용 회장, 올해 주식 순취득 1위 삼성전자 언급", "이재용 회장")
        self.assertFalse(result.accepted)


if __name__ == "__main__":
    unittest.main()