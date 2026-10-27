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


def report_payload(per=15.2, news=True, stock_name="예시회사", price=70000):
    statement = {"text": "관련 소식이 관심을 높일 가능성이 있습니다.", "news_ids": [1]}
    return {
        "stock_name": stock_name,
        "price": price,
        "per": per,
        "theme_trend": [copy.deepcopy(statement)] if news else [],
        "stock_comment": "이 지표만으로 기업 가치를 단정하기 어렵습니다.",
        "opportunity": copy.deepcopy(statement) if news else None,
        "risk": copy.deepcopy(statement) if news else None,
        "summary": copy.deepcopy(statement) if news else None,
    }


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

    def submit_theme(self, theme="반도체 테마 찾아줘"):
        self.app.text_input(key="composer_text").set_value(theme)
        self.app.button(key="composer_submit").click().run()
        self.assert_no_exception()

    def open_canvas(self):
        self.app.button(key="add_canvas").click().run()
        self.assert_no_exception()

    def select_stock(self, code):
        buttons = [el for el in self.app.button if el.key == f"msg_select_{code}"]
        selectors = [el for el in self.app.selectbox if el.key == "candidate_selector"]
        if buttons and not buttons[0].disabled:
            buttons[0].click().run()
        elif selectors and code in selectors[0].options:
            selectors[0].select(code).run()
        else:
            self.app.session_state["selected_code"] = code
            self.app.run()
        self.assert_no_exception()

    def submit(self, theme="반도체", code=None):
        request = theme if not theme.strip() or "찾아" in theme or "분석해" in theme else f"{theme} 테마 찾아줘"
        self.submit_theme(request)
        if "candidate_result" in self.app.session_state and "latest_error" not in self.app.session_state:
            discovery = self.app.session_state["candidate_result"]
            if discovery.candidates:
                target_code = code if code is not None else (discovery.candidates[0].code or discovery.candidates[0].name)
                self.select_stock(target_code)
                if "dashboard_result" in self.app.session_state:
                    self.open_canvas()

    def assert_no_exception(self):
        self.assertEqual(len(self.app.exception), 0, [element.message for element in self.app.exception])

    def error_text(self):
        return " ".join(element.value for element in self.app.error)

    def test_initial_screen_does_not_call_services(self):
        self.assertEqual(len(self.app.chat_input), 0)
        self.assertEqual(len(self.app.text_input), 1)
        self.assertEqual(len(self.app.metric), 0)
        self.assertFalse(any(element.key == "add_canvas" for element in self.app.button))
        self.assertTrue(any(element.key == "suggested_prompt_0" for element in self.app.button))
        self.assertTrue(any("관심 테마나 종목" in item.value for item in self.app.caption))
        self.assertEqual(sum(str(element.key).startswith("suggested_prompt_") for element in self.app.button), 3)
        self.llm.invoke.assert_not_called()
        self.listing.assert_not_called()
        self.news_request.assert_not_called()

    def test_theme_submission_enters_selection_waiting_state_before_detail_calls(self):
        self.submit_theme("반도체 테마 찾아줘")
        self.assertEqual(len(self.app.dataframe), 1)
        self.assertEqual(len(self.app.dataframe[0].value), 3)
        self.assertEqual(len(self.app.metric), 0)
        self.assertEqual(len(self.app.success), 0)
        self.assertTrue(any("분석할 종목을 선택해 주세요" in item.value for item in self.app.info))
        self.assertEqual(self.llm.invoke.call_count, 1)
        self.listing.assert_called_once()
        self.ticker.assert_not_called()
        self.news_request.assert_not_called()

    def test_normal_theme_runs_complete_pipeline_and_renders_sources(self):
        self.submit()
        self.assertIsNotNone(self.app.session_state["dashboard_result"].commentary)
        self.assertEqual(self.app.session_state["request_status"], "partial")
        self.assertEqual([metric.value for metric in self.app.metric[:2]], ["70,000원", "15.20배"])
        self.assertEqual(len(self.app.metric), 6)
        self.assertEqual(len(self.app.dataframe[0].value), 3)
        self.assertEqual(self.app.dataframe[0].value.iloc[1]["시장"], "KOSDAQ")
        self.assertEqual(self.llm.invoke.call_count, 2)
        self.ticker.assert_any_call("005930.KS")
        links = [element.proto.url for element in self.app.get("link_button")]
        self.assertIn("https://example.com/news", links)
        self.assertTrue(any("조회 시각" in element.value for element in self.app.caption))
        analysis_message = next(
            item for item in reversed(self.app.session_state["chat_messages"])
            if item.get("result_id")
        )
        self.assertIn("종합 분석", analysis_message["text"])
        self.assertFalse(analysis_message.get("follow_up"))
        self.assertTrue(analysis_message.get("evidence"))

    def test_selecting_second_or_third_candidate_updates_title_ticker_news_and_ai(self):
        self.info["symbol"] = "247540.KQ"
        self.info["regularMarketPrice"] = 125000
        self.info["currentPrice"] = 125000
        self.info["trailingPE"] = 22.5
        self.set_responses(
            ["예시회사", "회사나", "회사다"],
            report_payload(per=22.5, stock_name="회사나", price=125000),
        )
        self.submit("2차전지", code="247540")
        self.assertIsNotNone(self.app.session_state["dashboard_result"].commentary)
        self.assertEqual(self.app.session_state["request_status"], "partial")
        self.ticker.assert_any_call("247540.KQ")
        self.assertEqual(self.news_request.call_args.kwargs["params"]["query"], "2차전지 회사나")
        self.assertEqual([metric.value for metric in self.app.metric[:2]], ["125,000원", "22.50배"])
        table = self.app.dataframe[0].value
        self.assertEqual(table.iloc[1]["분석 대상"], "대표 종목 (선택됨)")
        self.assertEqual(table.iloc[0]["분석 대상"], "선택 가능")
        markdown_text = " ".join(el.value for el in self.app.markdown)
        self.assertIn("회사나", markdown_text)
        self.assertIn("247540", markdown_text)

    def test_related_candidate_button_switches_selection_without_reproposing(self):
        self.llm.invoke.side_effect = [
            response({"stocks": ["예시회사", "회사나", "회사다"]}),
            response(report_payload(per=15.2, stock_name="예시회사", price=70000)),
            response(report_payload(per=18.0, stock_name="회사다", price=90000)),
        ]
        self.submit("반도체", code="005930")
        self.assertEqual(self.app.session_state["selected_code"], "005930")

        # Update mock for third candidate 000660
        self.info["symbol"] = "000660.KS"
        self.info["regularMarketPrice"] = 90000
        self.info["currentPrice"] = 90000
        self.info["trailingPE"] = 18.0
        self.app.button(key="c1_result_related_000660").click().run()
        self.assert_no_exception()
        self.open_canvas()

        self.assertEqual(self.app.session_state["selected_code"], "000660")
        self.assertEqual(self.listing.call_count, 1)
        self.assertEqual(self.llm.invoke.call_count, 3)  # 1 candidate proposal + 2 reports
        self.assertEqual([metric.value for metric in self.app.metric[:2]], ["90,000원", "18.00배"])
        self.assertEqual(self.app.dataframe[0].value.iloc[2]["분석 대상"], "대표 종목 (선택됨)")

    def test_switching_stock_when_second_fails_clears_first_stock_result(self):
        self.submit("반도체", code="005930")
        self.assertEqual(len(self.app.metric), 6)
        self.app.session_state["export_bytes"] = b"old-excel-bytes"

        # Now switch to second candidate (247540), where financial fetch fails
        self.ticker.return_value.get_info.side_effect = RuntimeError("provider failure")
        self.select_stock("247540")

        self.assertEqual(len(self.app.metric), 6)
        self.assertNotIn("dashboard_result", self.app.session_state)
        self.assertNotIn("export_bytes", self.app.session_state)
        self.assertEqual(len(self.app.session_state["canvases"]), 1)
        self.assertIn("주가·PER 조회에 실패", self.error_text())

    def test_refresh_selected_button_requeries_current_stock_only(self):
        self.llm.invoke.side_effect = [
            response({"stocks": ["예시회사", "회사나", "회사다"]}),
            response(report_payload(per=15.2, stock_name="예시회사", price=70000)),
            response(report_payload(per=16.0, stock_name="예시회사", price=71000)),
        ]
        self.submit("반도체", code="005930")
        initial_calls = self.ticker.call_count
        self.assertGreaterEqual(initial_calls, 1)

        self.info["regularMarketPrice"] = 71000
        self.info["currentPrice"] = 71000
        self.info["trailingPE"] = 16.0
        self.app.button(key="refresh_selected").click().run()
        self.assert_no_exception()
        self.open_canvas()

        self.assertEqual(self.listing.call_count, 1)
        self.assertGreater(self.ticker.call_count, initial_calls)
        self.assertEqual([metric.value for metric in self.app.metric[:2]], ["71,000원", "16.00배"])

    def test_out_of_candidate_code_is_rejected_before_external_calls(self):
        self.submit_theme("반도체 테마 찾아줘")
        self.select_stock("999999")
        self.assertIn("후보 목록에 없습니다", self.error_text())
        self.ticker.assert_not_called()
        self.news_request.assert_not_called()
        self.assertEqual(len(self.app.metric), 0)

    def test_kosdaq_target_uses_kq_code(self):
        self.info["symbol"] = "247540.KQ"
        payload = report_payload()
        payload["stock_name"] = "회사나"
        self.set_responses(["회사나", "예시회사", "회사다"], payload)
        self.submit("2차전지")
        self.ticker.assert_any_call("247540.KQ")
        self.assertIsNotNone(self.app.session_state["dashboard_result"].commentary)
        self.assertEqual(self.app.session_state["request_status"], "partial")

    def test_numeric_theme_name_in_ai_text_does_not_fail(self):
        payload = report_payload()
        payload["risk"]["text"] = "2차전지 관련 소식은 추가 확인이 필요합니다."
        self.set_responses(report=payload)
        self.submit("2차전지 테마주 분석해줘")
        self.assertIsNotNone(self.app.session_state["dashboard_result"].commentary)
        self.assertEqual(self.app.session_state["request_status"], "partial")
        self.assertEqual(len(self.app.error), 0)

    def test_partly_unreadable_news_displays_partial_result(self):
        self.news_response.json.return_value["items"].append({"title": None})
        self.submit()
        self.assertEqual(len(self.app.metric), 6)
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
        self.llm.invoke.side_effect = [
            response({"stocks": ["없는회사", "회사나", "회사다"]}),
            response({"stocks": ["없는회사", "회사나", "회사다"]}),
        ]
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
        self.assertEqual(len(self.app.metric), 6)
        self.assertEqual(len(self.app.success), 0)
        self.assertTrue(any("뉴스 제목을 확보하지 못해" in item.value for item in self.app.info))

    def test_news_auth_failure_keeps_financial_result(self):
        self.news_response.status_code = 401
        self.set_responses(report=report_payload(news=False))
        self.submit()
        self.assertTrue(any("인증" in item.value for item in self.app.warning))
        self.assertEqual(len(self.app.metric), 6)
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
        self.assertEqual(len(self.app.metric), 6)
        self.assertEqual(len(self.app.success), 0)

    def test_dashboard_renders_pbr_eps_bps_and_price_volume_chart(self):
        self.info.update({
            "financialCurrency": "KRW",
            "trailingEps": 4605.0,
            "bookValue": 51850.0,
            "priceToBook": 1.35,
        })
        self.ticker.return_value.history.return_value = pd.DataFrame(
            {
                "Open": [69000.0, 70000.0],
                "High": [70500.0, 71500.0],
                "Low": [68500.0, 69500.0],
                "Close": [70000.0, 71000.0],
                "Volume": [10000000, 12000000],
            },
            index=[pd.Timestamp("2026-10-15"), pd.Timestamp("2026-10-16")],
        )
        self.submit("반도체", code="005930")
        self.assertEqual(
            [metric.value for metric in self.app.metric],
            ["70,000원", "15.20배", "1.35배", "정보 없음", "4,605원", "51,850원"],
        )
        captions = " ".join(c.value for c in self.app.caption)
        self.assertIn("시세 이력 출처: Yahoo Finance", captions)
        self.assertIn("2026-10-15 ~ 2026-10-16 (2거래일)", captions)
        self.assertIn("무수정 시세(auto_adjust=False)", captions)

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

    def test_unresolved_new_theme_keeps_previous_result_and_explains_next_step(self):
        self.submit()
        self.llm.invoke.side_effect = RuntimeError("fake AI failure")
        self.submit_theme("다른 테마")
        self.assertIn("dashboard_result", self.app.session_state)
        self.assertEqual(len(self.app.session_state["canvases"]), 1)
        self.assertIn(
            "새로 살펴볼 테마",
            self.app.session_state["chat_messages"][-1]["text"],
        )


if __name__ == "__main__":
    unittest.main()
