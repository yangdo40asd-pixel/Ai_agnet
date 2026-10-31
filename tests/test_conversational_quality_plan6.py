"""계획6 15절 단계 N~R 및 27·28절 대화 품질·반례·코드 지뢰(Trap 1~11) 회귀 검사."""

from dataclasses import replace
from decimal import Decimal
import unittest
from unittest.mock import patch

from src.analysis_flow import analysis_response
from src.agents.answer_quality import select_evidence, ordinal_news_key
from src.agents.chat import (
    CHAT_INSTRUCTION,
    answer_question,
    conversation_context,
    infer_implicit_metrics,
    recover_evidence_ids,
    validate_answer,
)
from src.agents.evidence import build_evidence
from src.agents.financial_numbers import normalize_financial_units
from src.agents.report import _comment_text, asserts_valuation
from src.agents.report_presentation import HEADLINE_SCOPE
from src.agents.request import company_to_lookup, is_evaluation_question, route_message
from src.config import Settings
from src.models import (
    AnnualFinancialSummary,
    AppError,
    CandidateDiscoveryResult,
    StockCandidate,
    now_kst,
)
from src.ui.answer import DISCLAIMER_TEXT, clean_display_lead, follow_up_suggestions
from test_answer_blocks import sample_result
from test_question_focused_answers import annuals


