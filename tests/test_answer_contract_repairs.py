"""저장된 실제 실패와 변형된 오답을 네트워크 없이 대조한다."""
from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from src.agents.chat import validate_response, answer_question
from src.agents.answer_quality import QUALITY_CHECKS
from src.agents.report import generate_commentary
from src.agents.report_presentation import HEADLINE_SCOPE
from src.agents.transport import _invoke
from src.agents.rate_control import paced_verification, verification_stop
from src.analysis_flow import analysis_response
from src.config import Settings
from src.models import AppError
from test_answer_blocks import sample_result
from test_question_focused_answers import annuals
from test_report_pipeline import example_financial, example_news, example_payload
from review_fixtures import with_review_units


FIXTURE = Path(__file__).parent / "fixtures" / "financial_literal_regression.json"
SETTINGS = Settings("fake", "model", "fake", "fake")


class FinancialLiteralTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.saved = json.loads(FIXTURE.read_text(encoding="utf-8"))

    def test_both_saved_failures_pass_numeric_structure_without_rewriting_text(self):
        for payload in self.saved["responses"]:
            with self.subTest(text=payload["text"]):
                response = validate_response(payload, self.saved["evidence"], "plain")
                self.assertEqual(response.text, payload["text"])

    def test_saved_single_year_failure_and_leading_year_are_bound_to_the_claim(self):
        saved = json.loads((FIXTURE.parent / "financial_single_year_regression.json").read_text(encoding="utf-8"))
        for payload in saved["responses"]:
            self.assertEqual(validate_response(payload, self.saved["evidence"], "plain").text, payload["text"])
        payload = deepcopy(self.saved["responses"][0])
        payload["text"] = "2025년 매출은 20% 증가했습니다. 2025년 영업이익은 80% 증가했습니다."
        self.assertEqual(validate_response(payload, self.saved["evidence"], "plain").text, payload["text"])

    def test_single_year_cannot_borrow_another_sentences_values_or_unknown_events(self):
        for text in (
            "매출이 20% 증가한 2023년에도 실적이 개선됐습니다.",
            "2024년 매출은 20% 증가했습니다.",
            "매출은 20% 증가했습니다. 2025년 계약을 체결했습니다.",
            "2025년 계약을 체결했고 매출은 20% 증가했습니다.",
            "매출은 20% 증가했습니다. 2024년 대비 2025년 계약이 증가했습니다.",
            "2024년 대비 2025년 계약이 늘었고 매출은 20% 증가했습니다.",
            "2025년 매출은 21% 증가했습니다.",
        ):
            payload = dict(text=text, evidence_ids=["CMP_2024_2025_CFS_REVENUE"], follow_up="", blocks=[])
            with self.subTest(text=text), self.assertRaises(AppError) as caught:
                validate_response(payload, self.saved["evidence"], "plain")
            self.assertEqual(caught.exception.code, "chat_numbers")

    def test_wrong_value_item_direction_unit_period_and_unknown_number_are_rejected(self):
        for before, after in (("20%", "21%"), ("매출이 20%", "영업이익은 20%"),
                              ("5%p", "5%"), ("2024년", "2023년"),
                              ("2024년 대비 2025년", "2025년 대비 2024년"),
                              ("80% 증가", "80% 감소"), ("80% 증가", "-80% 증가"),
                              ("5%p 상승", "5%p 하락")):
            payload = deepcopy(self.saved["responses"][0])
            payload["text"] = payload["text"].replace(before, after)
            with self.subTest(after=after), self.assertRaises(AppError) as caught:
                validate_response(payload, self.saved["evidence"], "plain")
            self.assertEqual(caught.exception.code, "chat_numbers")
        payload["text"] = "목표 매출은 999억원입니다."
        with self.assertRaises(AppError):
            validate_response(payload, self.saved["evidence"], "plain")

    def test_unreferenced_and_ambiguous_basis_values_are_not_accepted(self):
        payload = deepcopy(self.saved["responses"][0])
        payload["evidence_ids"].remove("CMP_2024_2025_CFS_REVENUE")
        with self.assertRaises(AppError):
            validate_response(payload, self.saved["evidence"], "plain")
        evidence = deepcopy(self.saved["evidence"])
        evidence["OTHER_REVENUE"] = dict(evidence["CMP_2024_2025_CFS_REVENUE"], fs_div="OFS")
        payload = deepcopy(self.saved["responses"][0])
        payload["evidence_ids"].append("OTHER_REVENUE")
        with self.assertRaises(AppError):
            validate_response(payload, evidence, "plain")

    def test_wrong_financial_value_cannot_borrow_an_identical_roe_value(self):
        evidence = deepcopy(self.saved["evidence"])
        evidence["ROE"] = {"value": 21, "status": "ok"}
        payload = deepcopy(self.saved["responses"][0])
        payload["text"] = "매출은 21% 증가했습니다."
        payload["evidence_ids"].append("ROE")
        with self.assertRaises(AppError) as caught:
            validate_response(payload, evidence, "plain")
        self.assertEqual(caught.exception.code, "chat_numbers")

    def test_saved_response_reaches_semantic_review_but_does_not_bypass_it(self):
        result = replace(sample_result(), annual_summaries=annuals())
        payload = self.saved["responses"][0]
        verdict = dict(checks=dict.fromkeys(QUALITY_CHECKS, True), supported=True, answers_question=True)
        with patch("src.agents.chat._invoke", side_effect=with_review_units([payload, verdict])) as invoke:
            response = answer_question("매출이 늘었으면 실적이 좋아진 거야?", result, [], SETTINGS)
        self.assertIn("20%", response.text)
        self.assertEqual(invoke.call_args_list[1].args[2]["task"], "chat_grounding_review")
        rejected = dict(verdict, supported=False)
        with patch("src.agents.chat._invoke", side_effect=with_review_units([payload, rejected, payload, rejected])):
            with self.assertRaises(AppError) as caught:
                answer_question("매출이 늘었으면 실적이 좋아진 거야?", result, [], SETTINGS)
        self.assertEqual(caught.exception.code, "chat_grounding")


