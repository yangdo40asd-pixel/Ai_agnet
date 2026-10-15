"""브라우저·서버 없이 실제 화면 코드와 처리 흐름을 검수한다.

AI, KRX, Yahoo, NAVER 응답만 대체하며 후보 확인·수집 결과 검사·리포트
검사·화면·세션 처리는 실제 코드를 사용한다. 실제 API 키는 읽지 않는다.
"""

import copy
from contextlib import ExitStack
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

import pandas as pd
from streamlit.testing.v1 import AppTest

from src.config import Settings

APP_PATH = Path(__file__).resolve().parents[1] / "src" / "ui" / "app.py"


def response(payload):
    import json
    return SimpleNamespace(content=json.dumps(payload, ensure_ascii=False), response_metadata={"finish_reason": "stop"})


def report_payload(per=15.2, news=True):
    statement = {"text": "관련 소식이 관심을 높일 가능성이 있습니다.", "news_ids": [1]}
    return {"stock_name": "예시회사", "price": 70000, "per": per,
            "theme_trend": [copy.deepcopy(statement)] if news else [],
            "stock_comment": "이 지표만으로 기업 가치를 단정하기 어렵습니다.",
            "opportunity": copy.deepcopy(statement) if news else None,
            "risk": copy.deepcopy(statement) if news else None,
            "summary": copy.deepcopy(statement) if news else None}


