"""단계 S01: 질문/요청 ID 보존, 실패 재시도, AppTest 재실행 중복 차단."""
from dataclasses import replace
from unittest.mock import patch
import unittest
from src.agents.answer_quality import QUALITY_CHECKS
from review_fixtures import with_review_units

import test_user_flow as flow
from scripts.llm_fixture import synthetic_result
from src.models import AppError, CandidateDiscoveryResult
from src.agents.request import ChatIntent
from src.ui.chat_lifecycle import (start_request, update_request, complete_request,
                             fail_request, current_request)
from src.ui.state import store_candidate_discovery, reset_all_state
from test_request import listing_fixture


class RequestStateTests(unittest.TestCase):
    def test_new_submission_gets_new_id_but_retry_preserves_original(self):
        state = {"last_submission": ("질문", [], None)}
        first = start_request(state, "원본  질문\n입니다", [{"role": "user", "text": "앞선 질문"}])
        update_request(state, user_recorded=True, status="fetching", data_scope="news")
        fail_request(state)
        retried = start_request(state, first.original_question, [], retry_id=first.request_id)
        self.assertEqual(retried.request_id, first.request_id)
        self.assertEqual(retried.original_question, "원본  질문\n입니다")
        self.assertTrue(retried.user_recorded)
        self.assertEqual(retried.history, first.history)
        complete_request(state, result_id="snapshot-a")
        self.assertIsNone(start_request(state, first.original_question, [], retry_id=first.request_id))
        next_request = start_request(state, first.original_question, [])
        self.assertNotEqual(next_request.request_id, first.request_id)
        self.assertEqual(state["chat_requests"][first.request_id].result_id, "snapshot-a")

    def test_immutable_original_and_completed_request(self):
        state = {}
        start_request(state, "질문", [])
        for changes in ({"original_question": "다른 질문"}, {"request_id": "overwritten"}):
            with self.assertRaises(ValueError):
                update_request(state, **changes)
        complete_request(state, result_id="snapshot-a")
        with self.assertRaises(ValueError):
            update_request(state, result_id="snapshot-b")

    def test_theme_reset_keeps_transaction_but_new_conversation_clears_it(self):
        state = {}
        request = start_request(state, "회사 분석해줘", [])
        result = synthetic_result()
        store_candidate_discovery(state, CandidateDiscoveryResult("새 테마", result.candidates, result.financial.retrieved_at))
        self.assertEqual(current_request(state).request_id, request.request_id)
        reset_all_state(state)
        self.assertIsNone(current_request(state))
        self.assertNotIn("request_id", state)