class ConversationalQualityPlan6Tests(unittest.TestCase):
    def setUp(self):
        base = sample_result()
        self.result = replace(
            base,
            annual_summaries=annuals(),
            commentary=replace(base.commentary, stock_comment=""),
        )
        self.evidence = build_evidence(self.result)
        self.settings = Settings("fake", "model", "fake", "fake", ai_provider="local", news_relevance_mode="strict")

    def test_scenario1_concept_question_has_no_api_call_and_explains_value_trap(self):
        with patch("src.agents.chat._invoke") as invoke:
            answer, refs, _ = answer_question("PER이 뭐야?", self.result, [], self.settings)
        invoke.assert_not_called()
        self.assertEqual(refs, [])
        self.assertIn("주가 ÷ 주당순이익", answer)
        self.assertIn("낮은 PER이 곧바로 저평가를 의미하지는 않으며", answer)
        self.assertFalse(asserts_valuation(answer))

    def test_scenario2_metric_value_question_includes_meaning_without_unconfirmed_period_claim(self):
        with patch("src.agents.chat._invoke") as invoke:
            answer, refs, _ = answer_question("삼성전자 PER은 얼마야?", self.result, [], self.settings)
        invoke.assert_not_called()
        self.assertEqual(refs[0]["id"], "PER")
        self.assertIn("15.20배입니다", answer)
        self.assertIn("주당순이익의 15.20배 수준", answer)
        self.assertNotIn("최근 결산", answer)

    def test_scenario3_evaluation_routing_and_conditional_valuation_boundaries(self):
        self.assertTrue(is_evaluation_question("삼성전자 PER은 어떤 편이야?"))
        self.assertTrue(is_evaluation_question("그럼 어떤 편이야?"))
        history = [{"role": "user", "text": "삼성전자 PER은 얼마야?"}, {"role": "assistant", "text": "PER 15.20배입니다."}]
        intent = route_message("그럼 어떤 편이야?", None, "005930", history, self.settings)
        self.assertEqual((intent.action, intent.scope), ("answer", "finance"))
        self.assertEqual(infer_implicit_metrics("그럼 어떤 편이야?", history), ["PER"])

        # 조건 A: 비교군 부재 시 평가 유보 문장은 허용, 단정적 저평가·평균 비교는 차단
        cond_a = (
            "현재 확인된 PER은 {{PER}}입니다. 현재 업종 평균 PER이나 과거 밴드 비교 자료가 제공되지 않아 "
            "고평가나 저평가 여부를 단정하기 어렵습니다. 적정 수준을 판단하려면 동종 기업 멀티플 비교가 필요합니다."
        )
        self.assertFalse(asserts_valuation(cond_a))
        checked, _ = validate_answer({"text": cond_a, "evidence_ids": ["PER"], "follow_up": ""}, self.evidence)
        self.assertIn("15.20배", checked)

        # 조건 B: 비교군이 근거에 있을 때 '배' 단위 차이는 허용, '배p' 단위는 거절
        ev_with_peer = dict(self.evidence)
        ev_with_peer["PEER_PER"] = {
            "id": "PEER_PER",
            "text": "동종 업계 평균 PER 18.50배",
            "value": 18.5,
            "value_text": "18.50배",
            "unit": "배",
            "status": "ok",
            "source": "업종 비교 자료",
        }
        cond_b = (
            "현재 PER은 {{PER}}로 동종 업계 평균({{PEER_PER}})보다 3.30배 낮습니다. "
            "다만 기업별 이익 지속성이 다르므로 단순 배수 차이만으로 저평가 여부를 단정하기 어렵습니다."
        )
        checked_b, _ = validate_answer({"text": cond_b, "evidence_ids": ["PER", "PEER_PER"], "follow_up": ""}, ev_with_peer)
        self.assertIn("3.30배 낮습니다", checked_b)
        with self.assertRaises(AppError) as bad_unit:
            validate_answer(
                {"text": cond_b.replace("3.30배 낮습니다", "3.30배p 낮습니다"), "evidence_ids": ["PER", "PEER_PER"], "follow_up": ""},
                ev_with_peer,
            )
        self.assertEqual(bad_unit.exception.code, "chat_numbers")

    def test_scenario3_fallback_for_evaluation_question_uses_refined_explanation(self):
        bad_payload = {"text": "PER는 평균 수준에 가깝습니다.", "evidence_ids": ["PER"], "follow_up": ""}
        with patch("src.agents.chat._invoke", return_value=bad_payload) as invoke:
            answer, refs, _ = answer_question("삼성전자 PER은 어떤 편이야?", self.result, [], self.settings)
        self.assertEqual(invoke.call_count, 2)
        self.assertEqual(refs[0]["answer_origin"], "verified_metric_fallback")
        self.assertIn("15.20배", answer)
        self.assertNotIn("AI의 추가 해석은 검증하지 못해", answer)
        self.assertIn("단정은 유보하며", answer)

    def test_scenario4_financial_conditions_and_number_trap_repairs(self):
        cmp_ids = [
            "CMP_2024_2025_CFS_REVENUE",
            "CMP_2024_2025_CFS_OPERATING_INCOME",
            "CMP_2024_2025_CFS_OPERATING_MARGIN",
        ]
        # 조건 A: 두괄식 당기 연도 요약 문장, 자연어 수식어(전년 대비), 괄호 표기, 배수 비교(4배 빠르게), 서수 표현 허용
        natural_a = (
            "2025년 가상검수회사의 실적은 전년 대비 매출과 영업이익 모두 큰 폭으로 개선되었습니다. "
            "제공된 최근 2개년 연결 실적 기준 수익성이 전반적으로 개선되었습니다. "
            "매출은 전년 대비 20.00% 증가했고 영업이익은 전년 대비 80.00% 증가해 매출 증가율(20.00%)보다 4배 빠르게 증가했으며, "
            "영업이익률은 5.00%p 상승했습니다."
        )
        checked_a, _ = validate_answer({"text": natural_a, "evidence_ids": cmp_ids, "follow_up": ""}, self.evidence)
        self.assertIn("4배 빠르게", checked_a)

        # Trap 10: 영업이익률 변동폭 수치 일치 시 % -> %p 자동 정규화
        raw_margin_pct = "매출은 20.00% 증가했고 영업이익은 80.00% 증가했으며 영업이익률은 5.00% 상승했습니다."
        normalized = normalize_financial_units(raw_margin_pct, self.evidence)
        self.assertIn("5.00%p 상승", normalized)
        self.assertEqual(normalize_financial_units("영업이익률은 9.00% 상승했습니다.", self.evidence), "영업이익률은 9.00% 상승했습니다.")

        # 조건 B: 매출 급증 + 영업이익 소폭 증가 + 영업이익률 하락 반례
        margin_drop_annuals = (
            AnnualFinancialSummary("2024", revenue=10_000_000_000, operating_income=1_000_000_000),
            AnnualFinancialSummary("2025", revenue=12_500_000_000, operating_income=1_050_000_000),
        )
        drop_result = replace(self.result, annual_summaries=margin_drop_annuals)
        drop_ev = build_evidence(drop_result)
        cond_b_text = (
            "매출은 전년 대비 25.00% 증가했으나 영업이익은 5.00% 증가에 그쳐 영업이익률은 1.60%p 하락했습니다. "
            "외형 성장에도 불구하고 매출 대비 수익성은 약화된 것으로 나타나며, 구체적인 비용 요인은 사업보고서 원문 등 추가 자료 확인이 필요합니다."
        )
        checked_b, _ = validate_answer({"text": cond_b_text, "evidence_ids": cmp_ids, "follow_up": ""}, drop_ev)
        self.assertIn("1.60%p 하락", checked_b)

        # 조건 C: 전년도 적자(-) -> 당해연도 흑자(+) 전환 반례
        turnaround_annuals = (
            AnnualFinancialSummary("2024", revenue=10_000_000_000, operating_income=-500_000_000),
            AnnualFinancialSummary("2025", revenue=12_000_000_000, operating_income=1_000_000_000),
        )
        turn_result = replace(self.result, annual_summaries=turnaround_annuals)
        turn_ev = build_evidence(turn_result)
        self.assertIsNone(turn_ev["CMP_2024_2025_CFS_OPERATING_INCOME"]["change_pct"])
        self.assertIn("흑자 전환", turn_ev["CMP_2024_2025_CFS_OPERATING_INCOME"]["text"])
        cond_c_text = "매출은 20.00% 증가했고 영업이익은 {{CMP_2024_2025_CFS_OPERATING_INCOME}}하며 수익성이 개선되었습니다."
        checked_c, _ = validate_answer(
            {"text": cond_c_text, "evidence_ids": ["CMP_2024_2025_CFS_REVENUE", "CMP_2024_2025_CFS_OPERATING_INCOME"], "follow_up": ""},
            turn_ev,
        )
        self.assertIn("흑자 전환", checked_c)

    def test_scenario5_causal_followup_selects_financials_and_injects_two_step_protocol(self):
        history = [{"role": "user", "text": "삼성전자 최근 실적이 좋아졌어?"}]
        selection = select_evidence("왜 그렇게 크게 증가했어?", history, self.evidence, [], strict=True)
        self.assertEqual(selection.reason, "financials")
        self.assertTrue(any("인과·원인 질문입니다" in req for req in selection.requirements))
        self.assertTrue(any("순환 논증하지 않습니다" in req for req in selection.requirements))

    def test_scenario6_ordinal_news_selection_and_ui_lead_cleanup(self):
        self.assertEqual(ordinal_news_key("두 번째 뉴스 자세히 설명해 줘"), "NEWS_2")
        self.assertEqual(ordinal_news_key("최근 주요 이슈 세 개 요약해 줘"), "")
        selection = select_evidence("두 번째 뉴스 자세히 설명해 줘", [], self.evidence, [], strict=True)
        self.assertEqual(selection.reason, "news")
        self.assertIn("NEWS_2", selection.evidence)
        self.assertNotIn("NEWS_1", selection.evidence)
        self.assertIn("NEWS_2", selection.required_ids)

        display = analysis_response(self.result)
        self.assertIn("요약해 드립니다", display.intro)
        self.assertIn(HEADLINE_SCOPE, display.intro)
        cleaned = clean_display_lead(display.intro)
        self.assertNotIn(HEADLINE_SCOPE, cleaned)
        self.assertIn("삼성전자 조회 결과", cleaned)
        chips = follow_up_suggestions({"target": "삼성전자", "follow_up": "동종 업계와 비교해 볼까요?"})
        self.assertEqual(len(chips), 3)
        self.assertEqual(chips[0], "동종 업계와 비교해 볼까요?")
        self.assertTrue(DISCLAIMER_TEXT.startswith("⚠️ 투자 유의사항:"))

    def test_hybrid_evidence_recovery_and_multiturn_sliding_window_and_stock_switch(self):
        raw = {
            "text": "현재 PER은 {{PER}}입니다.",
            "evidence_ids": ["PER", "PER"],
            "follow_up": "",
            "blocks": [{"title": "소식", "text": "내용입니다.", "evidence_ids": ["NEWS_1", "NEWS_1"]}],
        }
        recovered = recover_evidence_ids(raw, self.evidence)
        self.assertEqual(recovered["evidence_ids"], ["PER"])
        self.assertEqual(recovered["blocks"][0]["evidence_ids"], ["NEWS_1"])

        # 1:1 종목 전환 라우팅 (Trap 9)
        self.assertEqual(company_to_lookup("SK하이닉스로 바꿔서 비교해줘"), "SK하이닉스")
        discovery = CandidateDiscoveryResult(
            "반도체",
            (
                StockCandidate("삼성전자", "005930", "KOSPI", "005930.KS"),
                StockCandidate("SK하이닉스", "000660", "KOSPI", "000660.KS"),
            ),
            now_kst(),
        )
        switched = route_message("SK하이닉스로 바꿔서 비교해줘", discovery, "005930", [], self.settings)
        self.assertEqual((switched.action, switched.code), ("select", "000660"))
        lookup_intent = route_message("한미반도체로 바꿔서 비교해줘", discovery, "005930", [], self.settings)
        self.assertEqual((lookup_intent.action, lookup_intent.company), ("lookup", "한미반도체"))

        # 4K 슬라이딩 윈도우 대화 문맥 압축 (P6-Q05)
        long_text = "첫 번째 핵심 결론 문장입니다. " + ("매우 긴 부연 설명이 이어집니다. " * 20)
        messages = [
            {"role": "user", "text": "첫 질문"},
            {"role": "assistant", "text": long_text},
            {"role": "user", "text": "두 번째 질문"},
            {"role": "assistant", "text": long_text},
        ]
        ctx = conversation_context(messages)
        self.assertEqual(len(ctx), 4)
        self.assertLessEqual(len(ctx[1]["text"]), 180)
        self.assertGreater(len(ctx[3]["text"]), 180)

        # Trap 6: 자연스러운 수동태 종목 소유격 허용 및 주어-서술어 불일치 차단 유지
        self.assertEqual(
            _comment_text("예시회사의 신규 반도체 라인 가동 계획이 발표되었습니다.", "반도체", "예시회사"),
            "예시회사의 신규 반도체 라인 가동 계획이 발표되었습니다.",
        )
        with self.assertRaises(AppError):
            _comment_text("예시회사의 신규 반도체 라인 가동 계획을 발표했습니다.", "반도체", "예시회사")
        self.assertIn("두괄식 직접 답변 원칙", CHAT_INSTRUCTION)


if __name__ == "__main__":
    unittest.main()