class ReportContractTests(unittest.TestCase):
    def test_financial_reviewer_receives_visible_footer_basis_without_repeating_it_in_body(self):
        from src.source_presentation import data_source_label
        from src.ui.answer import source_groups, render_sources
        result = replace(sample_result(), annual_summaries=annuals())
        saved = json.loads((FIXTURE.parent / "financial_single_year_regression.json").read_text(encoding="utf-8"))
        payload = saved["responses"][0]
        verdict = dict(checks=dict.fromkeys(QUALITY_CHECKS, True), supported=True, answers_question=True)
        with patch("src.agents.chat._invoke", side_effect=with_review_units([payload, verdict])) as invoke:
            response = answer_question("매출이 늘었으면 실적이 좋아진 거야?", result, [], SETTINGS)
        review = invoke.call_args_list[1].args[2]
        labels = {data_source_label(item) for item in response.evidence}
        self.assertEqual({s["label"] for s in review["displayed_data_sources"]}, labels)
        self.assertEqual({s["evidence_id"] for s in review["displayed_data_sources"]}, set(payload["evidence_ids"]))
        self.assertTrue(all("2024년 → 2025년 연간 · 연결" in label for label in labels))
        self.assertEqual(response.text, payload["text"])
        groups, _ = source_groups({"evidence": response.evidence})
        with patch("src.ui.answer.st") as ui:
            render_sources(groups)
        displayed = [call.args[0] for call in ui.caption.call_args_list]
        self.assertTrue(all(any(label in line for line in displayed) for label in labels))

    def test_short_report_review_sees_same_scope_and_blocks_as_display(self):
        payload = dict(example_payload(), stock_comment="", opportunity=None, risk=None, summary=None)
        payload["theme_trend"] = [{"text": "신규 생산라인 가동 계획이 발표되었습니다.", "news_ids": [1]}]
        verdict = dict(checks=dict.fromkeys(QUALITY_CHECKS, True), supported=True, answers_question=True)
        with patch("src.agents.report._invoke", side_effect=with_review_units([payload, verdict])) as invoke:
            commentary = generate_commentary("반도체", example_financial(), example_news(), SETTINGS)
        review = invoke.call_args_list[1].args[2]
        display = analysis_response(replace(sample_result(), commentary=commentary))
        self.assertIn(HEADLINE_SCOPE, review["answer"])
        self.assertIn(HEADLINE_SCOPE, display.intro)
        self.assertIn("간단히 요약", review["question"])
        self.assertTrue(any("심층 분석" in text for text in review["answer_requirements"]))
        for block in display.blocks:
            if any(key.startswith("NEWS_") for key in block.evidence_ids):
                self.assertIn(block.text, review["answer"])
                self.assertIn(block.title, review["answer"])

    def test_financial_per_news_and_new_stock_use_current_evidence_through_conversation(self):
        result = replace(sample_result(), annual_summaries=annuals())
        history = []
        verdict = dict(checks=dict.fromkeys(QUALITY_CHECKS, True), supported=True, answers_question=True)
        finance_id = "CMP_2024_2025_CFS_REVENUE"
        cases = [
            ("매출을 설명해줘", "매출은 {{" + finance_id + "}}입니다.", [finance_id]),
            ("그럼 PER은 어떻게 해석해?", "PER은 {{PER}}로 주가를 주당순이익으로 나눈 배수입니다.", ["PER"]),
            ("관련 뉴스를 짧게 요약해줘", "생산라인 가동 계획이 보도되었습니다.", ["NEWS_1"]),
        ]
        for question, text, ids in cases:
            payload = dict(text=text, evidence_ids=ids, follow_up="", blocks=[])
            with patch("src.agents.chat._invoke", side_effect=with_review_units([payload, verdict])) as invoke:
                response = answer_question(question, result, history, SETTINGS)
            request = invoke.call_args_list[0].args[2]
            if ids == ["PER"]:
                self.assertEqual(set(request["evidence"]), {"PER"})
            if ids == ["NEWS_1"]:
                self.assertTrue(all(k.startswith("NEWS_") for k in request["evidence"]))
                self.assertIn("뉴스 제목", response.intro)
            history.extend([{"role": "user", "text": question}, {"role": "assistant", "text": response.text}])
        next_stock = replace(result.financial.stock, name="다른가상회사", code="654321", ticker="654321.KS")
        result = replace(result, result_id="next-fixture", selected_code=next_stock.code, candidates=(next_stock,),
                         financial=replace(result.financial, stock=next_stock, per=17.0))
        payload = dict(text="PER은 {{PER}}입니다.", evidence_ids=["PER"], follow_up="", blocks=[])
        with patch("src.agents.chat._invoke", side_effect=with_review_units([payload, verdict])) as invoke:
            response = answer_question("이 종목의 PER을 설명해줘", result, history, SETTINGS)
        current = invoke.call_args_list[0].args[2]["evidence"]["PER"]
        self.assertEqual(current["stock_code"], "654321")
        self.assertEqual(current["result_id"], "next-fixture")
        self.assertIn("17.00배", response.text)


