"""AI와 처리 흐름 검사 코드. 외부 호출은 전부 가짜 결과로 대체한다."""

import copy
import unittest
from unittest.mock import patch

from src.agents.report import parse_json_response, validate_report
from src.models import (
    AppError, Commentary, FinancialData, NewsArticle, NewsData, Statement, StockCandidate, now_kst,
)
from src.pipeline import analyze_theme, normalize_theme


def example_financial():
    stock = StockCandidate("예시회사", "005930", "KOSPI", "005930.KS")
    return FinancialData(stock, 70000, 15.2, now_kst(), now_kst())


def example_news():
    article = NewsArticle(1, "관심 테마 관련 소식", "https://example.com/news", "2026-10-13 09:00:00 KST", "example.com")
    return NewsData((article,), now_kst())


def example_payload():
    statement = {"text": "관련 소식이 관심을 높일 가능성이 있습니다.", "news_ids": [1]}
    return {"stock_name": "예시회사", "price": 70000, "per": 15.2,
            "theme_trend": [copy.deepcopy(statement)], "stock_comment": "이 지표만으로 기업 가치를 단정하기 어렵습니다.",
            "opportunity": copy.deepcopy(statement), "risk": copy.deepcopy(statement), "summary": copy.deepcopy(statement)}


class ReportRulesTests(unittest.TestCase):
    def test_valid_structured_report(self):
        result = validate_report(example_payload(), example_financial(), example_news())
        self.assertEqual(result.opportunity.news_ids, (1,))

    def test_wrong_stock_or_numbers_are_rejected(self):
        for key, value in (("stock_name", "다른회사"), ("price", 99999), ("per", 20), ("per", True)):
            payload = example_payload()
            payload[key] = value
            with self.subTest(key=key), self.assertRaises(AppError):
                validate_report(payload, example_financial(), example_news())

    def test_missing_per_cannot_be_invented(self):
        financial = example_financial()
        missing = FinancialData(financial.stock, financial.price, None, financial.retrieved_at)
        payload = example_payload()
        with self.assertRaises(AppError):
            validate_report(payload, missing, example_news())
        payload["per"] = None
        self.assertIsNotNone(validate_report(payload, missing, example_news()))

    def test_unknown_news_reference_is_rejected(self):
        payload = example_payload()
        payload["risk"]["news_ids"] = [99]
        with self.assertRaises(AppError):
            validate_report(payload, example_financial(), example_news())

    def test_new_number_in_commentary_is_rejected(self):
        payload = example_payload()
        payload["stock_comment"] = "주가는 99999원입니다."
        with self.assertRaises(AppError):
            validate_report(payload, example_financial(), example_news())

    def test_recommendation_is_rejected(self):
        payload = example_payload()
        payload["risk"]["text"] = "지금 매수하세요."
        with self.assertRaises(AppError):
            validate_report(payload, example_financial(), example_news())

    def test_no_news_means_no_news_based_insights(self):
        payload = example_payload()
        news = NewsData((), now_kst(), "empty", "검색된 뉴스가 없습니다.")
        with self.assertRaises(AppError):
            validate_report(payload, example_financial(), news)
        payload.update(theme_trend=[], opportunity=None, risk=None, summary=None)
        result = validate_report(payload, example_financial(), news)
        self.assertIsNone(result.opportunity)

    def test_malformed_json_duplicate_keys_and_empty_ai_result(self):
        for content in ("", "설명만 있는 응답", '{"stocks": [], "stocks": []}'):
            with self.subTest(content=content), self.assertRaises(AppError):
                parse_json_response(content)
        self.assertEqual(parse_json_response('```json\n{"stocks": []}\n```'), {"stocks": []})


class PipelineTests(unittest.TestCase):
    def test_empty_input_does_not_request_services(self):
        with patch("src.pipeline.load_settings") as settings:
            with self.assertRaises(AppError):
                analyze_theme("   ")
            settings.assert_not_called()
        self.assertEqual(normalize_theme("  반도체  테마  "), "반도체 테마")

    def test_unconfirmed_target_stops_before_finance_and_news(self):
        with (patch("src.pipeline.load_settings"), patch("src.pipeline.propose_candidates", return_value=("없는회사", "회사나", "회사다")),
              patch("src.pipeline.load_listing"), patch("src.pipeline.resolve_candidates", return_value=(StockCandidate("없는회사"),)),
              patch("src.pipeline.fetch_financial") as finance, patch("src.pipeline.fetch_news") as news):
            with self.assertRaises(AppError):
                analyze_theme("반도체")
            finance.assert_not_called()
            news.assert_not_called()

    def test_ai_failure_preserves_data_but_is_not_complete(self):
        financial = example_financial()
        with (patch("src.pipeline.load_settings"), patch("src.pipeline.propose_candidates", return_value=("예시회사", "회사나", "회사다")),
              patch("src.pipeline.load_listing"), patch("src.pipeline.resolve_candidates", return_value=(financial.stock,)),
              patch("src.pipeline.fetch_financial", return_value=financial), patch("src.pipeline.fetch_news", return_value=example_news()),
              patch("src.pipeline.generate_commentary", side_effect=AppError("ai_failed", "AI 호출 실패"))):
            result = analyze_theme("반도체")
            self.assertIs(result.financial, financial)
            self.assertIsNone(result.commentary)
            self.assertFalse(result.complete)

    def test_success_calls_services_in_order(self):
        financial = example_financial()
        statement = Statement("관심을 높일 가능성이 있습니다.", (1,))
        commentary = Commentary((statement,), "지표만으로 판단하기 어렵습니다.", statement, statement, statement)
        calls = []
        def response(label, value):
            def action(*args, **kwargs):
                calls.append(label)
                return value
            return action
        with (patch("src.pipeline.load_settings"),
              patch("src.pipeline.propose_candidates", side_effect=response("candidate", ("예시회사", "회사나", "회사다"))),
              patch("src.pipeline.load_listing", side_effect=response("listing", None)),
              patch("src.pipeline.resolve_candidates", return_value=(financial.stock,)),
              patch("src.pipeline.fetch_financial", side_effect=response("finance", financial)),
              patch("src.pipeline.fetch_news", side_effect=response("news", example_news())),
              patch("src.pipeline.generate_commentary", side_effect=response("report", commentary))):
            result = analyze_theme("반도체")
        self.assertEqual(calls, ["candidate", "listing", "finance", "news", "report"])
        self.assertTrue(result.complete)

    def test_failed_news_is_partial_even_when_ai_returns_limited_commentary(self):
        financial = example_financial()
        commentary = Commentary((), "뉴스 없이 지표만으로 판단하기 어렵습니다.", None, None, None)
        failed_news = NewsData((), now_kst(), "failed", "뉴스 조회 실패")
        with (patch("src.pipeline.load_settings"), patch("src.pipeline.propose_candidates", return_value=("예시회사", "회사나", "회사다")),
              patch("src.pipeline.load_listing"), patch("src.pipeline.resolve_candidates", return_value=(financial.stock,)),
              patch("src.pipeline.fetch_financial", return_value=financial), patch("src.pipeline.fetch_news", return_value=failed_news),
              patch("src.pipeline.generate_commentary", return_value=commentary)):
            result = analyze_theme("반도체")
        self.assertIsNotNone(result.commentary)
        self.assertFalse(result.complete)


if __name__ == "__main__":
    unittest.main()
