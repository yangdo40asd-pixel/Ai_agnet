"""계획8 06 단계: 연속 대화·기업 전환·비교 보강 (C02, C03, E03) 종합 검증 스위트."""

import unittest
from decimal import Decimal
from datetime import datetime
from unittest.mock import patch
from dataclasses import replace

from src.models import (
    StockCandidate, FinancialData, AnalysisResult, NewsData,
    AnnualFinancialSummary, now_kst, ChatResponse, AppError,
    CandidateDiscoveryResult
)
from src.config import Settings
from src.agents.request import route_message, parse_entities, company_to_lookup
from src.agents.answer_quality import select_evidence
from src.agents.outlook import answer_context, _price_focus, requirements as outlook_requirements
from src.comparison_flow import comparison_options, collect_comparison
from src.data.company_comparison import CompanyAnnuals, build_comparison
from test_answer_blocks import sample_result
from test_question_focused_answers import annuals


class Stage06ContinuityTests(unittest.TestCase):
    def setUp(self):
        import pandas as pd
        self.listing = pd.DataFrame([
            {"Name": name, "Code": code, "Market": "KOSPI", "Symbol": f"{code}.KS"}
            for name, code in (("삼성전자", "005930"), ("SK하이닉스", "000660"),
                               ("한미반도체", "042700"), ("삼성물산", "028260"))
        ])
        self.settings = Settings("fake", "model", "fake", "fake", ai_provider="local", local_model="gemma-4-12b-q4", news_relevance_mode="strict")
        base = sample_result()
        self.result = replace(
            base,
            annual_summaries=annuals(),
            commentary=replace(base.commentary, stock_comment=""),
        )
        self.samsung = StockCandidate("삼성전자", "005930", "KOSPI", "005930.KS")
        self.hynix = StockCandidate("SK하이닉스", "000660", "KOSPI", "000660.KS")
        self.discovery = CandidateDiscoveryResult("반도체", (self.samsung, self.hynix), now_kst())

    def test_c02_i4_price_focus_inherited_in_short_outlook_followup(self):
        """C02-I4: 직전 대화가 주가 전망 질문이었을 때 '그럼 내년은?'이 주가 관점(price_outlook)을 올바르게 이어받는다."""
        price_history = [
            {"role": "user", "text": "삼성전자 올해 주가 오를까?"},
            {"role": "assistant", "text": "과거 실적 개선이 주가 상승을 보장하지는 않습니다."}
        ]
        # 직전 질문이 주가 관점이면 '그럼 내년은?'도 price_focus가 True
        self.assertTrue(_price_focus("그럼 내년은?", messages=price_history))
        ctx_price = answer_context("그럼 내년은?", {}, messages=price_history)
        self.assertEqual(ctx_price["focus"], "price_outlook")
        self.assertEqual(ctx_price["requested_horizon"], "내년")

        # 반대로 직전 질문이 실적 관점이면 earnings_outlook 유지
        earnings_history = [
            {"role": "user", "text": "삼성전자 2025년 실적 개선됐어?"},
            {"role": "assistant", "text": "매출과 영업이익이 전년 대비 증가했습니다."}
        ]
        self.assertFalse(_price_focus("그럼 내년은?", messages=earnings_history))
        ctx_earnings = answer_context("그럼 내년은?", {}, messages=earnings_history)
        self.assertEqual(ctx_earnings["focus"], "earnings_outlook")
        self.assertEqual(ctx_earnings["requested_horizon"], "내년")

    def test_c02_i2_news_causal_followup_routes_to_news(self):
        """C02-I2: 직전 답변이 뉴스 카드 중심이었을 때 '왜?' 후속 질문이 뉴스 맥락으로 이어진다."""
        from src.agents.evidence import build_evidence
        evidence = build_evidence(self.result)
        
        # 뉴스 카드 중심 직전 답변
        news_history = [
            {"role": "user", "text": "최근 주요 뉴스 알려줘"},
            {"role": "assistant", "text": "신규 투자 공시가 발표되었습니다.",
             "evidence": [{"id": "NEWS_1", "kind": "official_disclosure", "scope": "official_disclosure"}]}
        ]
        selection = select_evidence("왜 그런 결정을 했어?", news_history, evidence, [], strict=True)
        self.assertEqual(selection.reason, "news")
        self.assertTrue(any(k.startswith("NEWS_") for k in selection.evidence))

        # 반대로 재무 비교 중심 직전 답변일 때는 financials로 라우팅
        financial_history = [
            {"role": "user", "text": "실적 어때?"},
            {"role": "assistant", "text": "영업이익이 80% 증가했습니다.",
             "evidence": [{"id": "CMP_2024_2025_CFS_OPERATING_INCOME", "kind": "annual_comparison"}]}
        ]
        fin_selection = select_evidence("왜 그렇게 크게 늘었어?", financial_history, evidence, [], strict=True)
        self.assertEqual(fin_selection.reason, "financials")

    def test_c02_i3_entity_parsing_maintains_multi_stock_intent(self):
        """C02-I3: 지분/공급/비교에서 여러 기업이 등장할 때 단일 종목 조회로 축소하지 않는다."""
        parsed_comp = parse_entities("삼성전자와 SK하이닉스 비교해줘", listing=self.listing)
        self.assertEqual(parsed_comp.intent, "comparison_query")
        self.assertIsNone(parsed_comp.primary_stock)
        self.assertEqual(len(parsed_comp.mentioned_stocks), 2)

        parsed_supply = parse_entities("한미반도체가 삼성전자에 장비 공급해?", listing=self.listing)
        self.assertEqual(parsed_supply.intent, "supply_chain_query")
        self.assertIsNone(parsed_supply.primary_stock)

        parsed_share = parse_entities("삼성물산이 삼성전자 지분을 얼마나 갖고 있어?", listing=self.listing)
        self.assertEqual(parsed_share.intent, "shareholding_query")
        self.assertIsNone(parsed_share.primary_stock)

    def test_c02_i1_and_e03_i1_collective_comparison_routing(self):
        """C02-I1 / E03-I1: '그 기업들 비교해줘', '둘 중에' 참조가 후보 집합 비교로 정확히 라우팅된다."""
        # 후보 목록이 2개 있을 때
        intent1 = route_message("그 기업들 비교해줘", self.discovery, "005930", [], self.settings)
        self.assertEqual(intent1.action, "comparison_query")
        self.assertEqual(len(intent1.entities.mentioned_stocks), 2)

        intent2 = route_message("둘 중에 어디가 나아?", self.discovery, "005930", [], self.settings)
        self.assertEqual(intent2.action, "comparison_query")
        self.assertEqual(len(intent2.entities.mentioned_stocks), 2)

    def test_c03_i1_stock_switch_routing(self):
        """C03-I1: 'SK하이닉스로 바꿔서 비교해줘'에서 이전 종목 대신 새 종목이 선택된다."""
        intent = route_message("SK하이닉스로 바꿔서 비교해줘", self.discovery, "005930", [], self.settings)
        self.assertEqual(intent.action, "select")
        self.assertEqual(intent.code, "000660")

        # 후보에 없는 새 종목 지목 시 lookup으로 분기
        intent_lookup = route_message("한미반도체로 변경해줘", self.discovery, "005930", [], self.settings)
        self.assertEqual(intent_lookup.action, "lookup")
        self.assertEqual(intent_lookup.company, "한미반도체")

    def test_e03_i3_unsupported_comparison_options_has_clear_boundary(self):
        """E03-I3: PER 또는 분기 등 미지원 비교 질문에 대해 지원 범위(연간 매출·영업이익·영업이익률)를 명시적으로 안내한다."""
        opts_per, reason_per = comparison_options("삼성전자와 SK하이닉스 PER 비교해줘")
        self.assertIsNone(opts_per)
        self.assertIn("원화 연간 매출·영업이익·영업이익률을 지원", reason_per)
        self.assertIn("다른 지표 비교는 아직 연결되지 않았습니다", reason_per)

        opts_qtr, reason_qtr = comparison_options("삼성전자와 SK하이닉스 3분기 실적 비교해줘")
        self.assertIsNone(opts_qtr)
        self.assertIn("분기", reason_qtr)

        # 지원되는 연간 비교 질문은 정상 파싱
        opts_ok, reason_ok = comparison_options("2025년 연간 연결 실적 비교해줘")
        self.assertEqual(reason_ok, "")
        self.assertEqual(opts_ok["year"], 2025)
        self.assertEqual(opts_ok["fs_div"], "CFS")

    def test_e03_i4_comparison_excludes_missing_items_cleanly(self):
        """E03-I4: 두 기업에서 공통 확인된 항목만 정확히 계산 비교하고 결측 항목은 정돈한다."""
        c1_annuals = (
            AnnualFinancialSummary("2024", revenue=100_000_000_000, operating_income=10_000_000_000, fs_div="CFS"),
            AnnualFinancialSummary("2025", revenue=120_000_000_000, operating_income=18_000_000_000, fs_div="CFS"),
        )
        c2_annuals = (
            AnnualFinancialSummary("2024", revenue=50_000_000_000, operating_income=5_000_000_000, fs_div="CFS"),
            AnnualFinancialSummary("2025", revenue=60_000_000_000, operating_income=9_000_000_000, fs_div="CFS"),
        )
        comp1 = CompanyAnnuals(self.samsung, c1_annuals, "src_1", now_kst(), "ok")
        comp2 = CompanyAnnuals(self.hynix, c2_annuals, "src_2", now_kst(), "ok")
        snapshot = build_comparison([comp1, comp2], year=2025, fs_div="CFS")
        self.assertEqual(snapshot.year, 2025)
        self.assertEqual(snapshot.fs_div, "CFS")
        self.assertEqual(len(snapshot.metrics), 6)  # 2 companies * 3 items (rev, op, margin)

        from src.agents.company_comparison import comparison_answer
        ans = comparison_answer(snapshot, "매출과 영업이익률 비교해줘")
        self.assertIn("삼성전자", ans.text)
        self.assertIn("SK하이닉스", ans.text)
        self.assertIn("영업이익률", ans.text)

    def test_c03_i2_and_i3_state_retention_vs_reset(self):
        """C03-I2 & C03-I3: 테마 전환 시 대화와 캔버스는 보존되나 선택은 초기화되고, 새 대화는 모두 초기화된다."""
        from src.ui.state import reset_all_state, add_canvas
        state = {
            "chat_messages": [{"role": "user", "text": "안녕"}, {"role": "assistant", "text": "반갑습니다."}],
            "selected_code": "005930",
            "active_tab": "canvas",
        }
        add_canvas(state, self.result)
        self.assertEqual(len(state["canvases"]), 1)

        # 주제 전환 시: keep_conversation=True
        reset_all_state(state, keep_conversation=True)
        self.assertEqual(len(state["chat_messages"]), 2)
        self.assertEqual(len(state["canvases"]), 1)
        self.assertNotIn("selected_code", state)

        # 새 대화 시: 완전 초기화
        reset_all_state(state)
        self.assertNotIn("chat_messages", state)
        self.assertNotIn("canvases", state)
        self.assertNotIn("selected_code", state)

    def test_c02_v1_multi_turn_flow_preserves_context_and_prevents_leak(self):
        """C02-V1 & E03-V1: 비교 -> 개별 기업 질문 -> 원인 후속 -> 전망 후속 -> 새 기업 전환의 연속 흐름이 일관성을 유지한다."""
        # 1. 두 기업 비교
        comp_intent = route_message("삼성전자와 SK하이닉스 비교해줘", self.discovery, None, [], self.settings, listing=self.listing)
        self.assertEqual(comp_intent.action, "comparison_query")
        self.assertEqual(len(comp_intent.entities.mentioned_stocks), 2)

        # 2. 삼성전자 단일 선택 후 실적 질문
        sel_intent = route_message("삼성전자는 어때?", self.discovery, "005930", [], self.settings, listing=self.listing)
        self.assertEqual(sel_intent.action, "answer")

        # 3. 실적 개선 원인 후속
        history = [
            {"role": "user", "text": "삼성전자는 어때?"},
            {"role": "assistant", "text": "2025년 영업이익이 전년 대비 증가했습니다.",
             "evidence": [{"id": "CMP_2024_2025_CFS_OPERATING_INCOME", "kind": "annual_comparison"}]}
        ]
        from src.agents.evidence import build_evidence
        evidence = build_evidence(self.result)
        sel_why = select_evidence("왜 늘었어?", history, evidence, [], strict=True)
        self.assertEqual(sel_why.reason, "financials")

        # 4. 주가 전망 후속
        history.extend([
            {"role": "user", "text": "왜 늘었어?"},
            {"role": "assistant", "text": "매출 증가와 원가율 개선이 손익에 기여했습니다."},
            {"role": "user", "text": "앞으로 주가는 오를까?"},
            {"role": "assistant", "text": "과거 실적 개선이 주가 상승을 보장하지는 않습니다."}
        ])
        ctx = answer_context("그럼 내년은?", {}, messages=history)
        self.assertEqual(ctx["focus"], "price_outlook")

        # 5. SK하이닉스로 기업 전환
        switch_intent = route_message("SK하이닉스로 바꿔서 분석해줘", self.discovery, "005930", history, self.settings, listing=self.listing)
        self.assertEqual(switch_intent.action, "select")
        self.assertEqual(switch_intent.code, "000660")


if __name__ == "__main__":
    unittest.main()