class WrappedBudgetTests(unittest.TestCase):
    def test_actual_sdk_budget_halt_reaches_caller_without_any_socket(self):
        with paced_verification(max_requests=1) as pacer, patch("socket.socket.connect", side_effect=AssertionError("network forbidden")) as connect:
            pacer.request_count = 1
            with self.assertRaises(AppError) as caught:
                _invoke(SETTINGS, "test", {}, 100)
            self.assertEqual(caught.exception.code, "ai_verification_budget")
            self.assertEqual(pacer.request_count, 1)
            connect.assert_not_called()

    def test_actual_sdk_halted_and_long_wait_are_preserved(self):
        for mode in ("halted", "wait"):
            with self.subTest(mode=mode), paced_verification() as pacer, patch("socket.socket.connect") as connect:
                if mode == "halted":
                    pacer.halted = True
                else:
                    pacer.next_at = pacer.clock() + 1000
                with self.assertRaises(AppError) as caught:
                    _invoke(SETTINGS, "test", {}, 100)
                self.assertEqual(caught.exception.code, "ai_rate_limit")
                self.assertEqual(pacer.request_count, 0)
                connect.assert_not_called()

    def test_ordinary_connection_failure_stays_ai_failed_and_cycles_terminate(self):
        error = RuntimeError("ai_verification_budget text is not a trusted stop")
        error.__cause__ = error
        self.assertIsNone(verification_stop(error))
        with paced_verification(), patch("langchain_groq.ChatGroq") as factory:
            factory.return_value.invoke.side_effect = error
            with self.assertRaises(AppError) as caught:
                _invoke(SETTINGS, "test", {}, 100)
        self.assertEqual(caught.exception.code, "ai_failed")
