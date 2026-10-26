"""계획5의 사용자 요구를 검증한다. 수치·회사명·외부 응답은 모두 가상 자료다."""
import unittest
from dataclasses import replace
from review_fixtures import with_review_units
from unittest.mock import patch
import pandas as pd

import test_user_flow as flow
from src.agents.chat import answer_question, build_evidence, validate_answer
from src.agents.request import route_message, discovery_theme
from src.agents.report import response_format
from src.config import Settings
from src.models import AnalysisResult, AppError, CandidateDiscoveryResult, FinancialData, NewsData, PriceHistory, PriceBar, StockCandidate, now_kst
from src.pipeline import analyze_selected_stock, identify_stock
from src.ui.state import add_canvas, store_analysis_result, store_candidate_discovery, suggested_prompts, historical_result, close_canvas
from src.ui.charts import aggregate_history


class Plan5Contracts(unittest.TestCase):
    def setUp(self):
        self.settings = Settings("test", "test-model", "", "")
        self.a = StockCandidate("예시회사", "005930", "KOSPI", "005930.KS")
        self.b = StockCandidate("회사나", "247540", "KOSDAQ", "247540.KQ")
        self.discovery = CandidateDiscoveryResult("반도체", (self.a, self.b), now_kst())
        self.result = AnalysisResult("반도체", (self.a, self.b), FinancialData(self.a, 10000, 12.5, now_kst()), NewsData((), now_kst()), None, result_id="a1")

    def test_natural_discovery_is_executed_and_explicit_form_overrides_keywords(self):
        with patch("src.agents.request._invoke", return_value={"action": "discover", "theme": "방산", "code": ""}):
            self.assertEqual(route_message("방산 쪽에는 어떤 종목이 있어?", None, None, [], self.settings).theme, "방산")
        with patch("src.agents.request._invoke") as call:
            intent = route_message("정보보안", None, None, [], self.settings, explicit_action="discover")
            self.assertEqual((intent.action, intent.theme), ("discover", "정보보안"))
            call.assert_not_called()

    def test_new_theme_and_concept_search_and_news_refresh(self):
        cases = [("다른 테마로 방산 찾아줘", "discover", "all"), ("PER 뜻 찾아줘", "answer", "finance"),
                 ("이 회사 뉴스 다시 조회해줘", "refresh", "news")]
        for text, action, scope in cases:
            intent = route_message(text, self.discovery, self.a.code, [], self.settings)
            self.assertEqual((intent.action, intent.scope), (action, scope))
        self.assertEqual(discovery_theme("반도체 관련 종목을 찾아줘"), "반도체")

    def test_negated_theme_search_and_initial_concept_suggestion(self):
        with patch("src.agents.request._invoke", return_value={"action": "lookup", "theme": "", "code": "", "company": "삼성전자"}):
            intent = route_message("테마 검색 말고 삼성전자만 보고 싶습니다.", None, None, [], self.settings)
        self.assertEqual((intent.action, intent.company), ("lookup", "삼성전자"))
        question = next(p for p in suggested_prompts({}) if "PBR" in p)
        with patch("src.agents.request._invoke") as route, patch("src.agents.chat._invoke") as answer:
            self.assertEqual(route_message(question, None, None, [], self.settings).action, "answer")
            result, _, _ = answer_question(question, None, [], self.settings)
        self.assertIn("| 지표 |", result)
        route.assert_not_called(); answer.assert_not_called()

    def test_unsupported_average_and_disclosure_are_not_accepted(self):
        evidence = build_evidence(self.result)
        for text in ("PER는 평균 수준에 가깝습니다.", "EPS가 공개되지 않아 분석이 제한됩니다."):
            with self.subTest(text=text), self.assertRaises(AppError):
                validate_answer({"text": text, "evidence_ids": ["PER"], "follow_up": ""}, evidence)
        with patch("src.agents.chat._invoke", return_value={"text": "PER는 평균 수준에 가깝습니다.", "evidence_ids": ["PER"], "follow_up": ""}) as call:
            answer, refs, _ = answer_question("이 종목 PER을 어떻게 해석합니까?", self.result, [], self.settings)
        self.assertEqual(call.call_count, 2)
        self.assertIn("12.50배", answer)
        self.assertIn("미확인", refs[0]["period"])
        self.assertNotIn("자료 기준:", answer)
        self.assertEqual(refs[0]["answer_origin"], "verified_metric_fallback")

    def test_general_trading_explanation_checks_knowledge_reference(self):
        incorrect = {"text": "매수는 현재가보다 낮은 가격으로 사는 행위입니다.", "evidence_ids": [], "follow_up": ""}
        with patch("src.agents.chat._invoke", side_effect=with_review_units([incorrect, {"checks": {'evidence_match': False, 'time_basis': False, 'question_focus': False, 'explanation': False, 'scope_disclosed': False, 'context_consistent': False}, "supported": False, "answers_question": True, "reason": "direction_vs_order"},
                    {"text": "매수는 주식을 사는 행위이고 매도는 파는 행위입니다.", "evidence_ids": [], "follow_up": ""},
                    {"checks": {'evidence_match': True, 'time_basis': True, 'question_focus': True, 'explanation': True, 'scope_disclosed': True, 'context_consistent': True}, "supported": True, "answers_question": True, "reason": ""}])) as call:
            answer, _, _ = answer_question("매수와 매도의 차이는?", None, [], self.settings)
        self.assertNotIn("낮은", answer)
        self.assertIn("주문 방식", call.call_args.args[2]["concept_reference"])

    def test_candidate_summaries_fetch_distinct_unselected_history_and_keep_partial(self):
        c = StockCandidate("회사다", "000660", "KOSPI", "000660.KS")
        own = PriceHistory(self.a.code, self.a.ticker, (PriceBar("2026-10-01", 100, 110, 90, 100, 10),))
        other = PriceHistory(self.b.code, self.b.ticker, (PriceBar("2026-10-01", 200, 220, 180, 200, 20),))
        failed = PriceHistory(c.code, c.ticker, (), status="failed", message="조회 실패")
        with patch("src.pipeline.fetch_price_history", return_value=own), patch("src.data.history.fetch_price_history", side_effect=[other, failed]) as fetch:
            result = analyze_selected_stock("반도체", (self.a, self.b, c), self.a.code, scope="history", previous=self.result, settings=self.settings)
        self.assertEqual(fetch.call_count, 2)
        self.assertEqual(fetch.call_args_list[0].args, (self.b, "1M"))
        self.assertEqual([s.price for s in result.related_stocks], [100, 200, None])
        self.assertEqual(result.related_stocks[-1].status, "failed")
        self.assertEqual(result.section_status["commentary"], "not_requested")

    def test_chart_values_are_safe_placeholders(self):
        bars = (PriceBar("2026-10-01", 100, 110, 90, 100, 100), PriceBar("2026-10-02", 100, 110, 90, 105, 70))
        evidence = build_evidence(replace(self.result, price_history=PriceHistory(self.a.code, self.a.ticker, bars)))
        answer, _ = validate_answer({"text": "조회 구간 종가 변화율은 {{HISTORY_CHANGE}}입니다.", "evidence_ids": ["HISTORY_CHANGE"], "follow_up": ""}, evidence)
        self.assertIn("+5.00%", answer)
        from src.data.history import resolve_range_key
        self.assertEqual(resolve_range_key("3Y"), "3Y")
        self.assertEqual(resolve_range_key("5Y"), "5Y")

    def test_dart_identifier_failure_is_partial_data_not_nameerror(self):
        from src.data.financials import collect_company_financials
        with patch("src.data.financials.fetch_corp_codes", return_value={}), patch("src.data.financials.resolve_corp_code", side_effect=AppError("dart_lookup", "기업 식별 실패")):
            result = collect_company_financials(self.a, replace(self.settings, dart_api_key="test"))
        self.assertNotEqual(result["status"], "ok")

    def test_new_period_requeries_even_fresh_history(self):
        from src.ui.app import _needs_data
        history = PriceHistory(self.a.code, self.a.ticker, (PriceBar("2026-10-01", 100, 110, 90, 100, 100),))
        result = replace(self.result, price_history=history)
        self.assertFalse(_needs_data(result, "history", "차트를 설명해줘", "3M"))
        self.assertTrue(_needs_data(result, "history", "최근 1년 차트를 설명해줘", "1Y"))
        intent = route_message("최근 1년 주가 차트 보여줘", self.discovery, self.a.code, [], self.settings)
        self.assertEqual((intent.action, intent.scope, intent.period), ("answer", "history", "1Y"))
        intent = route_message("조회 기간의 주가와 거래량 변화를 설명해줘", self.discovery, self.a.code, [], self.settings)
        self.assertEqual((intent.action, intent.scope), ("answer", "history"))

    def test_metric_cause_question_is_not_replaced_by_value_only(self):
        with patch("src.agents.chat._invoke", side_effect=with_review_units([
            {"text": "현재 PER는 {{PER}}입니다. 과거 비교 자료가 없어 낮아진 원인은 확인할 수 없습니다.", "evidence_ids": ["PER"], "follow_up": ""},
            {"checks": {'evidence_match': True, 'time_basis': True, 'question_focus': True, 'explanation': True, 'scope_disclosed': True, 'context_consistent': True}, "supported": True, "answers_question": True, "reason": ""}])) as invoke:
            answer, _, _ = answer_question("PER가 왜 낮아졌는지 알려줘", self.result, [], self.settings)
        self.assertEqual(invoke.call_count, 2)
        self.assertIn("원인은 확인할 수 없습니다", answer)

    def test_explicit_different_company_requests_that_company(self):
        intent = route_message("회사나 PER는 뭐야?", self.discovery, self.a.code, [], self.settings)
        self.assertEqual((intent.action, intent.code), ("select", self.b.code))
        intent = route_message("다른회사 최근 뉴스 보여줘", self.discovery, self.a.code, [], self.settings)
        self.assertEqual((intent.action, intent.company, intent.scope), ("lookup", "다른회사", "news"))

    def test_direct_lookup_verifies_official_name_and_code(self):
        listing = pd.DataFrame([{"Name": self.a.name, "Code": self.a.code, "Market": "KOSPI"}])
        for name in (self.a.name, self.a.code):
            self.assertEqual(identify_stock(name, listing=listing).code, self.a.code)
        with self.assertRaises(AppError):
            identify_stock("예시", listing=listing)

    def test_unsupported_prompts_are_absent_and_direct_question_has_honest_limit(self):
        prompts = suggested_prompts({}) + suggested_prompts({"candidate_result": self.discovery})
        self.assertFalse(any("주목" in p or "비교해" in p for p in prompts))
        intent = route_message("최근 시장에서 주목받는 테마를 알려줘", None, None, [], self.settings)
        self.assertEqual(intent.action, "unsupported")
        self.assertIn("순위", intent.reason)

    def test_discovery_state_survives_store_and_concepts_do_not_clear_result(self):
        state = {}
        store_candidate_discovery(state, self.discovery)
        self.assertEqual(state["conversation_mode"], "candidate_selection")
        store_analysis_result(state, self.result, "request")
        with patch("src.agents.chat._invoke") as call:
            text, refs, follow = answer_question("PER와 PBR의 차이는?", self.result, [], self.settings)
        self.assertIn("| 지표 |", text)
        self.assertEqual(state["dashboard_result"], self.result)
        call.assert_not_called()

    def test_value_and_unknown_cause_are_direct_without_model_invention(self):
        with patch("src.agents.chat._invoke") as call:
            answer, refs, follow = answer_question("현재 주가는 얼마야?", self.result, [], self.settings)
            self.assertIn("10,000.00원", answer)
            self.assertEqual(refs[0]["id"], "PRICE")
            answer, _, _ = answer_question("현재 PBR은 왜 없어?", self.result, [], self.settings)
            self.assertIn("원인을 확인할 수 없습니다", answer)
            self.assertNotIn("공시하지", answer)
            call.assert_not_called()

    def test_chart_evidence_changes_with_series_and_preserves_dates(self):
        first = PriceBar("2026-10-01", 100, 110, 90, 100, 1000000)
        last = PriceBar("2026-10-02", 100, 110, 90, 105, 700000)
        up = replace(self.result, price_history=PriceHistory(self.a.code, self.a.ticker, (first, last)))
        down = replace(up, price_history=replace(up.price_history, bars=(first, replace(last, close=95))))
        self.assertGreater(build_evidence(up)["HISTORY"]["change_pct"], 0)
        self.assertLess(build_evidence(down)["HISTORY"]["change_pct"], 0)
        self.assertIn("2026-10-01", build_evidence(up)["HISTORY"]["period"])

    def test_month_aggregation_uses_first_open_last_close_extremes_and_volume_sum(self):
        bars = (PriceBar("2026-01-01", 10, 13, 8, 12, 100), PriceBar("2026-01-03", 12, 15, 9, 14, 200),
                PriceBar("2026-02-01", 14, 16, 13, 15, 300))
        history = PriceHistory(self.a.code, self.a.ticker, bars)
        monthly = aggregate_history(history, "월")
        self.assertEqual(monthly.bars[0], PriceBar("2026-01", 10, 15, 8, 14, 300))
        yearly = aggregate_history(history, "연")
        self.assertEqual(yearly.bars[0], PriceBar("2026", 10, 16, 8, 15, 600))
        self.assertEqual(history.bars, bars)

    def test_export_failure_cannot_destroy_result_or_canvas(self):
        state = {}
        with patch("src.ui.state.build_workbook_bytes", side_effect=RuntimeError("export failure")) as export:
            store_analysis_result(state, self.result, "request")
            self.assertEqual(add_canvas(state, self.result), "added")
            export.assert_not_called()
        self.assertEqual(state["dashboard_result"], self.result)
        self.assertEqual(state["canvases"][0]["result"], self.result)

    def test_new_result_same_conditions_and_old_result_reopen(self):
        state = {}
        add_canvas(state, self.result)
        second = replace(self.result, result_id="a2", financial=replace(self.result.financial, price=11000))
        add_canvas(state, second)
        self.assertEqual(len(state["canvases"]), 2)
        self.assertEqual(add_canvas(state, self.result), "focused")
        self.assertEqual(state["canvases"][0]["result"].financial.price, 10000)
        self.assertEqual(historical_result(state, "이 카드 설명해줘")[1].result_id, "a1")
        self.assertEqual(historical_result(state, "이 카드 회사나 PER 설명해줘"), (True, None))
        for card in list(state["canvases"]):
            close_canvas(state, card["canvas_id"])
        self.assertFalse(state["canvases"])

    def test_semantic_review_rejects_unrelated_factory_claim_with_valid_per_id(self):
        fabricated = {"text": "이 회사의 공장이 중단되었습니다.", "evidence_ids": ["PER"], "follow_up": ""}
        reject = {"checks": {'evidence_match': False, 'time_basis': False, 'question_focus': False, 'explanation': False, 'scope_disclosed': False, 'context_consistent': False}, "supported": False, "answers_question": False, "reason": "unrelated"}
        with patch("src.agents.chat._invoke", side_effect=with_review_units([fabricated, reject, fabricated, reject])) as call:
            with self.assertRaises(AppError):
                answer_question("현재 종목의 위험 요인을 설명해줘", self.result, [], self.settings)
        self.assertEqual(call.call_count, 4)

    def test_formal_style_repetition_and_numeric_placeholders(self):
        evidence = build_evidence(self.result)
        text, refs = validate_answer({"text": "현재 PER는 {{PER}}입니다.", "evidence_ids": ["PER"], "follow_up": ""}, evidence)
        self.assertIn("12.50배", text)
        text, _ = validate_answer({"text": "현재 PER는 {{PER}}배입니다.", "evidence_ids": ["PER"], "follow_up": ""}, evidence)
        self.assertIn("12.50배입니다", text)
        self.assertNotIn("배배", text)
        for text in ("현재 주가는 999원입니다.", "그런 뜻이야.", "확인한 자료를 설명합니다. 확인한 자료를 설명합니다."):
            with self.subTest(text=text), self.assertRaises(AppError):
                validate_answer({"text": text, "evidence_ids": [], "follow_up": ""}, evidence)

    def test_grounding_schema_is_not_candidate_schema(self):
        schema = response_format({"task": "chat_grounding_review"}, "openai/gpt-oss-20b")["json_schema"]["schema"]
        self.assertEqual(set(schema["properties"]), {"supported", "answers_question", "reason", "checks", "unit_reviews"})

    def test_news_only_refresh_does_not_fetch_finance_history_or_report(self):
        with patch("src.pipeline.fetch_news", return_value=NewsData((), now_kst())) as news, \
             patch("src.pipeline.fetch_financial") as finance, patch("src.pipeline.fetch_price_history") as history, \
             patch("src.pipeline.generate_commentary") as report:
            a = analyze_selected_stock("반도체", (self.a,), self.a.code, settings=self.settings, scope="news", previous=self.result)
            b = analyze_selected_stock("반도체", (self.a,), self.a.code, settings=self.settings, scope="news", previous=self.result)
        self.assertEqual(news.call_count, 2)
        finance.assert_not_called(); history.assert_not_called(); report.assert_not_called()
        self.assertNotEqual(a.result_id, b.result_id)
        self.assertEqual(a.financial, self.result.financial)


