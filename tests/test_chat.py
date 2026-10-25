"""대화 의도/근거 검사 및 Streamlit 다중 턴 회귀 검사. 외부 호출은 대체한다."""

import unittest
from review_fixtures import with_review_units
from unittest.mock import patch

import test_user_flow as flow
from src.agents.chat import (
    answer_question, attachments_for_model, build_evidence, conversation_context,
    prefers_dialogue, unsupported_chat_claim, validate_answer,
    normalize_attachments, normalize_message, prepare_submission, resolve_follow_up, route_message,
)
from src.agents.report import CHAT_TEMPERATURE, FACT_TEMPERATURE, _comment_text, _invoke, response_format
from src.config import Settings
from src.models import (AnalysisResult, AppError, CandidateDiscoveryResult, FinancialData,
                        MetricValue, NewsData, StockCandidate, now_kst)
from src.ui.dashboard import CHART_CONFIG
from src.ui.layout import panel_content_height
from src.ui.state import (
    add_canvas, append_chat_message, close_canvas, guide_actions, reset_all_state,
    store_candidate_discovery, suggested_prompts,
)


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
        with patch("src.agents.request._invoke") as invoke:
            self.assertEqual(self.route("회사나로 바꿔줘").code, "247540")
            self.assertEqual(self.route("2차전지 테마주 분석해줘").action, "discover")
            self.assertEqual(self.route("재조회해줘").action, "refresh")
            invoke.assert_not_called()

    def test_new_theme_or_stock_never_reuses_current_selection(self):
        with patch("src.agents.request._invoke") as invoke:
            self.assertEqual(self.route("이번엔 다른 테마").action, "clarify")
            self.assertEqual(self.route("이번엔 다른 종목").action, "clarify")
            invoke.assert_not_called()

    def test_followup_classification_receives_current_target_and_history(self):
        with patch("src.agents.request._invoke", return_value={"action": "answer", "theme": "", "code": ""}) as invoke:
            history = [{"role": "assistant", "text": "지표를 설명했습니다."}]
            intent = route_message("그 방향이 맞는지 봐줘", self.discovery, "005930", history, self.settings)
            self.assertEqual(intent.action, "answer")
            payload = invoke.call_args.args[2]
            self.assertEqual(payload["selected_code"], "005930")
            self.assertEqual(payload["conversation"], history)

    def test_unknown_or_unselectable_ai_target_is_rejected(self):
        with patch("src.agents.request._invoke", return_value={"action": "select", "theme": "", "code": "999999"}):
            with self.assertRaises(AppError):
                self.route("다른 걸로 부탁해")

    def test_invalid_route_payload_is_rejected(self):
        for payload in ({"action": "run_code", "theme": "", "code": ""},
                        {"action": "answer", "theme": [], "code": ""}):
            with self.subTest(payload=payload), patch("src.agents.request._invoke", return_value=payload):
                with self.assertRaises(AppError):
                    self.route("이건 어떨까?")

    def test_empty_long_and_term_input(self):
        for value in ("  ", "가" * 1201):
            with self.assertRaises(AppError):
                normalize_message(value)
        self.assertEqual(self.route("PER").action, "answer")

    def test_answer_attaches_exact_values_from_current_result(self):
        with patch("src.agents.chat._invoke", side_effect=with_review_units([
            {"text":"이익과 주가를 비교하는 지표입니다.","evidence_ids":["PER"],"follow_up":""},
            {"checks": {'evidence_match': True, 'time_basis': True, 'question_focus': True, 'explanation': True, 'scope_disclosed': True, 'context_consistent': True}, "supported":True,"answers_question":True,"reason":""}])):
            text, evidence, follow = answer_question("PER 설명", self.result, [], self.settings)
        self.assertIn("지표", text)
        self.assertIn("15.20배", evidence[0]["text"])
        self.assertEqual(follow, "")

    def test_unknown_references_numbers_urls_and_duplicates_rejected(self):
        cases = [
            {"text": "수익성이 높습니다.", "evidence_ids": ["NEWS_99"], "follow_up": "이 지표의 한계도 알아볼까요?"},
            {"text": "PER는 99배입니다.", "evidence_ids": ["PER"], "follow_up": "이 지표의 한계도 알아볼까요?"},
            {"text": "https://example.com 에서 보세요.", "evidence_ids": [], "follow_up": "이 지표의 한계도 알아볼까요?"},
            {"text": "지표입니다.", "evidence_ids": ["PER", "PER"], "follow_up": "이 지표의 한계도 알아볼까요?"},
            {"text": "지표입니다.", "evidence_ids": [{}], "follow_up": "이 지표의 한계도 알아볼까요?"},
        ]
        for payload in cases:
            with self.subTest(payload=payload), patch("src.agents.chat._invoke", return_value=payload):
                with self.assertRaises(AppError):
                    answer_question("설명", self.result, [], self.settings)

    def test_general_question_without_stock(self):
        with patch("src.agents.chat._invoke", return_value={"text": "순이익 대비 주가의 수준을 나타냅니다.", "evidence_ids": [], "follow_up": "이 지표의 한계도 알아볼까요?"}):
            answer, evidence, _follow = answer_question("PER는 뭐야?", None, [], self.settings)
        self.assertTrue(answer)
        self.assertEqual(evidence, [])

    def test_invalid_answer_is_regenerated_once(self):
        with patch("src.agents.chat._invoke", side_effect=with_review_units([
            {"text":"PER는 99배입니다.","evidence_ids":["PER"],"follow_up":""},
            {"text":"주당 이익과 주가를 비교합니다.","evidence_ids":["PER"],"follow_up":""},
            {"checks": {'evidence_match': True, 'time_basis': True, 'question_focus': True, 'explanation': True, 'scope_disclosed': True, 'context_consistent': True}, "supported":True,"answers_question":True,"reason":""}])) as invoke:
            answer, evidence, _ = answer_question("지표 설명", self.result, [], self.settings)
        self.assertEqual(invoke.call_count, 3)
        self.assertIn("주당", answer)
        self.assertIn("15.20배", evidence[0]["text"])

    def test_invalid_answer_retry_is_bounded(self):
        with patch("src.agents.chat._invoke", return_value={"text": "99배입니다.", "evidence_ids": [], "follow_up": "이 지표의 한계도 알아볼까요?"}) as invoke:
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
            if task == "chat_answer":
                self.assertIn("follow_up", schema["properties"])
            self.assertEqual(response_format({"task": task}, "other-model"), {"type": "json_object"})


    def test_repeated_textbook_paragraph_is_not_an_answer(self):
        for text in ("지표를 확인할 수 있습니다. 지표를 확인할 수 있습니다.", "주가를 주당순이익으로 나눈 값이에요."):
            with self.assertRaises(AppError):
                validate_answer({"text":text,"evidence_ids":[],"follow_up":""},{})
        text, evidence = validate_answer({"text":"PER는 주가를 주당순이익으로 나눈 값입니다.","evidence_ids":[],"follow_up":""},{})
        self.assertIn("주당순이익",text)

    def test_chat_temperature_stays_below_hallucination_range(self):
        with patch("src.agents.chat._invoke") as call:
            text, evidence, follow = answer_question("PER가 뭐야?", None, [], self.settings)
        call.assert_not_called()
        self.assertIn("주당순이익", text)
        self.assertEqual(follow, "")
        self.assertLessEqual(CHAT_TEMPERATURE, 0.2)
        self.assertLessEqual(FACT_TEMPERATURE, 0.1)

    def test_per_level_does_not_become_valuation_and_formula_stays_per_share(self):
        allowed = "PER는 주가를 주당순이익으로 나눈 값입니다. 낮거나 높다고 해서 저평가나 고평가라고 단정할 수 없습니다."
        self.assertEqual(_comment_text(allowed), allowed)
        rejected = [
            "PER이 낮으면 저평가이고 높으면 고평가입니다.",
            "PER이 낮으면 이익 대비 주가가 저렴하다고 볼 수 있고, 높으면 비싸다고 해석할 수 있습니다.",
            "PER는 주가를 회사 전체 순이익으로 나눈 값입니다.",
        ]
        for text in rejected:
            with self.subTest(text=text):
                with self.assertRaises(AppError):
                    _comment_text(text)
        with patch("src.agents.chat._invoke", side_effect=with_review_units([
            {"text": rejected[1], "evidence_ids": [], "follow_up": "그래서 저평가인가요?"},
            {"text": "PER는 주가를 주당순이익으로 나눈 값입니다. 수치의 높고 낮음만으로 가치를 단정할 수 없습니다.",
             "evidence_ids": [], "follow_up": "업종 평균과 함께 보는 이유를 설명할까요?"},
        ])) as invoke:
            answer, evidence, follow = answer_question("PER는 무슨 뜻이야?", None, [], self.settings)
        invoke.assert_not_called()
        self.assertNotIn("저렴", answer)
        self.assertNotIn("저평가", follow)
        self.assertEqual(evidence, [])

    def test_investor_paraphrases_stay_in_dialogue_and_bad_answers_fail(self):
        for question in ("이거 지금 담아도 늦었나", "물타기 해야 돼?", "PER이 낮으면 저평가 아니야?", "뉴스 보면 호재야?"):
            self.assertEqual(self.route(question).action,"answer")
        self.assertEqual(self.route("삼성전자 사도 될까?").action,"lookup")
        for text in ("PER이 낮으면 저평가이고 높으면 고평가입니다.", "지금 담으세요.", "PER는 주가를 회사 전체 순이익으로 나눈 값입니다."):
            with self.assertRaises(AppError):
                validate_answer({"text":text,"evidence_ids":[],"follow_up":""},{})

    def test_general_questions_do_not_route_to_discovery(self):
        with patch("src.agents.request._invoke", return_value={"action": "answer", "theme": "", "code": ""}):
            self.assertEqual(self.route("PER이 뭐야?").action, "answer")
            self.assertEqual(self.route("반도체 업황이 무슨 뜻이야").action, "answer")

    def test_invalid_follow_up_keeps_answer_without_retry(self):
        with patch("src.agents.chat._invoke", side_effect=with_review_units([
            {"text":"이익과 주가를 비교하는 지표입니다.","evidence_ids":["PER"],"follow_up":"99배인가요?"},
            {"checks": {'evidence_match': True, 'time_basis': True, 'question_focus': True, 'explanation': True, 'scope_disclosed': True, 'context_consistent': True}, "supported":True,"answers_question":True,"reason":""}])) as invoke:
            _, evidence, follow = answer_question("PER 설명", self.result, [], self.settings)
        self.assertEqual(invoke.call_count,2)
        self.assertEqual(follow,"")
        self.assertEqual(evidence[0]["id"],"PER")

    def test_missing_follow_up_field_is_a_format_error(self):
        with self.assertRaises(AppError):
            validate_answer({"text": "개념을 설명해요.", "evidence_ids": []}, {})

    def test_missing_metric_still_requires_its_evidence_for_current_stock(self):
        answer = {"text": "이번 조회에서 해당 지표를 확인하지 못했어요.",
                  "evidence_ids": [], "follow_up": "다른 지표도 알아볼까요?"}
        with patch("src.agents.chat._invoke", side_effect=with_review_units([answer, dict(answer, evidence_ids=["PBR"])])) as invoke:
            _, evidence, _ = answer_question("현재 종목의 PBR 정보가 없어", self.result, [], self.settings)
        invoke.assert_not_called()
        self.assertIn("정보 없음", evidence[0]["text"])

    def test_number_error_retry_reports_reason_without_raw_response(self):
        with patch("src.agents.chat._invoke", side_effect=with_review_units([
            {"text":"PER는 99배입니다.","evidence_ids":["PER"],"follow_up":""},
            {"text":"주가를 주당순이익으로 나눈 값입니다.","evidence_ids":["PER"],"follow_up":""},
            {"checks": {'evidence_match': True, 'time_basis': True, 'question_focus': True, 'explanation': True, 'scope_disclosed': True, 'context_consistent': True}, "supported":True,"answers_question":True,"reason":""}])) as invoke:
            answer_question("PER 설명",self.result,[],self.settings)
        request=invoke.call_args_list[1].args[2]
        self.assertEqual(request["validation_error"],"chat_numbers")
        self.assertNotIn("99배",str(request))

    def test_repeated_follow_up_is_omitted(self):
        messages = [{"role": "assistant", "text": "설명", "follow_up": "이어서 궁금한 지표가 있나요?"}]
        self.assertEqual(resolve_follow_up("이어서 궁금한 지표가 있나요?", messages, None), "")
        self.assertEqual(resolve_follow_up("", messages, None, None), "")

    def test_guide_actions_follow_result_state(self):
        self.assertEqual(guide_actions({}), ["find"])
        selected = guide_actions({"selected_code": "005930"})
        self.assertIn("refresh", selected)
        self.assertNotIn("risk", selected)
        self.assertNotIn("canvas", selected)
        ready = guide_actions({"selected_code": "005930", "dashboard_result": self.result})
        self.assertEqual(ready, ["find", "risk", "refresh", "canvas"])

    def test_suggested_prompts_follow_current_state(self):
        self.assertEqual(suggested_prompts({}), ("반도체 관련 종목을 찾아줘", "삼성전자를 분석해줘", "PER와 PBR의 차이를 설명해줘"))
        self.assertFalse(any("비교" in p for p in suggested_prompts({"candidate_result":self.discovery})))
        self.assertIn("현재 종목의 PER와 PBR을 설명해줘", suggested_prompts({"dashboard_result":self.result}))

    def test_attachment_limits_and_model_payload_omit_bytes(self):
        with self.assertRaises(AppError):
            normalize_attachments([("메모.exe", b"abc")])
        with self.assertRaises(AppError):
            normalize_attachments([("큰파일.txt", b"a" * (5 * 1024 * 1024 + 1))])
        items = normalize_attachments([
            ("chart.png", b"\x89PNG"),
            ("메모.txt", ("가" * 9000).encode()),
        ])
        payload = attachments_for_model(items)
        self.assertEqual(payload["files"], [{"name": "chart.png", "kind": "image"}])
        self.assertEqual(len(payload["texts"][0]["text"]), 8000)
        self.assertTrue(payload["texts"][0]["truncated"])
        self.assertNotIn(b"\x89PNG", str(payload).encode())
        self.assertEqual(prepare_submission("", [("메모.txt", b"hello")])[0], "attachment_only")

    def test_canvas_snapshot_survives_later_result_and_close(self):
        state = {"dashboard_result": self.result}
        object.__setattr__(self.result, "result_id", "first")
        with patch("src.ui.state.build_workbook_bytes", return_value=b"xlsx"), \
                patch("src.ui.state.build_export_filename", return_value="a.xlsx"):
            self.assertEqual(add_canvas(state, None), "missing")
            self.assertEqual(add_canvas(state, self.result), "added")
            self.assertEqual(add_canvas(state, self.result), "focused")
            self.assertEqual(len(state["canvases"]), 1)
            other = AnalysisResult("반도체", self.discovery.candidates,
                                   FinancialData(self.other, 1000, 2, now_kst()),
                                   NewsData((), now_kst()), None, result_id="other")
            self.assertEqual(add_canvas(state, other), "added")
            self.assertEqual(state["canvases"][0]["stock_code"], "247540")
            self.assertEqual(state["canvases"][1]["result_id"], "first")
            generation = state["canvas_scroll_generation"]
            append_chat_message(state, "user", "후속")
            self.assertEqual(state["canvas_scroll_generation"], generation)
            close_canvas(state, state["canvases"][0]["canvas_id"])
            self.assertEqual(state["canvases"][0]["result_id"], "first")
            for index in range(8):
                extra = AnalysisResult("반도체", self.discovery.candidates,
                                       FinancialData(self.stock, 1000, 2, now_kst()),
                                       NewsData((), now_kst()), None, result_id=f"extra-{index}")
                add_canvas(state, extra)
            self.assertEqual(len(state["canvases"]), 8)
        reset_all_state(state, keep_conversation=True)
        self.assertIn("canvases", state)
        reset_all_state(state)
        self.assertNotIn("canvases", state)

    def test_panel_height_fits_reference_viewport(self):
        height = panel_content_height()
        self.assertEqual(160 + height + 430, 1080)
        self.assertFalse(CHART_CONFIG["scrollZoom"])

    def test_classifier_meaning_is_checked_and_valid_discovery_is_allowed(self):
        with patch("src.agents.request._invoke", return_value={"action":"discover","theme":"방산","code":""}):
            self.assertEqual(self.route("방산 분야를 알아보고 싶은데").action,"discover")
        with patch("src.agents.request._invoke", return_value={"action":"discover","theme":"","code":""}):
            self.assertEqual(self.route("그 방향이 맞는지 봐줘").action,"clarify")

    def test_short_input_and_search_explanation_are_not_implicit_search(self):
        with patch("src.agents.request._invoke", return_value={"action": "answer", "theme": "", "code": ""}):
            self.assertEqual(route_message("반도체", None, None, [], self.settings).action, "answer")
            self.assertEqual(self.route("테마주 검색 기능은 뭐야?").action, "answer")

    def test_multiple_candidates_require_explicit_choice(self):
        with patch("src.agents.request._invoke") as invoke:
            self.assertEqual(self.route("예시회사랑 회사나 중에서 분석해줘").action, "unsupported")
            invoke.assert_not_called()

    def test_candidate_association_evidence_is_explicitly_uncollected_by_default(self):
        self.assertEqual(self.stock.association_status, "not_collected")
        self.assertEqual(self.stock.association_reason, "")
        self.assertEqual(self.stock.association_source, "")

    def test_explicit_switch_beats_metric_word_and_other_stock_is_not_current_evidence(self):
        with patch("src.agents.request._invoke") as invoke:
            self.assertEqual(self.route("회사나로 바꿔서 지표 보여줘").action, "select")
            self.assertEqual(self.route("회사나 PER는 뭐야?").action, "select")
            self.assertEqual(self.route("예시회사 PER는 뭐야?").action, "answer")
            invoke.assert_not_called()

    def test_snapshot_copies_mutable_nested_fields(self):
        from dataclasses import replace
        result = replace(self.result, section_status={"finance": "ok"})
        state = {}
        with patch("src.ui.state.build_workbook_bytes", return_value=b"xlsx"):
            add_canvas(state, result)
        result.section_status["finance"] = "changed"
        self.assertEqual(state["canvases"][0]["result"].section_status["finance"], "ok")

    def test_inflight_guard_recovers_and_survives_theme_reset(self):
        from src.ui.state import begin_request, finish_request
        state = {}
        self.assertTrue(begin_request(state, "first"))
        reset_all_state(state, keep_conversation=True)
        self.assertFalse(begin_request(state, "second"))
        finish_request(state, "second")
        self.assertFalse(begin_request(state, "third"))
        finish_request(state, "first")
        self.assertTrue(begin_request(state, "second"))

    def test_new_chat_removes_uploads_queue_and_canvas_widget_state(self):
        state = {"composer_generation": 2, "composer_files_2": [b"file"], "composer_text": "보내기 전 글",
                 "canvas_period_c1": "1Y", "queued_submission": ("text", []),
                 "queued_prompt": "질문", "awaiting_theme": True, "canvases": [{}]}
        reset_all_state(state)
        self.assertEqual(state, {"composer_generation": 3})

    def test_image_and_pdf_answers_always_disclose_unread_content(self):
        with patch("src.agents.chat._invoke", return_value={
            "text": "확인할 내용을 글로 입력할 수 있습니다.", "evidence_ids": [],
            "follow_up": "설명이 필요한 용어가 있나요?",
        }) as invoke:
            answer, _, _ = answer_question("자료 설명해줘", None, [], self.settings,
                                         normalize_attachments([("chart.png", b"fake-image")]))
        self.assertIn("본문은 현재 읽을 수 없습니다", answer)
        self.assertNotIn("fake-image", str(invoke.call_args))

    def test_scroll_container_identity_changes_only_when_a_card_is_added(self):
        from src.ui.layout import canvas_scroll_key
        state = {}
        with patch("src.ui.state.build_workbook_bytes", return_value=b"xlsx"):
            add_canvas(state, self.result)
            original = canvas_scroll_key(state["canvas_scroll_generation"])
            append_chat_message(state, "assistant", "답변")
            self.assertEqual(canvas_scroll_key(state["canvas_scroll_generation"]), original)
            add_canvas(state, self.result)
            self.assertNotEqual(canvas_scroll_key(state["canvas_scroll_generation"]), original)