class RequestAppTests(unittest.TestCase):
    setUp = flow.UserFlowTests.setUp
    set_responses = flow.UserFlowTests.set_responses
    submit_theme = flow.UserFlowTests.submit_theme
    assert_no_exception = flow.UserFlowTests.assert_no_exception

    def setup_analysis(self):
        result = synthetic_result()
        stock = result.financial.stock
        self.stack.enter_context(patch("src.pipeline.identify_stock", return_value=stock))
        collect = self.stack.enter_context(patch("src.pipeline.analyze_selected_stock", return_value=result))
        answer = self.stack.enter_context(patch("src.agents.chat.answer_question", return_value=(
            "확인된 실적은 매출과 이익이 함께 개선됐습니다.",
            [{"id": "PER", "source": "검수", "text": "검수 지표", "value_text": "12.50배"}], "")))
        route = self.stack.enter_context(patch("src.agents.chat.route_message", return_value=ChatIntent(
            "lookup", company=stock.name)))
        self.app.run()
        return result, collect, answer, route

    def test_original_all_scope_questions_answer_once_and_rerun_keeps_snapshot(self):
        result, collect, answer, _ = self.setup_analysis()
        for question in ("삼성전자 어떻게 생각해?", "삼성전자를 분석해줘"):
            with self.subTest(question=question):
                self.submit_theme(question)
                transaction = self.app.session_state["chat_request"]
                self.assertEqual(transaction.original_question, question)
                self.assertEqual(transaction.status, "completed")
                self.assertEqual(answer.call_args.args[0], question)
                self.assertEqual(transaction.result_id, result.result_id)
                messages = list(self.app.session_state["chat_messages"])
                self.assertEqual(messages[-1]["text"], answer.return_value[0])
                before = (answer.call_count, collect.call_count)
                self.app.run()
                self.assert_no_exception()
                self.assertEqual((answer.call_count, collect.call_count), before)
                self.assertEqual(self.app.session_state["chat_messages"], messages)

    def test_answer_failure_retries_same_id_and_data_without_duplicate_user_message(self):
        result, collect, answer, route = self.setup_analysis()
        good_answer = answer.return_value
        answer.side_effect = AppError("test_answer", "검수용 설명 실패입니다.")
        question = "삼성전자 어떻게 생각해?"
        self.submit_theme(question)
        failed = self.app.session_state["chat_request"]
        self.assertEqual(failed.status, "failed")
        self.assertEqual(failed.data_result_id, result.result_id)
        self.assertEqual(collect.call_count, 1)
        self.app.run()
        self.assertEqual(answer.call_count, 1)
        answer.side_effect = None
        answer.return_value = good_answer
        self.app.button(key="retry_last_request").click().run()
        self.assert_no_exception()
        completed = self.app.session_state["chat_request"]
        self.assertEqual(completed.request_id, failed.request_id)
        self.assertEqual(completed.status, "completed")
        self.assertEqual(collect.call_count, 1)
        self.assertEqual(route.call_count, 1)
        self.assertEqual(sum(m["role"] == "user" for m in self.app.session_state["chat_messages"]), 1)
        self.assertEqual(answer.call_args.args[0], question)

    def test_fetch_failure_retries_same_id_and_question(self):
        result, collect, answer, route = self.setup_analysis()
        collect.side_effect = [AppError("test_fetch", "검수용 수집 실패입니다."), result]
        self.submit_theme("삼성전자를 분석해줘")
        failed = self.app.session_state["chat_request"]
        self.assertEqual(failed.status, "failed")
        self.assertIsNone(failed.data_result_id)
        self.app.button(key="retry_last_request").click().run()
        self.assert_no_exception()
        self.assertEqual(self.app.session_state["chat_request"].request_id, failed.request_id)
        self.assertEqual(self.app.session_state["chat_request"].status, "completed")
        self.assertEqual(answer.call_count, 1)
        self.assertEqual(route.call_count, 1)

    def test_real_router_preserves_new_company_question_without_classifier(self):
        result = synthetic_result()
        stock = replace(result.financial.stock, name="삼성전자", code="005930", ticker="005930.KS")
        result = replace(result, candidates=(stock,), financial=replace(result.financial, stock=stock))
        self.listing.return_value = listing_fixture()
        with patch("src.pipeline.analyze_selected_stock", return_value=result) as collect, patch(
                "src.agents.chat.answer_question", return_value=("수익성 변화를 설명합니다.",
                    [{"id": "PER", "text": "검수 지표", "source": "검수"}], "")) as answer:
            for question in ("삼성전자 어떻게 생각해?", "삼성전자를 분석해줘", "삼성전자 종목 이슈 세 줄 요약"):
                self.app.button(key="clear_results").click().run()
                self.submit_theme(question)
                self.assertEqual(self.app.session_state["original_question"], question)
                self.assertEqual(self.app.session_state["chat_request"].status, "completed")
                self.assertEqual(answer.call_args.args[0], question)
                self.assertEqual(collect.call_args.args[2], "005930")
        self.llm.invoke.assert_not_called()

    def test_relationship_with_no_primary_stock_never_calls_single_stock_pipeline(self):
        self.listing.return_value = listing_fixture()
        with patch("src.pipeline.analyze_selected_stock") as collect, patch("src.agents.chat.answer_question") as answer, patch("src.comparison_flow.collect_company_financials", return_value={"status":"empty"}) as pair_collect:
            for question, intent in (("삼성물산이 보유한 삼성전자 지분 알려줘", "shareholding_query"),
                                     ("삼성전자와 SK하이닉스 비교", "comparison_query")):
                self.submit_theme(question)
                request = self.app.session_state["chat_request"]
                self.assertEqual(request.status, "completed")
                self.assertEqual(request.intent.action, intent)
                self.assertIsNone(request.resolved_stock)
                self.assertIsNone(request.intent.entities.primary_stock)
                if intent == "shareholding_query":
                    self.assertIn("준비 중", self.app.session_state["chat_messages"][-1]["text"])
                else:
                    self.assertIn("재무자료를 모두 확보하지 못해", self.app.session_state["chat_messages"][-1]["text"])
                self.assertNotIn("dashboard_result", self.app.session_state)
            self.assertEqual(pair_collect.call_count, 2)
            collect.assert_not_called()
            answer.assert_not_called()
            self.ticker.assert_not_called()
            self.news_request.assert_not_called()
            self.llm.invoke.assert_not_called()

    def test_new_lookup_uses_real_answer_validation_and_keeps_old_canvas_and_excel(self):
        result = synthetic_result()
        first_stock = replace(result.financial.stock, name="삼성전자", code="005930", ticker="005930.KS")
        first = replace(result, candidates=(first_stock,), financial=replace(result.financial, stock=first_stock), result_id="snapshot-s-a")
        second_stock = replace(first_stock, name="SK하이닉스", code="000660", ticker="000660.KS")
        second = replace(first, candidates=(second_stock,), financial=replace(first.financial, stock=second_stock), result_id="snapshot-s-b")
        self.listing.return_value = listing_fixture()
        # 실제 answer_question/구조·수치 검사/화면은 유지하고 생성·의미 심사 모델 응답만 대체한다.
        payload = {"text": "확인된 PER은 {{PER}}입니다. 주가와 주당순이익의 관계를 나타냅니다.",
                   "evidence_ids": ["PER"], "follow_up": "", "blocks": []}
        verdict = {"checks": dict.fromkeys(QUALITY_CHECKS, True), "supported": True,
                   "answers_question": True, "reason": "모의 판정"}
        with patch("src.pipeline.analyze_selected_stock", side_effect=[first, second]), patch(
                "src.agents.chat._invoke", side_effect=with_review_units([payload, verdict, payload, verdict])) as invoke:
            self.submit_theme("삼성전자 어떻게 생각해?")
            first_id = self.app.session_state["request_id"]
            self.assertEqual(self.app.session_state["chat_request"].status, "completed")
            self.assertIn("12.50배", self.app.session_state["chat_messages"][-1]["text"])
            self.assertEqual(invoke.call_count, 2)
            self.app.button(key="add_canvas").click().run()
            self.app.button(key="prepare_export_c1").click().run()
            card = self.app.session_state["canvases"][0]
            old_bytes = card["export_bytes"]
            self.assertTrue(old_bytes.startswith(b"PK"))
            self.submit_theme("SK하이닉스를 분석해줘")
            self.assertEqual(self.app.session_state["chat_request"].status, "completed")
            self.assertNotEqual(self.app.session_state["request_id"], first_id)
            self.assertEqual(self.app.session_state["chat_requests"][first_id].result_id, first.result_id)
            self.assertEqual(self.app.session_state["results"][first.result_id], first)
            old_card = self.app.session_state["canvases"][0]
            self.assertEqual(old_card["result_id"], first.result_id)
            self.assertEqual(old_card["export_bytes"], old_bytes)
            self.assertEqual(self.app.session_state["chat_messages"][1]["result_id"], first.result_id)
            self.assertEqual(self.app.session_state["chat_messages"][-1]["result_id"], second.result_id)
            before = invoke.call_count
            self.app.run()
            self.assertEqual(invoke.call_count, before)
            self.assert_no_exception()


if __name__ == "__main__":
    unittest.main()