class Plan5Flow(unittest.TestCase):
    setUp = flow.UserFlowTests.setUp
    set_responses = flow.UserFlowTests.set_responses
    submit_theme = flow.UserFlowTests.submit_theme
    select_stock = flow.UserFlowTests.select_stock
    open_canvas = flow.UserFlowTests.open_canvas
    assert_no_exception = flow.UserFlowTests.assert_no_exception

    def test_analysis_is_in_chat_canvas_is_explicit_and_export_error_is_local(self):
        self.submit_theme()
        self.select_stock("005930")
        state = self.app.session_state
        self.assertFalse(state.filtered_state.get("canvases"))
        self.assertTrue(any("종합 분석" in m["text"] for m in state["chat_messages"]))
        self.open_canvas()
        self.assertEqual(len(state["canvases"]), 1)
        with patch("src.ui.state.build_workbook_bytes", side_effect=RuntimeError("private message")):
            self.app.button(key="prepare_export_c1").click().run()
        self.assert_no_exception()
        self.assertIn("dashboard_result", state)
        self.assertIn("생성하지 못했습니다", state["canvases"][0]["export_error"])
        self.assertNotIn("private message", str(state["canvases"][0]["export_error"]))

    def test_explicit_information_security_form_and_cancel(self):
        self.app.button(key="guide_find").click().run()
        self.submit_theme("정보보안")
        self.assertEqual(self.app.session_state["candidate_result"].theme, "정보보안")
        self.assertEqual(self.app.session_state["conversation_mode"], "candidate_selection")
        self.app.button(key="guide_find").click().run()
        self.app.button(key="cancel_search").click().run()
        self.assertEqual(self.app.session_state["conversation_mode"], "general")

    def test_direct_company_price_needs_no_candidate_generation_and_answers_value(self):
        self.submit_theme("예시회사 주가는 얼마야?")
        self.assertEqual(self.app.session_state["selected_code"], "005930")
        self.assertIn("70,000.00원", self.app.session_state["chat_messages"][-1]["text"])
        self.llm.invoke.assert_not_called()
        self.news_request.assert_not_called()
