"""대화 의도/근거 검사 및 Streamlit 다중 턴 회귀 검사. 외부 호출은 대체한다."""

import unittest
from unittest.mock import patch

import test_user_flow as flow
from src.agents.chat import answer_question, build_evidence, conversation_context, normalize_message, route_message
from src.agents.report import response_format
from src.config import Settings
from src.models import (AnalysisResult, AppError, CandidateDiscoveryResult, FinancialData,
                        MetricValue, NewsData, StockCandidate, now_kst)
from src.ui.state import append_chat_message, reset_all_state, store_candidate_discovery


class ChatUnitTests(unittest.TestCase):
    def setUp(self):
        self.settings = Settings("test", "test-model", "", "")
        self.stock = StockCandidate("예시회사", "005930", "KOSPI", "005930.KS")
        self.other = StockCandidate("회사나", "247540", "KOSDAQ", "247540.KQ")
        self.discovery = CandidateDiscoveryResult("반도체", (self.stock, self.other), now_kst())
        self.result = AnalysisResult("반도체", self.discovery.candidates,
                                     FinancialData(self.stock, 70000, 15.2, now_kst()),
                                     NewsData((), now_kst()), None)

    def route(self, text):
        return route_message(text, self.discovery, self.stock.code, [], self.settings)

    def test_explicit_switch_and_theme_do_not_call_classifier(self):
        with patch("src.agents.chat._invoke") as invoke:
            self.assertEqual(self.route("회사나로 바꿔줘").code, "247540")
            self.assertEqual(self.route("2차전지 테마주 분석해줘").action, "discover")
            self.assertEqual(self.route("재조회해줘").action, "refresh")
            invoke.assert_not_called()

    def test_followup_classification_receives_current_target_and_history(self):
        with patch("src.agents.chat._invoke", return_value={"action": "answer", "theme": "", "code": ""}) as invoke:
            history = [{"role": "assistant", "text": "지표를 설명했습니다."}]
            intent = route_message("왜 높은 거야?", self.discovery, "005930", history, self.settings)
            self.assertEqual(intent.action, "answer")
            payload = invoke.call_args.args[2]
            self.assertEqual(payload["selected_code"], "005930")
            self.assertEqual(payload["conversation"], history)

    def test_unknown_or_unselectable_ai_target_is_rejected(self):
        with patch("src.agents.chat._invoke", return_value={"action": "select", "theme": "", "code": "999999"}):
            with self.assertRaises(AppError):
                self.route("다른 걸로 부탁해")

    def test_invalid_route_payload_is_rejected(self):
        for payload in ({"action": "run_code", "theme": "", "code": ""},
                        {"action": "answer", "theme": [], "code": ""}):
            with self.subTest(payload=payload), patch("src.agents.chat._invoke", return_value=payload):
                with self.assertRaises(AppError):
                    self.route("이건 어떨까?")

    def test_empty_long_and_term_input(self):
        for value in ("  ", "가" * 1201):
            with self.assertRaises(AppError):
                normalize_message(value)
        self.assertEqual(self.route("PER").action, "answer")

    def test_answer_attaches_exact_values_from_current_result(self):
        with patch("src.agents.chat._invoke", return_value={"text": "이익과 주가를 비교하는 지표입니다.", "evidence_ids": ["PER"]}):
            text, evidence = answer_question("PER 설명", self.result, [], self.settings)
        self.assertIn("지표", text)
        self.assertIn("15.20배", evidence[0]["text"])
        self.assertEqual(evidence[0]["id"], "PER")

    def test_unknown_references_numbers_urls_and_duplicates_rejected(self):
        cases = [
            {"text": "수익성이 높습니다.", "evidence_ids": ["NEWS_99"]},
            {"text": "PER는 99배입니다.", "evidence_ids": ["PER"]},
            {"text": "https://example.com 에서 보세요.", "evidence_ids": []},
            {"text": "지표입니다.", "evidence_ids": ["PER", "PER"]},
            {"text": "지표입니다.", "evidence_ids": [{}]},
        ]
        for payload in cases:
            with self.subTest(payload=payload), patch("src.agents.chat._invoke", return_value=payload):
                with self.assertRaises(AppError):
                    answer_question("설명", self.result, [], self.settings)

    def test_general_question_without_stock(self):
        with patch("src.agents.chat._invoke", return_value={"text": "순이익 대비 주가의 수준을 나타냅니다.", "evidence_ids": []}):
            answer, evidence = answer_question("PER는 뭐야?", None, [], self.settings)
        self.assertTrue(answer)
        self.assertEqual(evidence, [])

    def test_invalid_answer_is_regenerated_once(self):
        with patch("src.agents.chat._invoke", side_effect=[
            {"text": "PER는 99배입니다.", "evidence_ids": ["PER"]},
            {"text": "주당 이익과 주가를 비교합니다.", "evidence_ids": ["PER"]},
        ]) as invoke:
            answer, evidence = answer_question("지표 설명", self.result, [], self.settings)
        self.assertEqual(invoke.call_count, 2)
        self.assertIn("주당", answer)
        self.assertIn("15.20배", evidence[0]["text"])

    def test_invalid_answer_retry_is_bounded(self):
        with patch("src.agents.chat._invoke", return_value={"text": "99배입니다.", "evidence_ids": []}) as invoke:
            with self.assertRaises(AppError):
                answer_question("지표 설명", self.result, [], self.settings)
        self.assertEqual(invoke.call_count, 2)

    def test_unavailable_value_has_no_invented_unit_value(self):
        self.assertIn("정보 없음", build_evidence(self.result)["PBR"]["text"])

    def test_conversation_reset_and_bound(self):
        state = {}
        for i in range(45):
            append_chat_message(state, "user", str(i))
        self.assertEqual(len(state["chat_messages"]), 40)
        store_candidate_discovery(state, self.discovery)
        self.assertEqual(len(state["chat_messages"]), 40)
        self.assertEqual(len(conversation_context(state["chat_messages"])), 12)
        reset_all_state(state)
        self.assertNotIn("chat_messages", state)
        self.assertNotIn("theme_history", state)

    def test_chat_has_its_own_json_format(self):
        for task in ("chat_route", "chat_answer"):
            schema = response_format({"task": task}, "openai/gpt-oss-20b")["json_schema"]["schema"]
            self.assertNotIn("stocks", schema["properties"])
            self.assertIn("action" if task == "chat_route" else "evidence_ids", schema["properties"])
            self.assertEqual(response_format({"task": task}, "other-model"), {"type": "json_object"})


