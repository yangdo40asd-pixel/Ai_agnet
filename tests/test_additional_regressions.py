"""추가 검토에서 발견한 응답 형식과 정상 테마 처리의 회귀 검사."""

import unittest
from unittest.mock import patch

from src.agents.report import validate_report
from src.data.news import parse_news
from src.data.stock import load_listing
from src.models import AppError
from test_report_pipeline import example_financial, example_news, example_payload


class AdditionalRegressionTests(unittest.TestCase):
    def test_invalid_listing_type_is_a_listing_error(self):
        for value in (None, {}, []):
            with self.subTest(value=value), patch("FinanceDataReader.StockListing", return_value=value):
                with self.assertRaises(AppError) as error:
                    load_listing()
                self.assertEqual(error.exception.code, "listing_format")

    def test_partly_unreadable_news_is_not_reported_as_full_success(self):
        item = {"title": "관련 소식", "originallink": "https://example.com/news",
                "pubDate": "Tue, 13 Oct 2026 09:00:00 +0900"}
        result = parse_news({"items": [item, None, {"title": None}]})
        self.assertEqual(len(result.articles), 1)
        self.assertEqual(result.status, "partial")
        self.assertIn("읽지 못", result.message)

    def test_numbers_in_known_theme_names_are_not_financial_claims(self):
        for theme in ("2차전지", "5G", "HBM3"):
            payload = example_payload()
            payload["risk"]["text"] = f"{theme} 관련 소식은 추가 확인이 필요합니다."
            with self.subTest(theme=theme):
                self.assertIsNotNone(validate_report(payload, example_financial(), example_news(), theme=theme))

    def test_theme_exception_does_not_allow_new_financial_numbers(self):
        for text, theme in (("2차전지의 주가는 99999원입니다.", "2차전지"),
                            ("주가는 99999원입니다.", "반도체 99999원")):
            payload = example_payload()
            payload["risk"]["text"] = text
            with self.subTest(text=text), self.assertRaises(AppError):
                validate_report(payload, example_financial(), example_news(), theme=theme)


if __name__ == "__main__":
    unittest.main()