class ChatFlowTests(unittest.TestCase):
    setUp = flow.UserFlowTests.setUp
    set_responses = flow.UserFlowTests.set_responses
    submit_theme = flow.UserFlowTests.submit_theme
    select_stock = flow.UserFlowTests.select_stock
    open_canvas = flow.UserFlowTests.open_canvas
    submit = flow.UserFlowTests.submit
    assert_no_exception = flow.UserFlowTests.assert_no_exception

    def answer_responses(self, text="현재 선택한 종목의 이익 대비 주가 수준을 보여줍니다.", ids=None):
        self.llm.invoke.side_effect = [
            flow.response({"text": text, "evidence_ids": ["PER"] if ids is None else ids,
                           "follow_up": "이 지표의 한계를 더 확인하시겠습니까?"}),
            flow.response({"checks": {'evidence_match': True, 'time_basis': True, 'question_focus': True, 'explanation': True, 'scope_disclosed': True, 'context_consistent': True}, "supported": True, "answers_question": True, "reason": "",
                           "unit_reviews": [{"id": "intro_0", "reason": "모의 문장 판정", "supported": True}]}),
        ]

    def test_named_company_question_verifies_that_stock_without_theme_candidates(self):
        self.llm.invoke.side_effect=[flow.response(flow.report_payload())]
        self.submit_theme("예시회사 사도 될까?")
        self.assertEqual(self.app.session_state["selected_code"],"005930")
        self.assertEqual(len(self.app.session_state["candidate_result"].candidates),1)
        self.assertIn("dashboard_result",self.app.session_state)
        self.assertNotIn("canvases",self.app.session_state)
        self.listing.assert_called_once()

    def test_followup_keeps_data_and_excel_and_history_without_refetch(self):
        self.submit()
        self.app.button(key="prepare_export_c1").click().run()
        original = self.app.session_state["canvases"][0]["export_bytes"]
        calls = self.ticker.call_count
        self.answer_responses()
        self.submit_theme("이 종목의 지표를 쉽게 설명해줘")
        self.assertEqual(self.ticker.call_count, calls)
        self.assertEqual(self.listing.call_count, 1)
        self.assertEqual(self.app.session_state["canvases"][0]["export_bytes"], original)
        messages = self.app.session_state["chat_messages"]
        self.assertEqual(messages[-1]["target"], "예시회사")
        self.assertEqual(messages[-1]["evidence"][0]["id"], "PER")
        self.assertTrue(messages[-1].get("follow_up"))
        self.assertFalse(any(m.get("report") for m in messages))
        self.assertEqual(len(self.app.session_state["canvases"]), 1)
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
        self.assertEqual(len(self.app.session_state["canvases"]), 1)
        self.assertFalse(any(m.get("report") for m in self.app.session_state["chat_messages"]))

    def test_previous_report_text_is_supplied_to_followup(self):
        self.submit()
        history = self.app.session_state["chat_messages"]
        context = conversation_context(history)
        self.assertTrue(any("종합 분석" in item["text"] for item in context))

    def test_followup_failure_preserves_current_result_and_can_retry(self):
        self.submit()
        self.llm.invoke.side_effect = RuntimeError("secret must not appear")
        self.submit_theme("위험 요인은 뭐야?")
        self.assertEqual(len(self.app.metric), 6)
        self.assertTrue(self.app.error)
        self.assertNotIn("secret", self.app.session_state["chat_messages"][-1]["text"])
        self.assertIn("retry_submission", self.app.session_state)
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
        self.assertEqual(len(self.app.session_state["canvases"]), 1)
        self.assertFalse(any(m.get("report") for m in self.app.session_state["chat_messages"]))
        self.app.button(key="clear_results").click().run()
        self.assert_no_exception()
        self.assertEqual(len(self.app.chat_message), 0)
        self.assertNotIn("chat_messages", self.app.session_state)

    def test_selection_keeps_canvas_empty_until_button(self):
        self.submit_theme("반도체 테마 찾아줘")
        discovery = self.app.session_state["candidate_result"]
        self.select_stock(discovery.candidates[0].code)
        self.assertIn("dashboard_result", self.app.session_state)
        self.assertNotIn("canvases", self.app.session_state)
        self.assertEqual(len(self.app.metric), 0)
        self.open_canvas()
        self.assertEqual(len(self.app.session_state["canvases"]), 1)
        self.assertEqual(len(self.app.metric), 6)

    def test_general_question_does_not_fetch_stocks(self):
        self.answer_responses("주가와 이익의 관계를 나타내는 개념입니다.", [])
        self.submit_theme("PER는 뭐야?")
        self.ticker.assert_not_called()
        self.listing.assert_not_called()
        self.assertEqual(self.app.session_state["chat_messages"][-1]["target"], "일반 설명")

    def test_no_selection_is_not_arbitrarily_analyzed(self):
        self.submit_theme("반도체 테마 찾아줘")
        self.llm.invoke.side_effect = [flow.response({"action": "clarify", "theme": "", "code": ""})]
        self.submit_theme("그 종목 분석해줘")
        self.ticker.assert_not_called()
        self.assertIsNone(self.app.session_state["selected_code"])

    def test_explicit_form_search_and_concept_dialogue_have_separate_actions(self):
        self.app.button(key="guide_find").click().run()
        self.llm.invoke.assert_not_called()
        self.app.button(key="cancel_search").click().run()
        self.submit_theme("PER가 뭐야?")
        self.listing.assert_not_called()
        self.app.button(key="guide_find").click().run()
        self.set_responses()
        self.submit_theme("정보보안")
        self.assertEqual(self.app.session_state["candidate_result"].theme,"정보보안")
        self.ticker.assert_not_called()

    def test_suggested_prompt_fills_composer_without_submitting(self):
        before = list(self.app.session_state.filtered_state.get("chat_messages", ()))
        self.app.button(key="suggested_prompt_0").click().run()
        self.assertEqual(self.app.session_state["composer_text"], "반도체 관련 종목을 찾아줘")
        self.assertEqual(list(self.app.session_state.filtered_state.get("chat_messages", ())), before)
        self.llm.invoke.assert_not_called()
        self.listing.assert_not_called()

    def test_attachment_submission_is_consumed_once(self):
        # AppTest는 파일 업로드를 직접 지원하지 않아 제출 콜백의 큐 경계부터 검사한다.
        old_generation = self.app.session_state.filtered_state.get("composer_generation", 0)
        self.app.session_state["queued_submission"] = ("", [("notes.txt", b"hello")])
        self.app.run()
        self.assert_no_exception()
        self.assertEqual(self.app.session_state["composer_generation"], old_generation + 1)
        self.assertEqual(self.app.session_state["chat_messages"][0]["attachments"][0]["name"], "notes.txt")
        self.submit_theme("안녕하세요")
        self.assertEqual(self.app.session_state["chat_messages"][-2]["attachments"], [])
        self.llm.invoke.assert_not_called()

    def test_old_canvas_related_selection_restores_its_own_candidates(self):
        self.submit()
        original_id = self.app.session_state["canvases"][0]["result_id"]
        self.set_responses()
        self.submit_theme("로봇 테마 찾아줘")
        self.info.update(symbol="247540.KQ", regularMarketPrice=125000, currentPrice=125000, trailingPE=22.5)
        self.llm.invoke.side_effect = [flow.response(flow.report_payload(22.5, stock_name="회사나", price=125000))]
        self.app.button(key="c1_result_related_247540").click().run()
        self.assert_no_exception()
        self.assertEqual(self.app.session_state["candidate_result"].theme, "반도체")
        self.assertEqual(self.app.session_state["selected_code"], "247540")
        self.assertEqual(self.app.session_state["canvases"][0]["result_id"], original_id)
        self.assertEqual(len(self.app.session_state["canvases"]), 1)
        self.open_canvas()
        self.assertEqual(len(self.app.session_state["canvases"]), 2)
        self.app.button(key="prepare_export_c1").click().run()
        self.app.button(key="prepare_export_c2").click().run()
        self.assertEqual(len(self.app.get("download_button")), 2)
        self.app.button(key="close_c2").click().run()
        self.assert_no_exception()
        self.assertEqual(self.app.session_state["canvases"][0]["result_id"], original_id)

    def test_old_canvas_period_change_uses_that_stock_and_keeps_snapshot(self):
        self.submit()
        snapshot = self.app.session_state["canvases"][0]
        self.set_responses()
        self.submit_theme("로봇 테마 찾아줘")
        self.llm.invoke.side_effect = [flow.response(flow.report_payload())]
        self.app.selectbox(key="canvas_period_c1").select("1Y").run()
        self.assert_no_exception()
        self.assertEqual(self.app.session_state["selected_code"], "005930")
        self.assertEqual(self.app.session_state["query_options"].price_period, "1Y")
        self.assertEqual(self.app.session_state["canvases"][0]["result_id"], snapshot["result_id"])
        self.assertEqual(self.app.session_state["canvases"][0]["export_bytes"], snapshot["export_bytes"])
        self.assertEqual(self.app.session_state["canvases"][0]["result"].query_options.price_period, "3M")
