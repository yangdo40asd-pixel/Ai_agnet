"""실제 연동 검사에서 발견한 AI 응답 문제의 재발 방지 검사. 외부 호출 없음."""

import unittest
from dataclasses import replace
from unittest.mock import patch
from types import SimpleNamespace
import json

import pandas as pd

from src.agents.report import generate_commentary, _invoke, response_format, _comment_text, validate_report
from src.config import Settings
from src.models import AppError
from src.data.stock import supplement_trailing_per, fetch_financial, candidate_options
from src.models import StockCandidate
from src.data.news import news_query
from src.pipeline import analyze_theme
from test_report_pipeline import example_financial, example_news, example_payload


class LiveRegressionTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings("test", "test", "test", "test")

    def generate(self):
        return generate_commentary("로봇", example_financial(), example_news(), self.settings)

    def test_news_year_in_text_gets_one_validated_rewrite(self):
        invalid = example_payload()
        invalid["theme_trend"][0]["text"] = "2026 로보월드 관련 소식입니다."
        with patch("src.agents.report._invoke", side_effect=[invalid, example_payload()]) as invoke:
            result = self.generate()
        self.assertEqual(invoke.call_count, 2)
        self.assertIn("revision_reason", invoke.call_args.args[2])
        self.assertEqual(result.theme_trend[0].news_ids, (1,))

    def test_rewrite_still_rejects_numbers_and_stops_after_one_retry(self):
        invalid = example_payload()
        invalid["summary"]["text"] = "2026 행사 소식입니다."
        with patch("src.agents.report._invoke", return_value=invalid) as invoke:
            with self.assertRaises(AppError) as error:
                self.generate()
        self.assertEqual(error.exception.code, "report_unverified")
        self.assertEqual(invoke.call_count, 2)

    def test_api_failure_is_not_retried(self):
        with patch("src.agents.report._invoke", side_effect=AppError("ai_failed", "호출 실패")) as invoke:
            with self.assertRaises(AppError):
                self.generate()
        self.assertEqual(invoke.call_count, 1)

    def test_rewrite_cannot_change_financial_values(self):
        invalid = example_payload()
        invalid["summary"]["text"] = "2026 행사 소식입니다."
        changed = example_payload()
        changed["price"] = 1
        with patch("src.agents.report._invoke", side_effect=[invalid, changed]):
            with self.assertRaises(AppError) as error:
                self.generate()
        self.assertEqual(error.exception.code, "report_numbers")

    def test_ai_echo_uses_display_precision_without_changing_raw_per(self):
        financial = replace(example_financial(), per=-971.8608716546611)
        payload = example_payload()
        payload["per"] = -971.86
        with patch("src.agents.report._invoke", return_value=payload) as invoke:
            generate_commentary("로봇", financial, example_news(), self.settings)
        self.assertEqual(invoke.call_args.args[2]["per"], -971.86)
        self.assertEqual(financial.per, -971.8608716546611)
        payload["per"] = -971.85
        with self.assertRaises(AppError):
            validate_report(payload, financial, example_news())


class TrailingPerTests(unittest.TestCase):
    def missing(self):
        return replace(example_financial(), per=None, warnings=("PER 정보가 없습니다.",))

    def income(self, eps=1000):
        return pd.DataFrame({pd.Timestamp("2026-06-30"): {"DilutedEPS": eps}})

    def test_missing_per_uses_trailing_eps_with_disclosed_period(self):
        result = supplement_trailing_per(self.missing(), self.income())
        self.assertEqual(result.per, 70)
        self.assertEqual(result.per_eps, 1000)
        self.assertEqual(result.per_period_end, "2026-06-30")
        self.assertEqual(result.warnings, ())

    def test_loss_is_kept_and_explained(self):
        result = supplement_trailing_per(self.missing(), self.income(-1000))
        self.assertEqual(result.per, -70)
        self.assertIn("음수", result.warnings[0])

    def test_bad_or_zero_eps_stays_missing(self):
        for eps in [0, None, float("nan"), float("inf"), True, "1000"]:
            with self.subTest(eps=eps):
                self.assertIsNone(supplement_trailing_per(self.missing(), self.income(eps)).per)

    def test_missing_latest_eps_does_not_take_older_period(self):
        income = self.income()
        income[pd.Timestamp("2026-09-30")] = float("nan")
        self.assertIsNone(supplement_trailing_per(self.missing(), income).per)

    def test_future_period_or_invalid_frame_stays_missing(self):
        for income in [None, pd.DataFrame(), self.income().rename(columns={pd.Timestamp("2026-06-30"):pd.Timestamp("2099-01-01")})]:
            self.assertIsNone(supplement_trailing_per(self.missing(), income).per)

    def test_existing_per_is_not_replaced(self):
        original = example_financial()
        self.assertIs(supplement_trailing_per(original, self.income()), original)

    def test_financial_currency_must_match_before_eps_request(self):
        with patch("yfinance.Ticker") as ticker:
            ticker.return_value.get_info.return_value = {
                "symbol":"005930.KS", "currency":"KRW", "regularMarketPrice":70000,
                "financialCurrency":"USD", "forwardPE":12,
            }
            result = fetch_financial(example_financial().stock)
        self.assertIsNone(result.per)
        ticker.return_value.get_income_stmt.assert_not_called()


