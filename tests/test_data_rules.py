"""사용자가 직접 실행할 로컬 검사. 가짜 응답만 사용하며 외부 서비스를 호출하지 않는다."""

import unittest
from unittest.mock import Mock, patch

import pandas as pd
import requests

from src.config import Settings
from src.data.news import fetch_news, parse_news, safe_news_url
from src.data.stock import (
    financial_from_info, require_target, resolve_candidates, validate_candidate_names, yahoo_ticker,
)
from src.models import AppError, StockCandidate


class StockRulesTests(unittest.TestCase):
    def setUp(self):
        self.stock = StockCandidate("예시회사", "005930", "KOSPI", "005930.KS")
        self.info = {"symbol": "005930.KS", "currency": "KRW", "currentPrice": 70000,
                     "trailingPE": 15.2, "regularMarketTime": 1700000000}

    def test_candidates_require_three_nonempty_unique_names(self):
        self.assertEqual(validate_candidate_names([" 회사가 ", "회사나", "회사다"]), ("회사가", "회사나", "회사다"))
        for bad in ([], ["회사", "회사", "다른회사"], ["회사", " ", "다른회사"], ["회사", None, "다른회사"]):
            with self.subTest(bad=bad), self.assertRaises(AppError):
                validate_candidate_names(bad)

    def test_market_suffix_and_unsupported_market(self):
        self.assertEqual(yahoo_ticker("005930", "KOSPI"), "005930.KS")
        self.assertEqual(yahoo_ticker("247540", "KOSDAQ"), "247540.KQ")
        self.assertIsNone(yahoo_ticker("123456", "KONEX"))

    def test_unconfirmed_first_candidate_does_not_use_next_candidate(self):
        listing = pd.DataFrame([{"Name": "확인된회사", "Code": "005930", "Market": "KOSPI"}])
        candidates = resolve_candidates(("없는회사", "확인된회사", "다른회사"), listing)
        self.assertTrue(candidates[1].verified)
        with self.assertRaises(AppError) as error:
            require_target(candidates)
        self.assertEqual(error.exception.code, "stock_unconfirmed")

    def test_ambiguous_name_is_not_guessed(self):
        listing = pd.DataFrame([
            {"Name": "같은회사", "Code": "005930", "Market": "KOSPI"},
            {"Name": "같은회사", "Code": "247540", "Market": "KOSDAQ"},
        ])
        candidate = resolve_candidates(("같은회사",), listing)[0]
        self.assertFalse(candidate.verified)

    def test_missing_per_and_missing_price_time_are_preserved(self):
        data = financial_from_info(self.stock, {**self.info, "trailingPE": None, "regularMarketTime": None})
        self.assertEqual(data.price, 70000)
        self.assertIsNone(data.per)
        self.assertIsNone(data.price_at)
        self.assertTrue(data.warnings)

    def test_price_falls_back_to_regular_market_price(self):
        data = financial_from_info(self.stock, {**self.info, "currentPrice": None, "regularMarketPrice": 71000})
        self.assertEqual(data.price, 71000)

    def test_current_price_is_not_assigned_regular_market_timestamp(self):
        data = financial_from_info(self.stock, self.info)
        self.assertIsNone(data.price_at)
        market_data = financial_from_info(self.stock, {**self.info, "regularMarketPrice": 68000})
        self.assertEqual(market_data.price, 68000)
        self.assertIsNotNone(market_data.price_at)

    def test_wrong_symbol_is_rejected(self):
        with self.assertRaises(AppError):
            financial_from_info(self.stock, {**self.info, "symbol": "247540.KQ"})

    def test_nonfinite_or_boolean_values_are_not_numbers(self):
        for bad in (float("nan"), float("inf"), True, "70000"):
            with self.subTest(bad=bad):
                data = financial_from_info(self.stock, {**self.info, "currentPrice": bad})
                self.assertIsNone(data.price)

    def test_wrong_currency_is_not_displayed_in_won(self):
        data = financial_from_info(self.stock, {**self.info, "currency": "USD"})
        self.assertIsNone(data.price)
        self.assertTrue(data.warnings)

    def test_hidden_price_does_not_keep_a_price_timestamp(self):
        data = financial_from_info(self.stock, {**self.info, "regularMarketPrice": 70000, "currency": "USD"})
        self.assertIsNone(data.price)
        self.assertIsNone(data.price_at)

    def test_missing_both_financial_values_stops_analysis(self):
        with self.assertRaises(AppError):
            financial_from_info(self.stock, {**self.info, "currentPrice": None, "trailingPE": None})


class NewsRulesTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings("test-only-not-a-key", "test-model", "test-id", "test-secret")

    def test_title_link_time_are_preserved_and_cleaned(self):
        data = parse_news({"items": [{"title": "<b>반도체</b> &quot;관련 소식&quot;",
                                    "originallink": "https://example.com/news",
                                    "pubDate": "Tue, 13 Oct 2026 09:00:00 +0900"}]})
        self.assertEqual(data.status, "ok")
        self.assertEqual(data.articles[0].title, '반도체 "관련 소식"')
        self.assertEqual(data.articles[0].publisher_domain, "example.com")
        self.assertIn("KST", data.articles[0].published_at)

    def test_zero_news_and_bad_response_are_different(self):
        self.assertEqual(parse_news({"items": []}).status, "empty")
        self.assertEqual(parse_news({"error": "failed"}).status, "failed")

    def test_missing_link_time_is_partial(self):
        data = parse_news({"items": [{"title": "관련 뉴스"}]})
        self.assertEqual(data.status, "partial")
        self.assertIsNone(data.articles[0].url)

    def test_unsafe_url_is_not_a_clickable_link(self):
        self.assertIsNone(safe_news_url("javascript:alert(1)"))
        self.assertIsNone(safe_news_url("https://user:password@example.com"))
        self.assertIsNone(safe_news_url("https://example.com/\nnews"))

    def test_duplicate_news_is_not_repeated(self):
        item = {"title": "관련 소식", "link": "https://example.com/news"}
        self.assertEqual(len(parse_news({"items": [item, item]}).articles), 1)

    def test_timeout_returns_failure_and_uses_explicit_timeout(self):
        with patch("src.data.news.requests.get", side_effect=requests.Timeout) as get:
            data = fetch_news("반도체", "예시회사", self.settings)
        self.assertEqual(data.status, "failed")
        self.assertIn("초과", data.message)
        self.assertEqual(get.call_args.kwargs["timeout"], self.settings.request_timeout)

    def test_http_error_does_not_disclose_response_body(self):
        response = Mock(status_code=401, text="private response body")
        with patch("src.data.news.requests.get", return_value=response):
            data = fetch_news("반도체", "예시회사", self.settings)
        self.assertEqual(data.status, "failed")
        self.assertIn("인증", data.message)
        self.assertNotIn("private", data.message)

    def test_bad_json_is_a_failed_result(self):
        response = Mock(status_code=200)
        response.json.side_effect = ValueError("malformed JSON")
        with patch("src.data.news.requests.get", return_value=response):
            self.assertEqual(fetch_news("반도체", "예시회사", self.settings).status, "failed")


if __name__ == "__main__":
    unittest.main()
