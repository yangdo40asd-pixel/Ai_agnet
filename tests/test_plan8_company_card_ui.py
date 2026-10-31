"""기업별 사업 카드 UI 및 출처 연동 테스트 (02-D / CARD-I8~I10)."""
import unittest
from unittest.mock import patch, MagicMock
from streamlit.testing.v1 import AppTest

from src.models import (
    StockCandidate, CandidateDiscoveryResult, CompanyBusinessProfile,
    ChatResponse, CompanyCard, CompanyCardSection, now_kst
)
from src.ui.answer import render_answer, response_fields, source_groups
from src.ui.company_cards import render_company_card, render_company_cards_section


STOCKS = (
    StockCandidate("삼성전자", "005930", "KOSPI", "005930.KS"),
    StockCandidate("SK하이닉스", "000660", "KOSPI", "000660.KS"),
)

EVIDENCE = {
    "BUSINESS_005930": {
        "id": "BUSINESS_005930",
        "kind": "company_profile",
        "stock_code": "005930",
        "stock_name": "삼성전자",
        "text": "삼성전자 · 업종: 통신 및 방송 장비 제조업 · 주요제품: 스마트폰, DRAM",
        "source": "한국거래소 KIND",
        "scope": "company_profile",
        "retrieved_at": "2026-10-30T10:00:00",
    },
    "005930_SEC_1": {
        "id": "005930_SEC_1",
        "kind": "company_business_section",
        "stock_code": "005930",
        "stock_name": "삼성전자",
        "text": "삼성전자 DS부문은 메모리 반도체(DRAM, NAND Flash)를 생산 및 판매하고 있습니다.",
        "source": "OpenDART 정기보고서",
        "scope": "official_business",
        "url": "https://opendart.fss.or.kr/fixture",
        "retrieved_at": "2026-10-30T10:00:00",
    },
    "BUSINESS_000660": {
        "id": "BUSINESS_000660",
        "kind": "company_profile",
        "stock_code": "000660",
        "stock_name": "SK하이닉스",
        "text": "SK하이닉스 · 업종: 반도체 제조업 · 주요제품: DRAM, NAND Flash, MCP",
        "source": "한국거래소 KIND",
        "scope": "company_profile",
        "retrieved_at": "2026-10-30T10:00:00",
    },
}


def _card_fixture():
    import streamlit as st
    from src.ui.answer import render_answer

    message = st.session_state["fixture_message"]
    render_answer(message, key_prefix="test_prefix")