class RealRequestRegressionTests(unittest.TestCase):
    def test_oss_client_initialization_and_candidate_response(self):
        response = SimpleNamespace(content='{"stocks":["회사A","회사B","회사C"]}', response_metadata={})
        # 클라이언트 생성은 실제로 수행하고 전송만 대체해 설정 인자 오류도 확인한다.
        with patch("langchain_groq.ChatGroq.invoke", return_value=response):
            result = _invoke(Settings("test","openai/gpt-oss-20b","test","test"), "JSON", {"theme":"로봇"}, 250)
        self.assertEqual(len(result["stocks"]), 3)

    def test_provider_schema_failure_retries_json_but_does_not_edit_response(self):
        error = RuntimeError("provider error")
        error.status_code = 400
        error.body = {"error":{"code":"json_validate_failed"}}
        response = SimpleNamespace(content='{"stocks":["회사A","회사B","회사C"]}', response_metadata={})
        with patch("langchain_groq.ChatGroq") as groq:
            groq.return_value.invoke.side_effect = [error, response]
            result = _invoke(Settings("test","test","test","test"), "JSON", {"theme":"로봇"}, 250)
        self.assertEqual(groq.return_value.invoke.call_count, 2)
        self.assertEqual(groq.return_value.invoke.call_args.kwargs["response_format"], {"type":"json_object"})
        self.assertEqual(result, {"stocks":["회사A","회사B","회사C"]})

    def test_sidecar_market_term_is_not_a_trading_recommendation(self):
        self.assertEqual(_comment_text("매도 사이드카가 발동됐다는 제목이 확인됩니다."), "매도 사이드카가 발동됐다는 제목이 확인됩니다.")
        with self.assertRaises(AppError):
            _comment_text("매도 사이드카 발동은 매수 기회입니다.")

    def test_candidate_options_are_official_supported_names_not_fuzzy_matches(self):
        listing = pd.DataFrame([
            {"Name":"로보티즈", "Code":"108490", "Market":"KOSDAQ"},
            {"Name":"로보로보", "Code":"215100", "Market":"KOSDAQ"},
            {"Name":"유진로봇", "Code":"056080", "Market":"KOSDAQ"},
            {"Name":"제외로봇", "Code":"000001", "Market":"KONEX"},
        ])
        candidates = (StockCandidate("로보티즈", "108490", "KOSDAQ", "108490.KQ"), StockCandidate("없는회사"))
        self.assertEqual(candidate_options("로봇", candidates, listing), ("로보티즈", "유진로봇", "로보로보"))

    def test_candidate_schema_constrains_reproposal_to_given_names(self):
        payload = {"theme":"로봇", "available_names":["로보티즈", "유진로봇", "클로봇"]}
        schema = response_format(payload, "qwen/qwen3.8-27b")["json_schema"]["schema"]
        self.assertEqual(schema["properties"]["stocks"]["items"]["enum"], payload["available_names"])

    def test_strict_report_schema_uses_actual_news_ids_and_financial_values(self):
        payload = {"headlines":[{"id":2}], "stock_name":"예시회사", "price":70000, "per":None}
        schema = response_format(payload, "qwen/qwen3.8-27b")["json_schema"]
        self.assertTrue(schema["strict"])
        properties = schema["schema"]["properties"]
        self.assertEqual(properties["price"]["enum"], [70000])
        self.assertEqual(properties["per"]["type"], "null")
        self.assertEqual(properties["theme_trend"]["maxItems"], 2)
        self.assertEqual(properties["stock_comment"]["pattern"], "^[^0-9]*$")
        self.assertEqual(properties["risk"]["properties"]["news_ids"]["items"]["enum"], [2])
        self.assertEqual(response_format({}, "other-model"), {"type":"json_object"})

    def test_strict_no_news_schema_requires_empty_insights(self):
        payload = {"headlines":[], "stock_name":"예시회사", "price":70000, "per":None}
        properties = response_format(payload, "qwen/qwen3.8-27b")["json_schema"]["schema"]["properties"]
        self.assertEqual(properties["theme_trend"]["maxItems"], 0)
        self.assertEqual(properties["summary"], {"type":"null"})

    def test_chat_request_words_do_not_pollute_news_query(self):
        for theme in ["반도체 테마주 분석해줘", "반도체 분석해주세요", "반도체 관련주", "반도체"]:
            self.assertEqual(news_query(theme, "삼성전자"), "반도체 삼성전자")
        self.assertEqual(news_query("2차전지", "LG에너지솔루션"), "2차전지 LG에너지솔루션")

    def rate_error(self, delay):
        error = RuntimeError("private provider response")
        error.status_code = 429
        error.response = SimpleNamespace(headers={"retry-after": delay})
        return error

    def test_short_rate_limit_retries_once_without_leaking_error(self):
        response = SimpleNamespace(content=json.dumps({"ok":True}), response_metadata={})
        with patch("langchain_groq.ChatGroq") as groq, patch("src.agents.transport.time.sleep") as sleep:
            groq.return_value.invoke.side_effect = [self.rate_error("1"), response]
            result = _invoke(Settings("test","test","test","test"), "test", {}, 20)
        self.assertEqual(result, {"ok":True})
        self.assertEqual(groq.return_value.invoke.call_count, 2)
        self.assertEqual(groq.call_args.kwargs["model_kwargs"]["response_format"], {"type":"json_object"})
        sleep.assert_called_once_with(1.2)

    def test_long_or_repeated_rate_limit_stops_with_clear_message(self):
        for failures in [[self.rate_error("60")], [self.rate_error("0"), self.rate_error("0")]]:
            with patch("langchain_groq.ChatGroq") as groq, patch("src.agents.transport.time.sleep"):
                groq.return_value.invoke.side_effect = failures
                with self.assertRaises(AppError) as error:
                    _invoke(Settings("test","test","test","test"), "test", {}, 20)
                self.assertEqual(error.exception.code, "ai_rate_limit")
                self.assertNotIn("private", error.exception.message)
                self.assertEqual(groq.return_value.invoke.call_count, len(failures))

    def test_unlisted_candidate_is_reproposed_and_revalidated(self):
        names = ("예시회사", "회사나", "회사다")
        listing = pd.DataFrame([{"Name":n,"Code":c,"Market":"KOSPI"} for n,c in zip(names,["005930","000660","000990"])])
        with (patch("src.pipeline.load_settings", return_value=Settings("test", "test-model", "test", "test")),
              patch("src.pipeline.propose_candidates", side_effect=[("없는회사", "회사나", "회사다"), names]) as propose,
              patch("src.pipeline.load_listing", return_value=listing) as load,
              patch("src.pipeline.fetch_financial", return_value=example_financial()),
              patch("src.pipeline.fetch_news", return_value=example_news()),
              patch("src.pipeline.generate_commentary", return_value=None)):
            result = analyze_theme("로봇")
        self.assertTrue(all(x.verified for x in result.candidates))
        self.assertEqual(propose.call_count, 2)
        self.assertEqual(propose.call_args.kwargs["rejected_names"], ("없는회사",))
        load.assert_called_once()

    def test_reproposal_does_not_accept_another_unlisted_name(self):
        listing = pd.DataFrame([{"Name":"회사나","Code":"005930","Market":"KOSPI"}])
        with (patch("src.pipeline.load_settings", return_value=Settings("test", "test-model", "test", "test")),
              patch("src.pipeline.propose_candidates", side_effect=[("없는회사","회사나","회사다"), ("또없는회사","회사나","회사다")]) as propose,
              patch("src.pipeline.load_listing", return_value=listing),
              patch("src.pipeline.fetch_financial") as finance):
            with self.assertRaises(AppError) as error:
                analyze_theme("로봇")
        self.assertEqual(error.exception.code, "stock_unconfirmed")
        self.assertEqual(propose.call_count, 2)
        finance.assert_not_called()

    def test_income_api_failure_preserves_price(self):
        with patch("yfinance.Ticker") as ticker:
            ticker.return_value.get_info.return_value = {
                "symbol":"005930.KS", "currency":"KRW", "regularMarketPrice":70000,
                "financialCurrency":"KRW", "forwardPE":12,
            }
            ticker.return_value.get_income_stmt.side_effect = RuntimeError("provider unavailable")
            result = fetch_financial(example_financial().stock)
        self.assertEqual(result.price, 70000)
        self.assertIsNone(result.per)
