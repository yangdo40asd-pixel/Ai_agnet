"""증권앱 참조 P0: 첫 진입·전송·후속 대화·결과별 상세·초기화 흐름."""
from dataclasses import replace
import unittest
from unittest.mock import patch

import test_user_flow as flow
from src.ui.state import store_analysis_result, append_chat_message


class ReferenceUIFlow(unittest.TestCase):
    setUp = flow.UserFlowTests.setUp
    set_responses = flow.UserFlowTests.set_responses
    submit_theme = flow.UserFlowTests.submit_theme
    select_stock = flow.UserFlowTests.select_stock
    open_canvas = flow.UserFlowTests.open_canvas
    assert_no_exception = flow.UserFlowTests.assert_no_exception

    def test_all_initial_examples_fill_without_calling_services_and_can_be_submitted(self):
        # 공급자와 종목명만 가상 응답으로 대체하며 실제 라우팅/화면을 실행한다.
        self.listing.return_value.loc[0, "Name"] = "삼성전자"
        for index, expected in enumerate(("반도체 관련 종목을 찾아줘", "삼성전자를 분석해줘", "PER와 PBR의 차이를 설명해줘")):
            with self.subTest(example=expected):
                self.app.button(key="clear_results").click().run()
                self.llm.invoke.reset_mock()
                self.listing.reset_mock()
                self.ticker.reset_mock()
                self.news_request.reset_mock()
                self.app.button(key=f"suggested_prompt_{index}").click().run()
                self.assertEqual(self.app.text_input(key="composer_text").value, expected)
                self.assertFalse(self.app.session_state.filtered_state.get("chat_messages"))
                for call in (self.llm.invoke, self.listing, self.ticker, self.news_request):
                    call.assert_not_called()
                if index == 0:
                    self.set_responses(names=["삼성전자", "회사나", "회사다"])
                elif index == 1:
                    self.llm.invoke.side_effect = [flow.response(flow.report_payload(stock_name="삼성전자"))]
                self.app.button(key="composer_submit").click().run()
                self.assert_no_exception()
                self.assertEqual(self.app.session_state["chat_messages"][0]["text"], expected)
                self.assertFalse(self.app.session_state.filtered_state.get("canvases"))
                self.assertFalse(any("어떤 종목이 궁금" in item.value for item in self.app.markdown))
                if index == 0:
                    self.assertEqual(self.app.session_state["request_status"], "awaiting_selection")
                    self.ticker.assert_not_called()
                elif index == 1:
                    self.assertEqual(self.app.session_state["dashboard_result"].target_code, "005930")
                    self.assertTrue(any(m.get("result_id") for m in self.app.session_state["chat_messages"]))
                else:
                    self.assertIn("| 지표 |", self.app.session_state["chat_messages"][-1]["text"])
                    self.llm.invoke.assert_not_called()
                    self.assertFalse(any(str(b.key).startswith("message_canvas_") for b in self.app.button))

    def test_concept_followup_does_not_link_unrelated_stock_and_reset_restores_welcome(self):
        self.submit_theme()
        self.select_stock("005930")
        self.open_canvas()
        self.submit_theme("PER와 PBR의 차이를 설명해줘")
        last_index = len(self.app.session_state["chat_messages"]) - 1
        self.assertIsNone(self.app.session_state["chat_messages"][-1]["result_id"])
        self.assertFalse(any(b.key == f"message_canvas_{last_index}" for b in self.app.button))
        messages = list(self.app.session_state["chat_messages"])
        self.app.button(key="close_c1").click().run()
        self.assertEqual(self.app.session_state["chat_messages"], messages)
        self.assertFalse(any("어떤 종목이 궁금" in item.value for item in self.app.markdown))
        self.app.button(key="clear_results").click().run()
        self.assert_no_exception()
        self.assertTrue(any("어떤 종목이 궁금" in item.value for item in self.app.markdown))
        self.assertEqual(sum(str(b.key).startswith("suggested_prompt_") for b in self.app.button), 3)
        self.assertFalse(self.app.session_state.filtered_state.get("canvases"))
        self.assertFalse(self.app.session_state.filtered_state.get("chat_messages"))

    def test_old_answer_opens_original_snapshot_after_new_stock_and_can_reopen(self):
        self.submit_theme()
        self.select_stock("005930")
        first = self.app.session_state["dashboard_result"]
        first_index = next(i for i,m in enumerate(self.app.session_state["chat_messages"]) if m.get("result_id") == first.result_id)
        self.ticker.return_value.get_info.return_value = dict(self.info, symbol="247540.KQ", currentPrice=80000, regularMarketPrice=80000)
        self.llm.invoke.side_effect = [flow.response(flow.report_payload(stock_name="회사나", price=80000))]
        self.select_stock("247540")
        second = self.app.session_state["dashboard_result"]
        self.assertNotEqual(first.result_id, second.result_id)
        self.assertFalse(self.app.session_state.filtered_state.get("canvases"))
        second_index = next(i for i,m in enumerate(self.app.session_state["chat_messages"]) if m.get("result_id") == second.result_id)
        self.app.button(key=f"message_canvas_{second_index}").click().run()
        self.app.button(key=f"message_canvas_{first_index}").click().run()
        self.assert_no_exception()
        card = self.app.session_state["canvases"][0]
        self.assertEqual(card["stock_code"], "005930")
        self.assertEqual(card["result"].financial.price, first.financial.price)
        self.assertEqual(card["result"].financial.retrieved_at, first.financial.retrieved_at)
        self.assertEqual(self.app.session_state["dashboard_result"].target_code, "247540")
        self.app.button(key=f"message_canvas_{second_index}").click().run()
        self.app.button(key=f"message_canvas_{first_index}").click().run()
        self.assertEqual(len(self.app.session_state["canvases"]), 2)
        self.assertEqual(self.app.session_state["canvases"][0]["result_id"], first.result_id)

    def test_expired_result_offers_explicit_requery_without_opening_current_result(self):
        self.submit_theme()
        self.select_stock("005930")
        state = self.app.session_state
        original = state["dashboard_result"]
        index = next(i for i,m in enumerate(state["chat_messages"]) if m.get("result_id") == original.result_id)
        # 실제 보관 한도(20)를 넘겨 첫 결과를 만료시킨다.
        retained = state.filtered_state
        for number in range(21):
            store_analysis_result(retained, replace(original, result_id=f"snapshot{number}"), state["active_request_key"])
        for key in ("results", "dashboard_result", "latest_result"):
            state[key] = retained[key]
        self.app.run()
        self.assertFalse(any(b.key == f"message_canvas_{index}" for b in self.app.button))
        self.assertTrue(any("보관 범위를 벗어났" in c.value for c in self.app.caption))
        before = self.llm.invoke.call_count
        self.app.button(key=f"expired_result_{index}").click().run()
        self.assertEqual(self.app.text_input(key="composer_text").value, "005930 분석 자료를 다시 조회해줘")
        self.assertEqual(self.llm.invoke.call_count, before)
        self.assertFalse(state.filtered_state.get("canvases"))
        self.llm.invoke.side_effect = [flow.response(flow.report_payload())]
        self.app.button(key="composer_submit").click().run()
        self.assert_no_exception()
        self.assertEqual(len(self.app.error), 0)
        self.assertEqual(state["dashboard_result"].target_code, "005930")
        self.assertNotEqual(state["dashboard_result"].result_id, original.result_id)
        self.assertNotEqual(state["dashboard_result"].result_id, "snapshot20")
        self.assertFalse(state.filtered_state.get("canvases"))

    def test_long_reply_and_error_keep_single_input_and_no_initial_examples(self):
        self.submit_theme("PER의 뜻을 설명해줘")
        messages = self.app.session_state.filtered_state
        append_chat_message(messages, "assistant", "긴 설명입니다.\n\n" * 100)
        self.app.session_state["chat_messages"] = messages["chat_messages"]
        self.app.run()
        self.assertEqual(len(self.app.text_input), 1)
        self.assertTrue(any(b.key == "composer_submit" for b in self.app.button))
        self.assertFalse(any(str(b.key).startswith("suggested_prompt_") for b in self.app.button))
        with patch("src.pipeline.discover_theme_candidates", side_effect=RuntimeError("private")):
            self.submit_theme("방산 테마 찾아줘")
        self.assert_no_exception()
        self.assertEqual(len(self.app.text_input), 1)
        self.assertTrue(any(b.key == "composer_submit" for b in self.app.button))
        self.assertFalse(any(str(b.key).startswith("message_canvas_") for b in self.app.button))
        self.assertTrue(any("이미지와 PDF" in c.value for c in self.app.caption))


if __name__ == "__main__":
    unittest.main()
