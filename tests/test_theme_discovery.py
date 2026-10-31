"""계획8 실행04 — 테마 발견·관련 기업 탐색 보강 검증.
E01 (테마 발견과 이해) 및 E02 (관련 기업 추가 탐색 및 차이 이해) 전수 검사.
"""
import unittest
from unittest.mock import patch

from src.agents.request import route_message
from src.agents.theme_recommendation import (
    is_theme_ranking_request,
    is_theme_recommendation_request,
    build_theme_recommendation_text,
    RECOMMENDED_THEMES,
)
from src.agents.discovery_context import expansion_request
from src.agents.discovery_answer import requested_business_area, is_discovery_question
from src.config import load_settings
from src.models import (
    CandidateDiscoveryResult,
    CompanyBusinessProfile,
    StockCandidate,
    now_kst,
)


class ThemeDiscoveryTests(unittest.TestCase):
    def setUp(self):
        self.settings = load_settings()
        self.semi_candidates = (
            StockCandidate("삼성전자", "005930", "KOSPI", "005930.KS"),
            StockCandidate("SK하이닉스", "000660", "KOSPI", "000660.KS"),
            StockCandidate("한미반도체", "042700", "KOSPI", "042700.KS"),
        )
        self.semi_discovery = CandidateDiscoveryResult(
            "반도체",
            self.semi_candidates,
            now_kst(),
            business_profiles=(
                CompanyBusinessProfile(
                    "삼성전자", "005930", "통신 및 방송 장비 제조업",
                    "DRAM, NAND Flash, 모바일AP 등", now_kst(), "https://kind.krx.co.kr", ""
                ),
                CompanyBusinessProfile(
                    "SK하이닉스", "000660", "반도체 제조업",
                    "DRAM, NAND Flash, MCP 등", now_kst(), "https://kind.krx.co.kr", ""
                ),
                CompanyBusinessProfile(
                    "한미반도체", "042700", "반도체 제조용 기계 제조업",
                    "반도체 제조용 장비 등", now_kst(), "https://kind.krx.co.kr", ""
                ),
            ),
        )

    def test_e01_i2_unprompted_theme_inquiry_routes_to_recommendation(self):
        """E01-I2: 관심 분야 미정 질문은 임의 순위 없이 근거 기반 테마 소개로 연결된다."""
        queries = [
            "요즘 관심 가질 만한 테마주 알려줘",
            "어떤 테마가 좋아?",
            "관심 가질 만한 테마 추천해줘",
            "요즘 관심 가질 테마 있어?",
            "어떤 테마를 볼까?",
            "테마주 추천해줘",
        ]
        for q in queries:
            with self.subTest(query=q):
                self.assertTrue(is_theme_recommendation_request(q))
                intent = route_message(q, None, None, [], self.settings)
                self.assertEqual(intent.action, "theme_recommendation")
                # 근거 없는 상승 보장이나 특정 종목 매수 추천이 아니라는 점을 명시해야 한다
                self.assertIn("상승 보장이 아니며", intent.reason)
                self.assertNotIn("반드시 오른", intent.reason)
                # 확인 가능한 산업 배경과 관찰 분야가 포함되어야 한다
                self.assertIn("산업 동향", intent.reason)
                self.assertIn("AI 반도체", intent.reason)
                self.assertIn("로봇", intent.reason)
                self.assertIn("2차전지", intent.reason)

    def test_e01_i3_theme_ranking_distinguished_from_recommendation(self):
        """E01-I3: 순위 집계 요청은 추천과 구분되어 지원 한계를 명확히 설명한다."""
        ranking_queries = [
            "테마 순위 알려줘",
            "테마 랭킹 집계해줘",
            "테마별 등락률 순위 보여줘",
            "현재 1위 테마가 뭐야?",
        ]
        for q in ranking_queries:
            with self.subTest(query=q):
                self.assertTrue(is_theme_ranking_request(q))
                self.assertFalse(is_theme_recommendation_request(q))
                intent = route_message(q, None, None, [], self.settings)
                self.assertEqual(intent.action, "unsupported")
                # 시장 전체 순위 미제공 이유를 안내해야 한다
                self.assertIn("순위", intent.reason)

    def test_e01_i1_explicit_theme_not_intercepted_by_recommendation(self):
        """E01-I1: 특정 산업 테마가 명시된 질문은 recommendation이 아니라 discover로 분기한다."""
        explicit_queries = [
            ("반도체 관련 종목 알려줘", "반도체"),
            ("2차전지 테마주 찾아줘", "2차전지"),
            ("로봇 관련주 알려줘", "로봇"),
            ("바이오 테마 알려줘", "바이오"),
        ]
        for q, expected_theme in explicit_queries:
            with self.subTest(query=q):
                self.assertFalse(is_theme_recommendation_request(q))
                intent = route_message(q, None, None, [], self.settings)
                self.assertEqual(intent.action, "discover")
                self.assertEqual(intent.theme, expected_theme)

    def test_e02_i2_expansion_natural_phrasings(self):
        """E02-I2: '더 보여줘', '다른 관련주' 등 다양한 후속 표현이 expand로 연결된다."""
        expansion_queries = [
            "더 보여줘",
            "더 찾아줘",
            "더 알려줘",
            "더 있어?",
            "다른 관련주",
            "다른 관련주는?",
            "다른 종목 더 보여줘",
            "추가로 더 알려줘",
            "관련주 더 보여줘",
        ]
        for q in expansion_queries:
            with self.subTest(query=q):
                self.assertTrue(expansion_request(q))
                intent = route_message(q, self.semi_discovery, None, [], self.settings)
                self.assertEqual(intent.action, "expand")
                self.assertEqual(intent.theme, "반도체")

    def test_e02_i2_business_area_narrowing_in_active_discovery(self):
        """E02-I2: '소재 기업은?', '그중 메모리 직접 제조하는 곳만 골라줘' 등 분야 축소가 discovery_answer로 연결된다."""
        narrowing_queries = [
            ("소재 기업은?", "소재"),
            ("그중 소재 기업은?", "소재"),
            ("장비 회사는?", "장비"),
            ("그중 메모리 직접 제조하는 곳만 골라줘", "메모리"),
        ]
        for q, expected_area in narrowing_queries:
            with self.subTest(query=q):
                area = requested_business_area(q)
                self.assertEqual(area, expected_area)
                self.assertTrue(is_discovery_question(q, self.semi_discovery))
                intent = route_message(q, self.semi_discovery, None, [], self.settings)
                self.assertEqual(intent.action, "discovery_answer")
                self.assertEqual(intent.theme, "반도체")

    def test_regression_new_theme_not_intercepted_as_sub_area(self):
        """새로운 테마 질문('방산 관련주 알려줘')이 기존 테마의 세부 분야로 가로채지지 않는다."""
        intent = route_message("방산 관련주 알려줘", self.semi_discovery, None, [], self.settings)
        self.assertEqual(intent.action, "discover")
        self.assertEqual(intent.theme, "방산")


if __name__ == "__main__":
    unittest.main()
