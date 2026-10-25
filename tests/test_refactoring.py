"""구조 정리 전후의 공개 계약과 중복 필드 갱신 회귀 검사."""
from dataclasses import replace, fields
from datetime import timedelta
from review_fixtures import with_review_units
from unittest.mock import patch
import unittest

from src.models import QueryOptions, FinancialRatios, AppError, FinancialStatementData, RelatedStockSummary, MetricValue
from src.config import Settings
from src.analysis_flow import needs_data, analysis_message
from src.agents.chat import answer_question, build_evidence
from src.diagnostics import record_failure
from src.ui.state import store_analysis_result, prepare_analysis_request, add_canvas
from src.pipeline import analyze_selected_stock
from test_excel_export import _make_sample_result
import test_user_flow as flow


class AliasRegressionTests(unittest.TestCase):
    def test_period_round_trip_and_legacy_constructor(self):
        options = QueryOptions(price_range="1Y")
        for period in ("3M", "1Y", "3M"):
            options = replace(options, price_period=period)
            self.assertEqual((options.price_period, options.price_range), (period, period))

    def test_analysis_replacement_updates_and_clears_aliases(self):
        result = _make_sample_result()
        ratios = FinancialRatios(bsns_year="2026")
        updated = replace(result, financial_ratios=ratios)
        self.assertIs(updated.ratios, ratios)
        self.assertIsNone(replace(updated, financial_ratios=None).ratios)
        self.assertEqual(replace(updated, related_stocks=()).related_summaries, ())

    def test_alias_constructor_and_single_storage(self):
        base = _make_sample_result()
        legacy = type(base)(base.theme, base.candidates, base.financial, base.news,
                            base.commentary, ratios=base.ratios)
        self.assertIs(legacy.financial_ratios, base.ratios)
        self.assertNotIn("price_range", {f.name for f in fields(QueryOptions)})
        self.assertNotIn("ratios", {f.name for f in fields(type(base))})

    def test_statement_and_related_aliases_do_not_retain_removed_data(self):
        base = _make_sample_result()
        statement = FinancialStatementData("005930", "00126380", "2025", "11011", "CFS")
        peer = RelatedStockSummary(stock=base.financial.stock)
        legacy = type(base)(base.theme, base.candidates, base.financial, base.news, base.commentary,
                            statements=statement, related_summaries=(peer,))
        self.assertEqual(legacy.financial_statements, (statement,))
        self.assertEqual(legacy.related_stocks, (peer,))
        cleared = replace(legacy, financial_statements=(), related_stocks=())
        self.assertIsNone(cleared.statements)
        self.assertEqual(cleared.related_summaries, ())


class RequestBoundaryTests(unittest.TestCase):
    def setUp(self):
        self.result = _make_sample_result()
        self.now = self.result.financial.retrieved_at

    def test_finance_collection_uses_status_not_display_wording(self):
        missing = replace(self.result, financial=replace(self.result.financial,
                          collection_status="not_collected", warnings=("표시 문구 변경",)))
        self.assertTrue(needs_data(missing, "finance", "현재 주가", now=self.now))
        collected = replace(self.result, financial=replace(self.result.financial,
                            warnings=("다른 정보는 아직 조회하지 않았습니다.",)))
        self.assertFalse(needs_data(collected, "finance", "현재 주가", now=self.now))
        self.assertFalse(needs_data(collected, "finance", "현재 주가", now=self.now+timedelta(seconds=300)))
        self.assertTrue(needs_data(collected, "finance", "현재 주가", now=self.now+timedelta(seconds=301)))

    def test_scope_period_concept_and_dart_configuration(self):
        self.assertFalse(needs_data(self.result, "news", "뉴스", now=self.now))
        self.assertTrue(needs_data(self.result, "news", "뉴스", now=self.now+timedelta(seconds=901)))
        self.assertTrue(needs_data(self.result, "history", "차트", "1Y", now=self.now))
        self.assertFalse(needs_data(self.result, "history", "차트", "3M", now=self.now))
        self.assertFalse(needs_data(self.result, "finance", "PER의 뜻", now=self.now+timedelta(days=1)))
        missing = replace(self.result, section_status={"dart": "not_collected"})
        self.assertFalse(needs_data(missing, "financials", "실적", now=self.now, dart_enabled=False))
        self.assertTrue(needs_data(missing, "financials", "실적", now=self.now, dart_enabled=True))

    def test_refresh_preserves_snapshot_and_pending_question(self):
        state = {"selected_code": self.result.target_code, "query_options": QueryOptions(price_period="1Y")}
        store_analysis_result(state, self.result, "old")
        add_canvas(state, self.result)
        prepare_analysis_request(state, scope="history", question="3개월 차트", period="3M", refresh=True)
        self.assertEqual(state["request_scope"], "history")
        self.assertEqual(state["pending_question"], "3개월 차트")
        self.assertEqual(state["query_options"].price_period, "3M")
        self.assertEqual(state["query_options"].refresh_generation, 1)
        self.assertEqual(state["canvases"][0]["result"], self.result)
        self.assertEqual(state["pending_previous_result"], self.result)

    def test_report_message_keeps_sections_and_deduplicates_evidence(self):
        text, refs = analysis_message(self.result)
        self.assertTrue(text.startswith("**삼성전자 조회 결과**"))
        self.assertIn("**종합 분석**", text)
        self.assertIn("**재무 분석**", text)
        ids = [r["id"] for r in refs]
        self.assertEqual(ids[:4], ["PRICE", "PER", "PBR", "ROE"])
        self.assertEqual(ids.count("NEWS_1"), 1)

    def test_roe_fallback_is_same_in_chat_and_display(self):
        metric = MetricValue("ROE", 8.5, "%")
        result = replace(self.result, financial_ratios=FinancialRatios(),
                         financial=replace(self.result.financial, roe_metric=metric))
        from src.models import resolve_roe_metric
        self.assertIs(resolve_roe_metric(result), metric)
        self.assertEqual(build_evidence(result)["ROE"]["value"], 8.5)


