import unittest
from decimal import Decimal
from datetime import datetime

from src.models import (
    StockCandidate, FinancialData, AnalysisResult, NewsData,
    now_kst, ChatResponse, AppError
)
from src.config import load_settings
from src.agents.chat import answer_question
from src.agents.knowledge import TERMS, concept_answer
from src.agents.question_goal import question_goal
from src.agents.presentation import parse_presentation
from src.agents.report import _comment_text
from src.agents.company_overview import comparison_fallback
from src.ui.answer import clean_display_lead


def _get_text(res):
    return res.text if hasattr(res, "text") else res[0]


def _get_evidence(res):
    return res.evidence if hasattr(res, "evidence") else res[1]


class Stage05AnswerQualityTests(unittest.TestCase):
    def setUp(self):
        self.settings = load_settings()
        self.stock = StockCandidate(name="삼성전자", code="005930", ticker="005930.KS")
        self.fin = FinancialData(self.stock, 70000.0, 15.2, now_kst(), per_period_end="2024-12-31")
        self.res = AnalysisResult("반도체", (self.stock,), self.fin, NewsData((), now_kst(), "empty", ""), None)

    def test_a01_direct_metric_per_query(self):
        """A01-I2: 직접 지표 질문은 값과 기준을 우선 답하고 기업 개요나 전체 표를 나열하지 않는다."""
        ans = answer_question("삼성전자 PER 얼마야?", self.res, [], self.settings)
        text = _get_text(ans)
        evidence = _get_evidence(ans)
        self.assertIn("15.20배", text)
        self.assertIn("PER", text)
        self.assertNotIn("관련 뉴스와 테마 동향", text)
        self.assertTrue(any(e.get("id") == "PER" for e in evidence))

    def test_a01_direct_metric_uncollected_dividend_and_market_cap(self):
        """A01-I2 / S02-I3: 미수집 지표 질문은 환각이나 덤프 없이 기본 수집 범위와 지표 상태를 직결 설명한다."""
        ans_div = answer_question("삼성전자 배당수익률 얼마야?", self.res, [], self.settings)
        text_div = _get_text(ans_div)
        self.assertIn("배당수익률(배당금)", text_div)
        self.assertIn("포함되어 있지 않습니다", text_div)
        self.assertIn("주가, PER, PBR, ROE, EPS, BPS", text_div)

        ans_cap = answer_question("삼성전자 시가총액 얼마야?", self.res, [], self.settings)
        text_cap = _get_text(ans_cap)
        self.assertIn("시가총액", text_cap)
        self.assertIn("포함되어 있지 않습니다", text_cap)

    def test_a01_concept_question_korean_metrics(self):
        """A01-I2: 배당수익률 및 시가총액 개념 질문에 올바른 정의와 산식을 제공한다."""
        ans_div = concept_answer(["배당수익률"])
        self.assertIn("**배당수익률**은", ans_div)
        self.assertIn("1주당 배당금 ÷ 현재 주가 × 100", ans_div)

        ans_cap = concept_answer(["시가총액"])
        self.assertIn("**시가총액**은", ans_cap)
        self.assertIn("발행주식수 × 현재 주가", ans_cap)

    def test_a01_v1_overview_nuanced_situations(self):
        """A01-I1 / A01-V1: 개선·악화·혼재·적자전환 상황에서 각 근거에 맞는 차별화된 결론을 제시한다."""
        base_evidence = {
            "kind": "annual_comparison",
            "status": "ok",
            "years": [2024, 2025],
            "fs_div": "CFS",
            "stock_code": "005930"
        }
        # 1. 개선 (매출 증가 + 영업이익 증가)
        ev_improved = {
            "CMP_REV": {**base_evidence, "item": "revenue", "previous": "2000000000000", "current": "2500000000000", "text": "매출: 2조 → 2.5조"},
            "CMP_OP": {**base_evidence, "item": "operating_income", "previous": "100000000000", "current": "150000000000", "text": "영업이익: 1000억 → 1500억"},
            "CMP_MARGIN": {**base_evidence, "item": "operating_margin", "text": "영업이익률: 5% → 6%"}
        }
        lead_improved, _ = comparison_fallback(ev_improved)
        self.assertIn("매출과 영업이익이 모두 증가", lead_improved)

        # 2. 혼재 (매출 증가 + 영업이익 감소)
        ev_mixed = {
            "CMP_REV": {**base_evidence, "item": "revenue", "previous": "2000000000000", "current": "2500000000000", "text": "매출: 2조 → 2.5조"},
            "CMP_OP": {**base_evidence, "item": "operating_income", "previous": "150000000000", "current": "100000000000", "text": "영업이익: 1500억 → 1000억"},
            "CMP_MARGIN": {**base_evidence, "item": "operating_margin", "text": "영업이익률: 7.5% → 4%"}
        }
        lead_mixed, _ = comparison_fallback(ev_mixed)
        self.assertIn("매출은 늘었으나 영업이익이 줄어", lead_mixed)

        # 3. 적자 전환
        ev_turnaround_loss = {
            "CMP_REV": {**base_evidence, "item": "revenue", "previous": "2000000000000", "current": "1800000000000", "text": "매출: 2조 → 1.8조"},
            "CMP_OP": {**base_evidence, "item": "operating_income", "previous": "100000000000", "current": "-50000000000", "text": "영업이익: 1000억 → -500억 (적자 전환)"},
            "CMP_MARGIN": {**base_evidence, "item": "operating_margin", "text": "영업이익률: 5% → -2.7%"}
        }
        lead_loss, _ = comparison_fallback(ev_turnaround_loss)
        self.assertIn("적자로 전환", lead_loss)

    def test_a04_i4_presentation_depth_parsing(self):
        """A04-I4: '쉽게' / '자세히' 등 사용자 표현 요청을 깊이 계약에 바인딩한다."""
        p_simple = parse_presentation("초보자도 알기 쉽게 설명해줘")
        self.assertEqual(p_simple.depth, "simple")
        self.assertTrue(any("쉬운 한국어" in inst for inst in p_simple.instructions()))

        p_detailed = parse_presentation("재무 상황을 자세히 분석해줘")
        self.assertEqual(p_detailed.depth, "detailed")
        self.assertTrue(any("깊이 있고 상세하게" in inst for inst in p_detailed.instructions()))

        p_lines = parse_presentation("세 줄로 요약해줘")
        self.assertEqual(p_lines.max_lines, 3)
        self.assertEqual(p_lines.style, "plain")

    def test_a03_i4_news_plan_empty_rejection_and_hyphen_cleaning(self):
        """A03-I4: 내용 없는 '계획이 보도되었습니다' 문장을 거절하고 앞뒤 의미 없는 하이픈을 정돈한다."""
        with self.assertRaises(AppError):
            _comment_text("계획이 보도되었습니다.")

        with self.assertRaises(AppError):
            _comment_text("이 종목은 계획이 보도되었습니다.")

        cleaned = _comment_text("- 삼성전자는 신규 라인 증설 계획을 발표했습니다.")
        self.assertFalse(cleaned.startswith("-"))
        self.assertIn("삼성전자는 신규 라인 증설 계획을 발표했습니다.", cleaned)

    def test_s02_i4_placeholder_leak_cleanup(self):
        """S02-I4: 자리표시자나 내부 Fact ID가 화면 선두 본문에 누출되지 않도록 정돈한다."""
        raw = "{{PER}}와 {{PRICE}} 수치 확인 결과입니다.\n\n주요 소식입니다."
        cleaned = clean_display_lead(raw)
        self.assertNotIn("{{PER}}", cleaned)
        self.assertNotIn("{{PRICE}}", cleaned)

    def test_s02_i1_echoed_metric_value_is_normalized_only_when_equal(self):
        """S02-I1: 'PER {{PER}}은 15.20배' 중복은 같은 확인값일 때만 정리하고, 다른 값·다른 지표는 그대로 둬 검증이 거절하게 한다."""
        from src.agents.presentation import normalize_metric_subject
        ev = {"PER": {"value_text": "15.20배"}, "PBR": {"value_text": "1.10배"}}
        self.assertEqual(normalize_metric_subject("삼성전자의 현재 PER {{PER}}은 15.20배입니다.", ev),
                         "삼성전자의 현재 PER은 15.20배입니다.")
        # 본문 값이 확인값과 다르면 정리하지 않는다(오답을 숨기지 않음).
        wrong = "현재 PER {{PER}}은 99.00배입니다."
        self.assertEqual(normalize_metric_subject(wrong, ev), wrong)
        # 다른 지표의 값이면 정리하지 않는다.
        cross = "현재 PBR {{PBR}}은 15.20배입니다."
        self.assertEqual(normalize_metric_subject(cross, ev), cross)
        # 정상 형태는 변하지 않는다.
        ok = "PER은 {{PER}}입니다."
        self.assertEqual(normalize_metric_subject(ok, ev), ok)

    def test_s02_i4_fallback_never_shows_internal_status_as_headline_and_leads_judgment(self):
        """S02-I4/A04-V1: 제한 응답에 NEWS_STATUS 내부 문구('ok')를 뉴스 제목으로 노출하지 않고, 판단 질문은 단정 불가 문장으로 시작한다."""
        from src.agents.chat import _verified_fallback
        evidence = {
            "PRICE": {"text": "삼성전자 · PRICE: 70,000.00원", "value_text": "70,000.00원", "status": "ok"},
            "PER": {"text": "삼성전자 · PER: 15.20배", "value_text": "15.20배", "status": "ok"},
            "NEWS_STATUS": {"text": "ok", "status": "ok"},
        }
        request = {"verified_sentence_examples": [], "issue_groups": [], "answer_style": "plain"}
        text, items, _ = _verified_fallback("PER이 낮으니 사도 돼?", evidence, request)
        self.assertNotIn("1. ok", text)
        self.assertNotIn("보도 제목", text)
        self.assertTrue(text.startswith("이 질문은 아래 확인된 수치만으로"))
        self.assertIn("PER 15.20배", text)
        self.assertNotIn("NEWS_STATUS", [i["id"] for i in items])
        # 뉴스 질문의 제한 응답에도 상태 문구는 제목이 되지 않는다.
        news = _verified_fallback("최근 뉴스 알려줘", evidence, request)
        self.assertIsNone(news)

    def test_habitual_caveat_stripping_on_judgment_sentences(self):
        """A01-V1/S02-I4: '추가 자료 확인이 필요합니다' 같은 습관적 면책 문장을 정리하고 핵심 실적 문장만 유지한다."""
        from src.agents.chat import strip_habitual_caveats
        lead = "삼성전자는 2025년 영업이익이 100억원으로 증가했습니다."
        
        # 1. 제보된 반도체 수요/생산계획 추가 자료 확인 문구
        s1 = f"{lead} 앞으로의 판단을 위해서는 향후 반도체 수요 전망이나 회사의 구체적인 생산 계획 등 실적 지속성을 뒷받침할 추가 자료 확인이 필요합니다."
        self.assertEqual(strip_habitual_caveats(s1), lead)

        # 2. 연도가 포함된 전망 추가 확인 문구
        s2 = f"{lead} 2026년 실적 지속성을 뒷받침할 추가 자료 확인이 필요합니다."
        self.assertEqual(strip_habitual_caveats(s2), lead)

        # 3. 추가적인 자료의 확인이 필요
        s3 = f"{lead} 실적 개선 흐름을 판단하기 위해서는 추가적인 자료의 확인이 필요합니다."
        self.assertEqual(strip_habitual_caveats(s3), lead)

        # 4. 쉼표 절 연결 형태 면책 문구 정돈 및 종결어미 정상화
        s4 = "2025년 영업이익은 100억원으로 증가했으나, 개별 투자 성향을 고려하시기 바랍니다."
        self.assertEqual(strip_habitual_caveats(s4), "2025년 영업이익은 100억원으로 증가했습니다.")


if __name__ == "__main__":
    unittest.main()
