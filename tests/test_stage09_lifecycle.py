"""Stage 09: 요약, 저장, 종료, 재시작 수명주기 검증 (M01, M02, M03)"""
import unittest
from types import SimpleNamespace
from src.agents.followup import (
    is_restatement,
    is_conversation_summary_request,
    conversation_summary_evidence,
    same_evidence,
)
from src.agents.presentation import parse_presentation
from src.agents.request import (
    route_message,
    is_closing_request,
    is_reset_request,
)
from src.agents.answer_quality import select_evidence
from src.config import load_settings
from src.ui.state import (
    reset_all_state,
    store_candidate_discovery,
    CandidateDiscoveryResult,
)
from src.models import AnalysisResult, FinancialData, PriceHistory, NewsData, StockCandidate
from datetime import datetime


class Stage09LifecycleTests(unittest.TestCase):
    def setUp(self):
        self.settings = load_settings()

    def test_m01_i1_and_i2_classification_distinction(self):
        """M01-I1 & I2: 직전 답변 요약과 전체 대화 정리를 엄밀히 구분한다."""
        restatements = [
            "방금 말한 거 두 줄로 요약해줘",
            "앞서 말한 내용 세 줄로 정리해줘",
            "직전 답변 짧게 요약해줘",
            "두 줄로 요약해줘",
            "핵심만 두 줄로 줄여줘",
        ]
        summaries = [
            "지금까지 정리해줘",
            "지금까지 대화 내용 요약해줘",
            "전체 대화 요약해줘",
            "여태까지 논의한 내용 요약해줘",
            "지금까지 살펴본 내용 종합해줘",
            "지금까지 나온 이야기 정리해줘",
            "대화 요약해줘",
            "대화 내용 요약해줘",
            "대화 내용 정리해줘",
        ]
        for query in restatements:
            self.assertTrue(is_restatement(query), f"Should be restatement: {query}")
            self.assertFalse(is_conversation_summary_request(query), f"Should not be summary: {query}")

        for query in summaries:
            self.assertFalse(is_restatement(query), f"Should not be restatement: {query}")
            self.assertTrue(is_conversation_summary_request(query), f"Should be summary: {query}")

        # Negative directives should NOT be treated as summary
        negatives = [
            "지금까지 내용 정리하지 마",
            "요약하지 말고 자세히 설명해줘",
            "지금까지 나온 이야기 요약하지 말고",
        ]
        for query in negatives:
            self.assertFalse(is_conversation_summary_request(query), f"Negative query should not be summary: {query}")

    def test_m01_i2_presentation_constraints(self):
        """M01-I2: 요청한 문장 수 및 줄 수 제약을 정확히 파싱한다."""
        p_two_lines = parse_presentation("방금 말한 거 두 줄로 요약해줘")
        self.assertEqual(p_two_lines.max_lines, 2)
        self.assertEqual(p_two_lines.max_sentences, 2)

        p_three_lines = parse_presentation("지금까지 대화 내용 세 줄로 정리해줘")
        self.assertEqual(p_three_lines.max_lines, 3)
        self.assertEqual(p_three_lines.max_sentences, 3)

        p_plain_summary = parse_presentation("지금까지 정리해줘")
        self.assertIsNone(p_plain_summary.max_lines)

    def test_m01_v1_multi_company_evidence_preservation(self):
        """M01-V1: 여러 기업이 섞인 대화에서 과거 어시스턴트의 모든 기업 근거가 보존된다."""
        sec_ev = {"id": "FACT_SEC_SALES", "kind": "financial", "stock_code": "005930", "item": "매출액", "value": "300조"}
        hynix_ev = {"id": "FACT_HYNIX_SALES", "kind": "financial", "stock_code": "000660", "item": "매출액", "value": "60조"}

        messages = [
            {"role": "user", "text": "삼성전자 실적 어때?"},
            {"role": "assistant", "text": "2024년 매출 300조원입니다.", "evidence": [sec_ev]},
            {"role": "user", "text": "SK하이닉스는?"},
            {"role": "assistant", "text": "2024년 매출 60조원입니다.", "evidence": [hynix_ev]},
        ]

        # Active evidence only has Hynix
        active_evidence = {"FACT_HYNIX_SALES": hynix_ev}

        collected = conversation_summary_evidence("지금까지 정리해줘", messages, active_evidence)
        self.assertIsNotNone(collected)
        # Both Samsung and Hynix evidence must be in the summary evidence!
        sec_item = next((v for k, v in collected.items() if k.startswith("FACT_SEC_SALES")), None)
        hynix_item = next((v for k, v in collected.items() if k.startswith("FACT_HYNIX_SALES")), None)
        self.assertIsNotNone(sec_item)
        self.assertIsNotNone(hynix_item)
        self.assertEqual(sec_item["stock_code"], "005930")
        self.assertEqual(hynix_item["stock_code"], "000660")

    def test_m02_i1_explicit_save_detection(self):
        """M02-I1: 저장/엑셀 명시 요청만 내보내기로 처리한다."""
        from src.ui.app import _handle_explicit_canvas_or_export_request

        state = {}
        # Normal dialogue turn does NOT create export bytes or demand saving
        _handle_explicit_canvas_or_export_request(state, "삼성전자 PER은 얼마야?", None)
        self.assertNotIn("export_bytes", state)

        # Explicit save request triggers bundle preparation if result exists
        mock_stock = StockCandidate(code="005930", name="삼성전자", market="KOSPI")
        mock_fin = FinancialData(stock=mock_stock, price=70000.0, per=15.0, retrieved_at=datetime(2026, 10, 31))
        mock_price = PriceHistory("005930", "005930.KS", ())
        mock_news = NewsData((), datetime(2026, 10, 31))
        mock_result = AnalysisResult(
            theme="반도체",
            candidates=(mock_stock,),
            financial=mock_fin,
            news=mock_news,
            commentary=None,
            price_history=mock_price,
            result_id="res_1",
        )
        state["dashboard_result"] = mock_result

        _handle_explicit_canvas_or_export_request(state, "이 내용 엑셀로 저장해줘", None)
        canvases = state.get("canvases", [])
        self.assertTrue(len(canvases) > 0)
        self.assertIsNotNone(canvases[0].get("export_bytes"))
        self.assertTrue(canvases[0].get("export_filename").endswith(".xlsx"))

    def test_m03_i1_closing_routing(self):
        """M03-I1: 고마워/여기까지 등의 종료 인사에는 추가 분석을 강요하지 않는 closing 인텐트를 반환한다."""
        closings = [
            "고마워",
            "고마워요!",
            "고맙습니다",
            "감사합니다.",
            "감사해요",
            "수고하셨습니다",
            "수고하셨어요",
            "수고했어",
            "수고 많으셨습니다",
            "여기까지",
            "여기까지요",
            "오늘은 여기까지",
            "오늘은 여기까지 할게",
            "오늘은 여기까지 할게요",
            "고마워 오늘은 여기까지 할게",
            "감사합니다 여기까지 할게요",
            "이만 마칠게요",
            "끝낼게",
            "종료할게",
            "좋은 하루 되세요",
        ]
        for query in closings:
            self.assertTrue(is_closing_request(query), f"Should be closing: {query}")
            intent = route_message(query, None, "005930", [{"role": "assistant", "text": "분석 완료"}], self.settings)
            self.assertEqual(intent.action, "closing", f"Expected closing action for: {query}")

        # Inquiries attached to greetings must NOT be classified as closing
        non_closings = [
            "고마워 그런데 삼성전자 영업이익은?",
            "감사합니다 혹시 SK하이닉스는?",
            "수고하셨어요 다른 종목도 봐주세요",
            "여기까지 주가 흐름 분석해줘",
        ]
        for query in non_closings:
            self.assertFalse(is_closing_request(query), f"Inquiry should not be closing: {query}")

    def test_m03_i2_and_v1_reset_vs_closing(self):
        """M03-I2 & V1: 새 대화는 상태를 초기화하고, 이전 종목의 의도치 않은 재사용을 차단한다."""
        resets = [
            "새 대화",
            "새 대화 시작",
            "새 대화 시작해줘",
            "새 대화 시작할게요",
            "새 대화하자",
            "새 대화해줘",
            "새 채팅",
            "새 채팅 시작",
            "대화 초기화",
            "대화 초기화해줘",
            "대화 초기화할게요",
            "대화 내용 초기화",
            "처음부터 다시",
            "처음부터 다시 시작",
            "처음부터 다시 시작해줘",
            "처음부터 다시 할게",
            "처음부터 다시 할게요",
            "초기화해줘",
            "초기화할게요",
        ]
        for query in resets:
            self.assertTrue(is_reset_request(query), f"Should be reset: {query}")
            intent = route_message(query, None, "005930", [{"role": "assistant", "text": "분석 완료"}], self.settings)
            self.assertEqual(intent.action, "reset", f"Expected reset action for: {query}")

        non_resets = [
            "새 대화에서 삼성전자 볼래",
            "처음부터 다시 삼성전자 영업이익 설명해줘",
        ]
        for query in non_resets:
            self.assertFalse(is_reset_request(query), f"Should not be reset: {query}")

        # Simulate state reset
        state = {}
        mock_stock = StockCandidate("005930", "삼성전자", "KOSPI", True)
        state["selected_code"] = "005930"
        state["candidate_result"] = CandidateDiscoveryResult("반도체", (mock_stock,), datetime(2026, 10, 31))

        # Perform reset_all_state
        reset_all_state(state)
        self.assertIsNone(state.get("selected_code"))
        self.assertNotIn("candidate_result", state)

        # After reset, omitted expression ("이 종목 영업이익은?") must clarify, not reuse Samsung Electronics
        followup_intent = route_message("이 종목 영업이익은?", state.get("candidate_result"), state.get("selected_code"), [], self.settings)
        self.assertEqual(followup_intent.action, "clarify")
        self.assertIn("종목명이나 종목코드를 입력", followup_intent.reason)


if __name__ == "__main__":
    unittest.main()