class AnswerRetryTests(unittest.TestCase):
    def setUp(self):
        self.result = _make_sample_result()
        self.settings = Settings("fake", "model", "fake", "fake")

    def test_reviewer_auth_and_quota_errors_are_not_retried_or_hidden(self):
        valid = {"text": "현재 PER는 {{PER}}입니다.", "evidence_ids": ["PER"], "follow_up": ""}
        for code in ("ai_auth", "ai_rate_limit"):
            with self.subTest(code=code), patch("src.agents.chat._invoke", side_effect=with_review_units([valid, AppError(code, "안내")])) as invoke:
                with self.assertRaises(AppError) as caught:
                    answer_question("현재 PER를 해석해줘", self.result, [], self.settings)
                self.assertEqual(caught.exception.code, code)
                self.assertEqual(invoke.call_count, 2)

    def test_news_retry_feedback_stays_on_news(self):
        invalid = {"text": "미확인 숫자 999입니다.", "evidence_ids": ["NEWS_1"], "follow_up": ""}
        valid = {"text": "제목에서 반도체 수출 관련 소식을 확인했습니다.", "evidence_ids": ["NEWS_1"], "follow_up": ""}
        with patch("src.agents.chat._invoke", side_effect=with_review_units([invalid, valid, {"checks": {'evidence_match': True, 'time_basis': True, 'question_focus': True, 'explanation': True, 'scope_disclosed': True, 'context_consistent': True}, "supported": True, "answers_question": True}])) as invoke:
            answer_question("이 종목의 뉴스 설명", self.result, [], self.settings)
        feedback = invoke.call_args_list[1].args[2]["validation_feedback"]
        self.assertIn("제목", feedback)
        self.assertNotIn("낮은 PER", feedback)
        self.assertEqual(invoke.call_count, 3)

    def test_price_analysis_does_not_treat_price_as_a_glossary_term(self):
        valid = {"text": "현재 주가는 {{PRICE}}입니다.", "evidence_ids": ["PRICE"], "follow_up": ""}
        with patch("src.agents.chat._invoke", side_effect=with_review_units([valid, {"checks": {'evidence_match': True, 'time_basis': True, 'question_focus': True, 'explanation': True, 'scope_disclosed': True, 'context_consistent': True}, "supported": True, "answers_question": True}])) as invoke:
            answer, refs, _ = answer_question("현재 주가를 어떻게 해석합니까?", self.result, [], self.settings)
        self.assertIn("70,000.00원", answer)
        self.assertEqual(refs[0]["id"], "PRICE")
        self.assertEqual(invoke.call_args_list[0].args[2]["concept_reference"], {})


class ScopedCollectionTests(unittest.TestCase):
    def test_only_requested_sources_run_and_preserved_sources_keep_their_values(self):
        result = _make_sample_result()
        settings = Settings("fake", "model", "fake", "fake", dart_api_key="fake")
        for scope in ("all", "finance", "news", "history", "financials"):
            with self.subTest(scope=scope), \
                 patch("src.pipeline.fetch_financial", return_value=result.financial) as finance, \
                 patch("src.pipeline.fetch_news", return_value=result.news) as news, \
                 patch("src.pipeline.fetch_price_history", return_value=result.price_history) as history, \
                 patch("src.pipeline.fetch_related_stock_summaries", return_value=()) as related, \
                 patch("src.pipeline.collect_company_financials", return_value={"status": "empty"}) as dart, \
                 patch("src.pipeline.generate_commentary", return_value=result.commentary) as report:
                updated = analyze_selected_stock(result.theme, result.candidates, result.target_code,
                                                 settings=settings, scope=scope, previous=result)
            self.assertEqual(finance.call_count, int(scope in {"all", "finance"}))
            self.assertEqual(news.call_count, int(scope in {"all", "news"}))
            self.assertEqual(history.call_count, int(scope in {"all", "history"}))
            self.assertEqual(related.call_count, history.call_count)
            self.assertEqual(dart.call_count, int(scope in {"all", "financials"}))
            self.assertEqual(report.call_count, int(scope == "all"))
            self.assertNotEqual(updated.result_id, result.result_id)
            self.assertEqual(updated.target_code, result.target_code)
            self.assertEqual(updated.financial, result.financial)
            self.assertEqual(updated.news, result.news)