class UserFlowTests(unittest.TestCase):
    def setUp(self):
        self.stack = ExitStack()
        self.addCleanup(self.stack.close)
        self.stack.enter_context(patch("socket.socket.connect", side_effect=AssertionError("로컬 검사에서 실제 외부 요청은 허용하지 않습니다.")))
        self.stack.enter_context(patch("src.pipeline.load_settings", return_value=Settings(
            "test-only-not-a-key", "test-model", "test-id", "test-secret")))
        listing = pd.DataFrame([
            {"Name": "예시회사", "Code": "005930", "Market": "KOSPI"},
            {"Name": "회사나", "Code": "247540", "Market": "KOSDAQ"},
            {"Name": "회사다", "Code": "000660", "Market": "KOSPI"},
        ])
        self.listing = self.stack.enter_context(patch("FinanceDataReader.StockListing", return_value=listing))
        self.ticker = self.stack.enter_context(patch("yfinance.Ticker"))
        self.info = {"symbol": "005930.KS", "currency": "KRW", "regularMarketPrice": 70000,
                     "currentPrice": 70000, "trailingPE": 15.2, "regularMarketTime": 1700000000}
        self.ticker.return_value.get_info.return_value = self.info
        self.news_response = Mock(status_code=200)
        self.news_response.json.return_value = {"items": [
            {"title": "<b>관심 테마</b> 관련 소식", "originallink": "https://example.com/news",
             "pubDate": "Tue, 13 Oct 2026 09:00:00 +0900"}]}
        self.news_request = self.stack.enter_context(patch("src.data.news.requests.get", return_value=self.news_response))
        self.groq = self.stack.enter_context(patch("langchain_groq.ChatGroq"))
        self.llm = self.groq.return_value
        self.set_responses()
        self.app = AppTest.from_file(str(APP_PATH), default_timeout=15)
        self.app.run()
        self.assert_no_exception()

    def set_responses(self, names=None, report=None):
        self.llm.invoke.side_effect = [
            response({"stocks": names or ["예시회사", "회사나", "회사다"]}),
            response(report if report is not None else report_payload()),
        ]

    def submit(self, theme="반도체"):
        self.app.chat_input[0].set_value(theme).run()
        self.assert_no_exception()

    def assert_no_exception(self):
        self.assertEqual(len(self.app.exception), 0, [element.message for element in self.app.exception])

    def error_text(self):
        return " ".join(element.value for element in self.app.error)

    def test_initial_screen_does_not_call_services(self):
        self.assertEqual(len(self.app.chat_input), 1)
        self.assertEqual(len(self.app.metric), 0)
        self.llm.invoke.assert_not_called()
        self.listing.assert_not_called()
        self.news_request.assert_not_called()

    def test_normal_theme_runs_complete_pipeline_and_renders_sources(self):
        self.submit()
        self.assertEqual(len(self.app.success), 1)
        self.assertEqual([metric.value for metric in self.app.metric], ["70,000원", "15.20배"])
        self.assertEqual(len(self.app.dataframe[0].value), 3)
        self.assertEqual(self.app.dataframe[0].value.iloc[1]["시장"], "KOSDAQ")
        self.assertEqual(self.llm.invoke.call_count, 2)
        self.ticker.assert_called_once_with("005930.KS")
        links = [element.proto.url for element in self.app.get("link_button")]
        self.assertIn("https://example.com/news", links)
        self.assertTrue(any("조회 시각" in element.value for element in self.app.caption))

    def test_kosdaq_target_uses_kq_code(self):
        self.info["symbol"] = "247540.KQ"
        payload = report_payload()
        payload["stock_name"] = "회사나"
        self.set_responses(["회사나", "예시회사", "회사다"], payload)
        self.submit("2차전지")
        self.ticker.assert_called_once_with("247540.KQ")
        self.assertEqual(len(self.app.success), 1)

    def test_numeric_theme_name_in_ai_text_does_not_fail(self):
        payload = report_payload()
        payload["risk"]["text"] = "2차전지 관련 소식은 추가 확인이 필요합니다."
        self.set_responses(report=payload)
        self.submit("2차전지 테마주 분석해줘")
        self.assertEqual(len(self.app.success), 1)
        self.assertEqual(len(self.app.error), 0)

    def test_partly_unreadable_news_displays_partial_result(self):
        self.news_response.json.return_value["items"].append({"title": None})
        self.submit()
        self.assertEqual(len(self.app.metric), 2)
        self.assertEqual(len(self.app.success), 0)
        self.assertTrue(any("일부 뉴스 항목을 읽지 못" in item.value for item in self.app.warning))

    def test_malformed_listing_displays_specific_error(self):
        self.listing.return_value = None
        self.submit()
        self.assertIn("상장 종목 목록의 형식", self.error_text())
        self.ticker.assert_not_called()
        self.news_request.assert_not_called()

    def test_blank_and_too_long_theme_never_call_ai(self):
        self.submit("   ")
        self.assertIn("테마를 입력", self.error_text())
        self.submit("가" * 121)
        self.assertIn("120자", self.error_text())
        self.llm.invoke.assert_not_called()

    def test_duplicate_candidates_stop_before_data_requests(self):
        self.set_responses(["예시회사", "예시회사", "회사다"])
        self.submit()
        self.assertIn("중복", self.error_text())
        self.listing.assert_not_called()
        self.ticker.assert_not_called()
        self.news_request.assert_not_called()

    def test_unconfirmed_target_does_not_use_next_candidate(self):
        self.set_responses(["없는회사", "회사나", "회사다"])
        self.submit()
        self.assertIn("첫 번째 후보", self.error_text())
        self.ticker.assert_not_called()
        self.news_request.assert_not_called()
        self.assertEqual(len(self.app.metric), 0)

    def test_financial_request_failure_stops_news_and_report(self):
        self.ticker.return_value.get_info.side_effect = RuntimeError("provider failure")
        self.submit()
        self.assertIn("주가·PER 조회에 실패", self.error_text())
        self.news_request.assert_not_called()
        self.assertEqual(self.llm.invoke.call_count, 1)

    def test_missing_per_displays_no_unit_and_no_full_success(self):
        self.info["trailingPE"] = None
        self.set_responses(report=report_payload(per=None))
        self.submit()
        self.assertEqual(self.app.metric[1].value, "정보 없음")
        self.assertEqual(len(self.app.success), 0)
        self.assertTrue(any("PER 정보가 없습니다" in item.value for item in self.app.warning))

    def test_unconfirmed_currency_hides_price_and_its_timestamp(self):
        self.info["currency"] = "USD"
        payload = report_payload()
        payload["price"] = None
        self.set_responses(report=payload)
        self.submit()
        self.assertEqual(self.app.metric[0].value, "정보 없음")
        self.assertTrue(any("가격 자료 시각: 확인되지 않음" in item.value for item in self.app.caption))
        self.assertFalse(any("가격 자료 시각: 2023" in item.value for item in self.app.caption))
        self.assertEqual(len(self.app.success), 0)

    def test_no_news_preserves_finance_without_invented_insights(self):
        self.news_response.json.return_value = {"items": []}
        self.set_responses(report=report_payload(news=False))
        self.submit()
        self.assertEqual(len(self.app.metric), 2)
        self.assertEqual(len(self.app.success), 0)
        self.assertTrue(any("뉴스 제목을 확보하지 못해" in item.value for item in self.app.info))

    def test_news_auth_failure_keeps_financial_result(self):
        self.news_response.status_code = 401
        self.set_responses(report=report_payload(news=False))
        self.submit()
        self.assertTrue(any("인증" in item.value for item in self.app.warning))
        self.assertEqual(len(self.app.metric), 2)
        self.assertEqual(len(self.app.success), 0)

    def test_ai_report_number_mismatch_keeps_actual_metrics(self):
        payload = report_payload()
        payload["price"] = 99999
        self.set_responses(report=payload)
        self.submit()
        self.assertIn("숫자가 조회값과 달라", self.error_text())
        self.assertEqual(self.app.metric[0].value, "70,000원")
        self.assertEqual(len(self.app.success), 0)

    def test_second_ai_call_failure_preserves_collected_data(self):
        self.llm.invoke.side_effect = [response({"stocks": ["예시회사", "회사나", "회사다"]}), RuntimeError("fake private details")]
        self.submit()
        self.assertIn("AI 호출에 실패", self.error_text())
        self.assertNotIn("private", self.error_text())
        self.assertEqual(len(self.app.metric), 2)
        self.assertEqual(len(self.app.success), 0)

    def test_rerun_and_clear_do_not_request_again(self):
        self.submit()
        self.app.run()
        self.assert_no_exception()
        self.assertEqual(self.llm.invoke.call_count, 2)
        self.app.button[0].click().run()
        self.assert_no_exception()
        self.assertEqual(len(self.app.metric), 0)
        self.assertEqual(len(self.app.dataframe), 0)
        self.assertEqual(len(self.app.chat_message), 0)
        self.assertEqual(self.llm.invoke.call_count, 2)

    def test_failed_new_request_clears_previous_result(self):
        self.submit()
        self.llm.invoke.side_effect = RuntimeError("fake AI failure")
        self.submit("다른 테마")
        self.assertEqual(len(self.app.metric), 0)
        self.assertEqual(len(self.app.dataframe), 0)
        self.assertEqual(len(self.app.success), 0)
        self.assertIn("AI 호출에 실패", self.error_text())


if __name__ == "__main__":
    unittest.main()