class CompanyCardUiTests(unittest.TestCase):
    def test_render_company_cards_layout_and_sections(self):
        message = {
            "intro": "반도체 테마 관련 후보 기업입니다.",
            "evidence": list(EVIDENCE.values()),
            "company_cards": [
                {
                    "stock_code": "005930",
                    "stock_name": "삼성전자",
                    "sections": [
                        {"role": "summary", "text": "메모리 반도체 종합 제조사입니다.", "evidence_ids": ["BUSINESS_005930"]},
                        {"role": "business", "text": "DRAM 및 NAND 제품을 생산합니다.", "evidence_ids": ["005930_SEC_1"]},
                    ],
                },
                {
                    "stock_code": "000660",
                    "stock_name": "SK하이닉스",
                    "sections": [
                        {"role": "summary", "text": "메모리 반도체를 공급하는 기업입니다.", "evidence_ids": ["BUSINESS_000660"]},
                    ],
                },
            ],
        }
        app = AppTest.from_function(_card_fixture)
        app.session_state["fixture_message"] = message
        app.run()
        self.assertEqual(len(app.exception), 0)

        # 1. 기업명 헤더와 종목 코드 렌더링 확인
        markdown_texts = [m.value for m in app.markdown]
        self.assertTrue(any("### 삼성전자" in t for t in markdown_texts))
        self.assertTrue(any("### SK하이닉스" in t for t in markdown_texts))

        # 2. 각 카드 섹션 본문 렌더링 확인
        self.assertTrue(any("메모리 반도체 종합 제조사입니다." in t for t in markdown_texts))
        self.assertTrue(any("DRAM 및 NAND 제품을 생산합니다." in t for t in markdown_texts))
        self.assertTrue(any("메모리 반도체를 공급하는 기업입니다." in t for t in markdown_texts))

        # 3. 실적 보기 버튼 렌더링 확인
        button_labels = [b.label for b in app.button]
        self.assertIn("삼성전자 실적 보기", button_labels)
        self.assertIn("SK하이닉스 실적 보기", button_labels)

    def test_action_button_triggers_candidate_selection(self):
        message = {
            "intro": "후보 소개입니다.",
            "evidence": list(EVIDENCE.values()),
            "company_cards": [
                {
                    "stock_code": "005930",
                    "stock_name": "삼성전자",
                    "sections": [{"role": "summary", "text": "설명", "evidence_ids": ["BUSINESS_005930"]}],
                }
            ],
        }
        app = AppTest.from_function(_card_fixture)
        app.session_state["fixture_message"] = message
        app.run()

        # 최초에는 selected_code가 없음
        self.assertNotIn("selected_code", app.session_state)

        # '삼성전자 실적 보기' 버튼 클릭
        analyze_btn = next(b for b in app.button if "실적 보기" in b.label)
        analyze_btn.click().run()

        # 클릭 후 selected_code 가 '005930'으로 설정되고 request_status 가 'pending'으로 전이됨
        self.assertEqual(app.session_state["selected_code"], "005930")
        self.assertEqual(app.session_state["request_status"], "pending")

        # 재실행 후 버튼 라벨이 '실적 확인됨'으로 변경되고 비활성화됨
        updated_btn = next(b for b in app.button if "실적" in b.label)
        self.assertIn("확인됨", updated_btn.label)
        self.assertTrue(updated_btn.disabled)

    def test_source_popover_contains_exact_card_evidence(self):
        message = {
            "intro": "후보 소개입니다.",
            "evidence": list(EVIDENCE.values()),
            "company_cards": [
                {
                    "stock_code": "005930",
                    "stock_name": "삼성전자",
                    "sections": [
                        {"role": "summary", "text": "요약", "evidence_ids": ["BUSINESS_005930"]},
                        {"role": "business", "text": "원문", "evidence_ids": ["005930_SEC_1"]},
                    ],
                }
            ],
        }
        app = AppTest.from_function(_card_fixture)
        app.session_state["fixture_message"] = message
        app.run()
        self.assertEqual(len(app.exception), 0)

        markdown_texts = [m.value for m in app.markdown]
        # 팝오버 내부의 근거 소유자 대조: 삼성전자 출처 정보 렌더링 확인
        self.assertTrue(any("삼성전자 관련 출처" in t for t in markdown_texts))
        self.assertTrue(any("한국거래소 KIND" in t for t in markdown_texts))
        self.assertTrue(any("OpenDART 정기보고서" in t for t in markdown_texts))

        # 링크 버튼 생성 확인 (원문 URL이 있는 경우)
        link_buttons = app.get("link_button")
        self.assertTrue(any(btn.proto.url == "https://opendart.fss.or.kr/fixture" for btn in link_buttons))

    def test_redundant_candidate_buttons_omitted_when_company_cards_present(self):
        from src.ui.app import render_conversation
        discovery = CandidateDiscoveryResult("반도체", STOCKS, now_kst())

        def _conversation_fixture():
            import streamlit as st
            from src.ui.app import render_conversation
            render_conversation()

        # 메시지에 company_cards 가 포함된 경우
        card_msg = {
            "role": "assistant",
            "text": "카드 답변",
            "intro": "카드 도입",
            "discovery": discovery,
            "evidence": list(EVIDENCE.values()),
            "company_cards": [
                {
                    "stock_code": "005930",
                    "stock_name": "삼성전자",
                    "sections": [{"role": "summary", "text": "요약", "evidence_ids": ["BUSINESS_005930"]}],
                }
            ],
        }
        app = AppTest.from_function(_conversation_fixture)
        app.session_state["chat_messages"] = [card_msg]
        app.session_state["candidate_result"] = discovery
        app.run()
        self.assertEqual(len(app.exception), 0)

        # 카드가 있으므로 별도의 하단 후보 선택 버튼(render_related_candidate_buttons)은 렌더링되지 않음
        button_labels = [b.label for b in app.button]
        self.assertNotIn("삼성전자 (005930) 선택", button_labels)
        self.assertIn("삼성전자 실적 보기", button_labels)
        # 후보 상세 정보 expander는 전체 세부 표로서 분리 보존됨
        expander_labels = [e.label for e in app.expander]
        self.assertIn("후보 상세 정보", expander_labels)

    def test_legacy_or_plain_message_retains_fallback_buttons(self):
        from src.ui.app import render_conversation
        discovery = CandidateDiscoveryResult("반도체", STOCKS, now_kst())

        def _conversation_fixture():
            import streamlit as st
            from src.ui.app import render_conversation
            render_conversation()

        # 구형 또는 plain 메시지(company_cards 부재)인 경우
        plain_msg = {
            "role": "assistant",
            "text": "일반 텍스트 답변입니다.",
            "discovery": discovery,
            "evidence": list(EVIDENCE.values()),
        }
        app = AppTest.from_function(_conversation_fixture)
        app.session_state["chat_messages"] = [plain_msg]
        app.session_state["candidate_result"] = discovery
        app.run()
        self.assertEqual(len(app.exception), 0)

        # 카드가 없으므로 하단에 후보 선택 버튼 및 후보 상세 정보 expander가 정상 표시됨
        expander_labels = [e.label for e in app.expander]
        self.assertIn("후보 상세 정보", expander_labels)
        button_labels = [b.label for b in app.button]
        self.assertTrue(any("삼성전자 (005930) 선택" in b for b in button_labels))


if __name__ == "__main__":
    unittest.main()