class SafeDiagnosticTests(unittest.TestCase):
    def test_only_allowed_codes_types_and_generated_reference_are_recorded(self):
        secret = "Authorization Bearer private-key user-question attachment-content"
        with self.assertLogs("ai_agent.diagnostics", level="WARNING") as records:
            record_failure("chat", AppError("ai_auth", secret), result_id="a"*32)
            record_failure("export", RuntimeError(secret), result_id=secret)
            record_failure(secret, AppError(secret, secret))
        output = " ".join(records.output)
        self.assertIn("stage=chat type=AppError code=ai_auth", output)
        self.assertIn("stage=export type=RuntimeError", output)
        self.assertNotIn(secret, output)
        self.assertIn("result_id="+"a"*32, output)

    def test_logging_failure_does_not_replace_application_error_handling(self):
        with patch("src.diagnostics.logger.warning", side_effect=RuntimeError("handler failed")):
            record_failure("analysis", ValueError("private response"))


class DiagnosticFlowTests(unittest.TestCase):
    setUp = flow.UserFlowTests.setUp
    set_responses = flow.UserFlowTests.set_responses
    submit_theme = flow.UserFlowTests.submit_theme
    select_stock = flow.UserFlowTests.select_stock
    open_canvas = flow.UserFlowTests.open_canvas
    assert_no_exception = flow.UserFlowTests.assert_no_exception

    def test_export_failures_record_stage_without_losing_result_or_leaking_response(self):
        self.submit_theme()
        self.select_stock("005930")
        self.open_canvas()
        original_id = self.app.session_state["dashboard_result"].result_id
        for error in (AppError("ai_failed", "private provider response"), ValueError("private parse body"), RuntimeError("private code body")):
            with self.subTest(error=type(error).__name__), \
                 patch("src.ui.state.build_workbook_bytes", side_effect=error), \
                 self.assertLogs("ai_agent.diagnostics", level="WARNING") as records:
                self.app.button(key="prepare_export_c1").click().run()
            self.assert_no_exception()
            self.assertEqual(self.app.session_state["dashboard_result"].result_id, original_id)
            self.assertEqual(len(self.app.session_state["canvases"]), 1)
            self.assertIn("stage=export", " ".join(records.output))
            self.assertNotIn("private", " ".join(records.output))

    def test_request_and_analysis_errors_preserve_existing_canvas(self):
        self.submit_theme()
        self.select_stock("005930")
        self.open_canvas()
        original = self.app.session_state["canvases"][0]["result"].result_id
        with patch("src.pipeline.discover_theme_candidates", side_effect=AppError("ai_auth", "인증 확인")), \
             self.assertLogs("ai_agent.diagnostics", level="WARNING") as records:
            self.submit_theme("자동차 테마 찾아줘")
        self.assertIn("stage=chat", " ".join(records.output))
        self.assertEqual(self.app.session_state["canvases"][0]["result"].result_id, original)
        with patch("src.pipeline.analyze_selected_stock", side_effect=ValueError("private raw provider body")), \
             self.assertLogs("ai_agent.diagnostics", level="WARNING") as records:
            self.app.button(key="refresh_selected").click().run()
        self.assert_no_exception()
        self.assertIn("stage=analysis type=ValueError", " ".join(records.output))
        self.assertNotIn("private", " ".join(records.output))
        self.assertEqual(self.app.session_state["canvases"][0]["result"].result_id, original)

    def test_pending_answer_failure_keeps_newly_collected_data(self):
        self.submit_theme()
        self.select_stock("005930")
        with patch("src.agents.chat.answer_question", side_effect=RuntimeError("private internal state")), \
             self.assertLogs("ai_agent.diagnostics", level="WARNING") as records:
            self.submit_theme("예시회사 뉴스 다시 조회해줘")
        self.assertIn("stage=pending_answer", " ".join(records.output))
        self.assertNotIn("private", " ".join(records.output))
        self.assertIn("dashboard_result", self.app.session_state)
        self.assertTrue(self.app.session_state["dashboard_result"].news.articles)
        self.assertIn("요청한 자료는 보관했습니다", self.app.session_state["chat_messages"][-1]["text"])


if __name__ == "__main__":
    unittest.main()