class ChatFlowTests(unittest.TestCase):
    setUp = flow.UserFlowTests.setUp
    set_responses = flow.UserFlowTests.set_responses
    submit_theme = flow.UserFlowTests.submit_theme
    select_stock = flow.UserFlowTests.select_stock
    submit = flow.UserFlowTests.submit
    assert_no_exception = flow.UserFlowTests.assert_no_exception

    def answer_responses(self, text="현재 선택한 종목의 이익 대비 주가 수준을 보여줍니다.", ids=None):
        self.llm.invoke.side_effect = [
            flow.response({"action": "answer", "theme": "", "code": ""}),
            flow.response({"text": text, "evidence_ids": ["PER"] if ids is None else ids}),
        ]

    def test_followup_keeps_data_and_excel_and_history_without_refetch(self):
        self.submit()
        original = self.app.session_state["export_bytes"]
        calls = self.ticker.call_count
        self.answer_responses()
        self.submit_theme("이 종목의 지표를 쉽게 설명해줘")
        self.assertEqual(self.ticker.call_count, calls)
        self.assertEqual(self.listing.call_count, 1)
        self.assertEqual(self.app.session_state["export_bytes"], original)
        messages = self.app.session_state["chat_messages"]
        self.assertEqual(messages[-1]["target"], "예시회사")
        self.assertEqual(messages[-1]["evidence"][0]["id"], "PER")
        self.assertTrue(any(m.get("report") is not None for m in messages))
        count = len(messages)
        self.app.run()
        self.assert_no_exception()
        self.assertEqual(len(self.app.session_state["chat_messages"]), count)

    def test_chat_stock_switch_changes_answer_context(self):
        self.submit()
        self.info.update(symbol="247540.KQ", regularMarketPrice=125000, currentPrice=125000, trailingPE=22.5)
        self.llm.invoke.side_effect = [flow.response(flow.report_payload(22.5, stock_name="회사나", price=125000))]
        self.submit_theme("회사나로 바꿔줘")
        self.assertEqual(self.app.session_state["selected_code"], "247540")
        self.assertEqual(self.listing.call_count, 1)
        self.answer_responses()
        self.submit_theme("그 종목은 어떤 지표야?")
        last = self.app.session_state["chat_messages"][-1]
        self.assertEqual(last["target"], "회사나")
        self.assertIn("22.50배", last["evidence"][0]["text"])

    def test_explicit_chat_refresh_reuses_candidates(self):
        self.submit()
        old_generation = self.app.session_state["query_options"].refresh_generation
        self.llm.invoke.side_effect = [flow.response(flow.report_payload())]
        self.submit_theme("재조회해줘")
        self.assertEqual(self.listing.call_count, 1)
        self.assertEqual(self.app.session_state["query_options"].refresh_generation, old_generation + 1)
        reports = [m for m in self.app.session_state["chat_messages"] if m.get("report")]
        self.assertEqual(len(reports), 2)

    def test_previous_report_text_is_supplied_to_followup(self):
        self.submit()
        history = self.app.session_state["chat_messages"]
        context = conversation_context(history)
        self.assertTrue(any("기업 가치를 단정하기 어렵습니다" in item["text"] for item in context))

    def test_followup_failure_preserves_current_result_and_can_retry(self):
        self.submit()
        self.llm.invoke.side_effect = RuntimeError("secret must not appear")
        self.submit_theme("위험 요인은 뭐야?")
        self.assertEqual(len(self.app.metric), 6)
        self.assertNotIn("secret", self.app.session_state["chat_messages"][-1]["text"])
        self.answer_responses()
        self.submit_theme("지표를 다시 설명해줘")
        self.assertIn("evidence", self.app.session_state["chat_messages"][-1])

    def test_new_theme_preserves_conversation_but_clears_target(self):
        self.submit()
        self.set_responses()
        self.submit_theme("로봇 테마주 분석해줘")
        self.assertIsNone(self.app.session_state["selected_code"])
        self.assertNotIn("dashboard_result", self.app.session_state)
        self.assertNotIn("export_bytes", self.app.session_state)
        self.assertTrue(any(m.get("report") for m in self.app.session_state["chat_messages"]))
        self.app.button(key="clear_results").click().run()
        self.assert_no_exception()
        self.assertEqual(len(self.app.chat_message), 0)
        self.assertNotIn("chat_messages", self.app.session_state)

    def test_general_question_does_not_fetch_stocks(self):
        self.answer_responses("주가와 이익의 관계를 나타내는 개념입니다.", [])
        self.submit_theme("PER는 뭐야?")
        self.ticker.assert_not_called()
        self.listing.assert_not_called()
        self.assertEqual(self.app.session_state["chat_messages"][-1]["target"], "일반 설명")

    def test_no_selection_is_not_arbitrarily_analyzed(self):
        self.submit_theme("반도체")
        self.llm.invoke.side_effect = [flow.response({"action": "clarify", "theme": "", "code": ""})]
        self.submit_theme("그 종목 분석해줘")
        self.ticker.assert_not_called()
        self.assertIsNone(self.app.session_state["selected_code"])
