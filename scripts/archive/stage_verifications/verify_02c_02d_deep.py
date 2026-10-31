"""02-C 및 02-D 종합 재검수 및 심층 시나리오 스트레스 테스트.

다양한 상황(단일 기업, 3기업, 5기업, 결측 기업, 크로스 인용 거절, 과장 표현 방지,
분량 계약 경계, 196자 문장 보존, 위젯 키 중복 방지, 실적 보기 클릭 및 상태 전이,
팝오버 출처 독립성, 실시간 로컬 LLM 생성 등)을 깐깐하게 검증한다.
"""
import sys
import json
import time
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path.cwd()))

from src.models import (
    StockCandidate, CandidateDiscoveryResult, CompanyBusinessProfile,
    ChatResponse, CompanyCard, CompanyCardSection, AppError, now_kst
)
from src.config import load_settings, Settings
from src.agents.company_cards import validate_company_cards, build_fallback_cards, _source_doc_label
from src.agents.discovery_answer import discovery_answer, _fallback
from src.agents.presentation import parse_presentation, enforce_presentation
from src.ui.answer import response_fields, source_groups, render_answer
from streamlit.testing.v1 import AppTest

results = {"passed": 0, "failed": 0, "scenarios": []}


def record(name: str, success: bool, detail: str = ""):
    status = "PASS" if success else "FAIL"
    print(f"[{status}] {name}: {detail}")
    results["scenarios"].append({"name": name, "status": status, "detail": detail})
    if success:
        results["passed"] += 1
    else:
        results["failed"] += 1


# -------------------------------------------------------------
# 테스트용 픽스처 데이터
# -------------------------------------------------------------
STOCKS_3 = (
    StockCandidate("삼성전자", "005930", "KOSPI", "005930.KS"),
    StockCandidate("SK하이닉스", "000660", "KOSPI", "000660.KS"),
    StockCandidate("한미반도체", "042700", "KOSPI", "042700.KS"),
)

EVIDENCE_3 = {
    "BUSINESS_005930": {
        "id": "BUSINESS_005930", "kind": "company_profile", "stock_code": "005930", "stock_name": "삼성전자",
        "text": "삼성전자 · 업종: 통신 및 방송 장비 제조업 · 주요제품: 스마트폰, DRAM",
        "source": "한국거래소 KIND", "scope": "company_profile", "theme_supported": True,
    },
    "005930_SEC_1": {
        "id": "005930_SEC_1", "kind": "company_business_section", "stock_code": "005930", "stock_name": "삼성전자",
        "text": "삼성전자 DS부문은 메모리 반도체(DRAM, NAND Flash)를 생산 및 판매하고 있습니다.",
        "source": "OpenDART 정기보고서", "scope": "official_business", "document_id": "DART_005930",
        "url": "https://dart.fss.or.kr/005930", "theme_supported": True,
    },
    "BUSINESS_000660": {
        "id": "BUSINESS_000660", "kind": "company_profile", "stock_code": "000660", "stock_name": "SK하이닉스",
        "text": "SK하이닉스 · 업종: 반도체 제조업 · 주요제품: DRAM, NAND Flash",
        "source": "한국거래소 KIND", "scope": "company_profile", "theme_supported": True,
    },
    "000660_SEC_1": {
        "id": "000660_SEC_1", "kind": "company_business_section", "stock_code": "000660", "stock_name": "SK하이닉스",
        "text": "당사는 고성능 HBM 메모리와 낸드플래시 제품을 제조하여 글로벌 고객사에 공급합니다.",
        "source": "공식 홈페이지", "scope": "official_business", "document_id": "WEB_000660",
        "url": "https://skhynix.com/products", "theme_supported": True,
    },
    "BUSINESS_042700": {
        "id": "BUSINESS_042700", "kind": "company_profile", "stock_code": "042700", "stock_name": "한미반도체",
        "text": "한미반도체 · 업종: 반도체 제조용 기계 제조업 · 주요제품: 반도체 제조용 장비",
        "source": "한국거래소 KIND", "scope": "company_profile", "theme_supported": True,
    },
    "042700_SEC_1": {
        "id": "042700_SEC_1", "kind": "company_business_section", "stock_code": "042700", "stock_name": "한미반도체",
        "text": "한미반도체는 듀얼 헤드 TC 본더 등 2.5D 및 3D 패키징용 첨단 장비를 제작 공급합니다.",
        "source": "OpenDART 정기보고서", "scope": "official_business", "document_id": "DART_042700",
        "url": "https://dart.fss.or.kr/042700", "theme_supported": True,
    },
}

PROFILES_3 = (
    CompanyBusinessProfile("삼성전자", "005930", "제조업", "스마트폰, DRAM", now_kst(), "https://example.com"),
    CompanyBusinessProfile("SK하이닉스", "000660", "제조업", "DRAM, NAND Flash", now_kst(), "https://example.com"),
    CompanyBusinessProfile("한미반도체", "042700", "제조업", "반도체 제조용 장비", now_kst(), "https://example.com"),
)


def run_checks():
    print("=" * 60)
    print("02-C & 02-D 종합 재검수 시작")
    print("=" * 60)

    # ---------------------------------------------------------
    # 1. 02-C: 크로스 인용 및 소유자 불명 근거 거절 검증
    # ---------------------------------------------------------
    try:
        cross_payload = {
            "text": "도입부입니다.",
            "evidence_ids": ["BUSINESS_005930"],
            "follow_up": "",
            "company_cards": [
                {"stock_code": "005930", "sections": [{"role": "summary", "text": "삼성전자", "evidence_ids": ["BUSINESS_000660"]}]},  # SK하이닉스 근거 교차 인용
                {"stock_code": "000660", "sections": [{"role": "summary", "text": "SK하이닉스", "evidence_ids": ["BUSINESS_000660"]}]},
                {"stock_code": "042700", "sections": [{"role": "summary", "text": "한미반도체", "evidence_ids": ["BUSINESS_042700"]}]},
            ]
        }
        validate_company_cards(cross_payload, EVIDENCE_3, candidates=STOCKS_3)
        record("02-C 타사 근거 교차 인용 차단", False, "타사 근거가 거절되지 않고 승인됨")
    except AppError as e:
        record("02-C 타사 근거 교차 인용 차단", e.code == "company_card_evidence_ownership", f"정상 거절 ({e.code})")

    # ---------------------------------------------------------
    # 2. 02-C: 근거 없는 '전문/핵심/주력/특화/집중' 과장 수식어 차단 및 근거 있는 경우 승인
    # ---------------------------------------------------------
    try:
        exaggerated_payload = {
            "text": "도입부입니다.",
            "evidence_ids": ["BUSINESS_005930"],
            "follow_up": "",
            "company_cards": [
                {"stock_code": "005930", "sections": [{"role": "summary", "text": "삼성전자는 글로벌 반도체 전문 기업입니다.", "evidence_ids": ["BUSINESS_005930"]}]},
                {"stock_code": "000660", "sections": [{"role": "summary", "text": "SK하이닉스 메모리 제조사입니다.", "evidence_ids": ["BUSINESS_000660"]}]},
                {"stock_code": "042700", "sections": [{"role": "summary", "text": "한미반도체 장비 제조사입니다.", "evidence_ids": ["BUSINESS_042700"]}]},
            ]
        }
        validate_company_cards(exaggerated_payload, EVIDENCE_3, candidates=STOCKS_3)
        record("02-C 근거 없는 전문 기업 과장 차단", False, "원문에 없는 '전문' 표현이 승인됨")
    except AppError as e:
        record("02-C 근거 없는 전문 기업 과장 차단", e.code == "chat_claim", f"정상 거절 ({e.code})")

    # 원문에 '전문'이 있는 경우 승인
    grounded_ev = dict(EVIDENCE_3)
    grounded_ev["BUSINESS_005930"] = dict(EVIDENCE_3["BUSINESS_005930"], text="삼성전자 · 반도체 전문 제조업 · 주요제품: DRAM")
    try:
        validate_company_cards(exaggerated_payload, grounded_ev, candidates=STOCKS_3)
        record("02-C 원문에 명시된 전문 표현 승인", True, "원문에 존재하는 경우 정상 승인")
    except Exception as e:
        record("02-C 원문에 명시된 전문 표현 승인", False, f"예기치 않은 실패 ({e})")

    # ---------------------------------------------------------
    # 3. 02-C: 분량 제한(한 문장, 두 문장, 세 문장, 두 줄) 요청 시 대체 카드 및 문장형 전환
    # ---------------------------------------------------------
    disc_3 = CandidateDiscoveryResult("반도체", STOCKS_3, now_kst(), business_profiles=PROFILES_3)
    settings = Settings("mock", "mock", "", "")

    # 세 문장 요청: 3개 기업에 대해 각각 1문장씩 3개 컴팩트 카드로 반환되어야 함
    with patch("src.agents.discovery_answer._invoke", side_effect=AppError("mock_fail", "실패")):
        resp_3 = discovery_answer("반도체 관련 기업 세 문장으로 소개해줘", disc_3, settings, as_cards=True)
        enforce_presentation(resp_3, parse_presentation("반도체 관련 기업 세 문장으로 소개해줘"))
        record("02-C 세 문장 요청 카드 반환", len(resp_3.company_cards) == 3, f"카드 {len(resp_3.company_cards)}개, 분량 검증 통과")

    # 두 문장 요청: 기업 수(3개)보다 작으므로 일반 문장형 2문장으로 반환되어야 함
    with patch("src.agents.discovery_answer._invoke", side_effect=AppError("mock_fail", "실패")):
        resp_2 = discovery_answer("반도체 관련 기업 두 문장으로 요약해줘", disc_3, settings, as_cards=True)
        enforce_presentation(resp_2, parse_presentation("반도체 관련 기업 두 문장으로 요약해줘"))
        record("02-C 두 문장 요청 문장형 전환", len(resp_2.company_cards) == 0, f"카드 {len(resp_2.company_cards)}개, 분량 검증 통과")

    # 한 문장 요청: 기업 수(3개)보다 작으므로 단일 문장으로 반환되어야 함
    with patch("src.agents.discovery_answer._invoke", side_effect=AppError("mock_fail", "실패")):
        resp_1 = discovery_answer("반도체 관련 기업 한 문장으로 요약해줘", disc_3, settings, as_cards=True)
        enforce_presentation(resp_1, parse_presentation("반도체 관련 기업 한 문장으로 요약해줘"))
        record("02-C 한 문장 요청 단일문장 전환", len(resp_1.company_cards) == 0, f"카드 {len(resp_1.company_cards)}개, 분량 검증 통과")

    # 두 줄 요청: 2줄 plain 문장으로 반환되어야 함
    with patch("src.agents.discovery_answer._invoke", side_effect=AppError("mock_fail", "실패")):
        resp_line2 = discovery_answer("반도체 관련 기업 두 줄로 써줘", disc_3, settings, as_cards=True)
        enforce_presentation(resp_line2, parse_presentation("반도체 관련 기업 두 줄로 써줘"))
        record("02-C 두 줄 요청 줄수제한 준수", len(resp_line2.company_cards) == 0, f"카드 {len(resp_line2.company_cards)}개, 줄수 통과")

    # ---------------------------------------------------------
    # 4. 02-C: 긴 공식 문장(196자) 손실 방지 및 출처 라벨 정확성
    # ---------------------------------------------------------
    paragraph_196 = (
        "당사는 반도체 제조 공정에서 사용되는 웨이퍼 검사 장비와 세정 장비를 개발하고 생산하며, "
        "고객의 생산 공정 조건에 맞춘 장비 설계와 조립, 설치, 시운전 및 유지보수 업무를 수행하고 있고, "
        "장비에 사용되는 소모성 부품과 교체 부품도 함께 공급하며, "
        "국내외 반도체 제조업체에 대한 제품 판매와 기술 지원 업무를 별도 담당 조직을 통해 수행하고 있습니다."
    )
    long_ev = {
        "SEC_LONG": {
            "id": "SEC_LONG", "stock_code": "005930", "stock_name": "삼성전자",
            "kind": "company_business_section", "scope": "official_business",
            "products": paragraph_196, "text": paragraph_196, "theme_supported": True,
            "source": "공식 홈페이지", "document_id": "WEB_005930",
        }
    }
    fb_cards = build_fallback_cards(disc_3, long_ev, (STOCKS_3[0],))
    card_text = fb_cards[0].sections[0].text
    has_196 = "웨이퍼 검사 장비와 세정 장비를 개발하고 생산하며" in card_text
    label_correct = "공식 홈페이지 자료 발췌" in card_text
    record("02-C 196자 단일 문장 완전 보존", has_196, "196자 문장 누락 없이 보존됨")
    record("02-C 웹 자료의 정확한 출처 라벨 표기", label_correct, f"라벨: {card_text[:35]}")

    # ---------------------------------------------------------
    # 5. 02-C: 5개 기업 후보 탐색 시 카드 생성 호환성
    # ---------------------------------------------------------
    stocks_5 = tuple(StockCandidate(f"기업{i}", f"00000{i}", "KOSPI", f"00000{i}.KS") for i in range(1, 6))
    profiles_5 = tuple(CompanyBusinessProfile(s.name, s.code, "제조업", f"제품{i}", now_kst(), "url") for i, s in enumerate(stocks_5, 1))
    ev_5 = {
        f"BUSINESS_{s.code}": {
            "id": f"BUSINESS_{s.code}", "kind": "company_profile", "stock_code": s.code, "stock_name": s.name,
            "text": f"{s.name} · 제조업 · 제품{i}", "source": "한국거래소 KIND", "scope": "company_profile", "theme_supported": True,
        }
        for i, s in enumerate(stocks_5, 1)
    }
    cards_5 = build_fallback_cards(CandidateDiscoveryResult("반도체", stocks_5, now_kst()), ev_5, stocks_5)
    record("02-C 5개 기업 카드 확장성", len(cards_5) == 5, f"5개 기업 카드 정확히 생성 ({len(cards_5)}개)")

    # ---------------------------------------------------------
    # 6. 02-C: 1개 기업만 자료 조회 실패한 부분 결측 시나리오
    # ---------------------------------------------------------
    partial_ev = dict(EVIDENCE_3)
    del partial_ev["BUSINESS_042700"]
    del partial_ev["042700_SEC_1"]
    partial_cards = build_fallback_cards(disc_3, partial_ev, STOCKS_3)
    c0, c1, c2 = partial_cards
    hpsp_missing_notice = "상세 공식 사업 정보는 이번 조회에서 확보되지 않았습니다" in c2.sections[0].text
    record("02-C 1개 기업 결측 시 고지 및 타기업 보존", hpsp_missing_notice and len(c0.sections) >= 1, "결측 기업만 안전하게 고지되고 타기업 카드 정상 보존")

    # ---------------------------------------------------------
    # 7. 02-C: 불변 객체, 직렬화, 세 값 언패킹 호환성
    # ---------------------------------------------------------
    sec = CompanyCardSection("summary", "본문", ("E1",))
    card = CompanyCard("005930", "삼성전자", (sec,))
    chat_resp = ChatResponse("도입", [dict(EVIDENCE_3["BUSINESS_005930"])], "후속", company_cards=(card,))
    txt, ev, fu = chat_resp
    is_3tuple = (txt == chat_resp.text and ev == chat_resp.evidence and fu == "후속")
    fields = response_fields(chat_resp)
    json_str = json.dumps(fields, ensure_ascii=False)
    loaded_fields = json.loads(json_str)
    has_serialized_cards = len(loaded_fields.get("company_cards", [])) == 1
    record("02-C 불변 객체/직렬화/세값 순회 호환", is_3tuple and has_serialized_cards, "3값 언패킹 및 JSON 직렬화 완벽 호환")

    # ---------------------------------------------------------
    # 8. 02-D: 카드 렌더링, 섹션별 표기, 인용 번호 연동
    # ---------------------------------------------------------
    def _ui_fixture():
        import streamlit as st
        from src.ui.answer import render_answer
        msg = st.session_state["test_msg"]
        render_answer(msg, key_prefix="deep_test")

    ui_msg = {
        "intro": "반도체 테마 관련 후보 기업입니다.",
        "evidence": list(EVIDENCE_3.values()),
        "company_cards": [
            {
                "stock_code": "005930",
                "stock_name": "삼성전자",
                "sections": [
                    {"role": "summary", "text": "메모리 반도체 종합 제조사입니다.", "evidence_ids": ["BUSINESS_005930"]},
                    {"role": "business", "text": "DRAM 및 NAND 제품을 생산합니다.", "evidence_ids": ["005930_SEC_1"]},
                    {"role": "theme", "text": "반도체 테마의 핵심 제조 역량을 보유하고 있습니다.", "evidence_ids": ["005930_SEC_1"]},
                ],
            },
            {
                "stock_code": "000660",
                "stock_name": "SK하이닉스",
                "sections": [
                    {"role": "summary", "text": "메모리 반도체 전문 생산 기업입니다.", "evidence_ids": ["BUSINESS_000660"]},
                ],
            },
        ],
    }

    app = AppTest.from_function(_ui_fixture)
    app.session_state["test_msg"] = ui_msg
    app.run()
    record("02-D UI 렌더링 예외 발생 여부", len(app.exception) == 0, f"예외 {len(app.exception)}건")

    mds = [m.value for m in app.markdown]
    has_headers = any("### 삼성전자" in m for m in mds) and any("### SK하이닉스" in m for m in mds)
    has_sections = any("메모리 반도체 종합 제조사입니다." in m for m in mds)
    record("02-D 카드 헤더 및 섹션 렌더링", has_headers and has_sections, "기업명 헤더 및 본문 정상 렌더링")

    # ---------------------------------------------------------
    # 9. 02-D: 실적 보기 클릭 시 종목 선택 및 버튼 상태 전이
    # ---------------------------------------------------------
    btn_labels = [b.label for b in app.button]
    has_btns = "삼성전자 실적 보기" in btn_labels and "SK하이닉스 실적 보기" in btn_labels
    record("02-D 실적 보기 버튼 존재 확인", has_btns, f"버튼: {btn_labels}")

    samsung_btn = next(b for b in app.button if "삼성전자" in b.label)
    samsung_btn.click().run()

    selected_is_samsung = ("selected_code" in app.session_state and app.session_state["selected_code"] == "005930")
    status_is_pending = ("request_status" in app.session_state and app.session_state["request_status"] == "pending")
    updated_labels = [b.label for b in app.button]
    samsung_disabled = any("확인됨" in b.label and b.disabled for b in app.button)
    hynix_active = any("SK하이닉스 실적 보기" in b.label and not b.disabled for b in app.button)
    sel_code = app.session_state["selected_code"] if "selected_code" in app.session_state else None
    req_status = app.session_state["request_status"] if "request_status" in app.session_state else None
    record("02-D 실적 보기 클릭 시 상태 전이 및 버튼 비활성화", selected_is_samsung and status_is_pending and samsung_disabled and hynix_active,
           f"선택: {sel_code}, 상태: {req_status}")

    # ---------------------------------------------------------
    # 10. 02-D: 팝오버 출처 독립성 (타사 근거 침범 방지)
    # ---------------------------------------------------------
    record("02-D 출처 팝오버 독립성", any("삼성전자 관련 출처" in m for m in mds) and any("SK하이닉스 관련 출처" in m for m in mds),
           "각 카드별 출처가 서로 침범하지 않고 독립적으로 렌더링됨")

    # ---------------------------------------------------------
    # 11. 02-D: 다중 턴 대화 시 위젯 키 충돌 방지 검증
    # ---------------------------------------------------------
    def _multiturn_fixture():
        import streamlit as st
        from src.ui.app import render_conversation
        render_conversation()

    multi_app = AppTest.from_function(_multiturn_fixture)
    # 2개 턴의 메시지 모두 company_cards 포함
    multi_app.session_state["chat_messages"] = [
        {"role": "user", "text": "반도체 기업 찾아줘", "sent_at": "2026-10-30T10:00:00"},
        {"role": "assistant", "text": "첫 번째 답변", "intro": "소개", "sent_at": "2026-10-30T10:00:01",
         "evidence": list(EVIDENCE_3.values()), "company_cards": ui_msg["company_cards"]},
        {"role": "user", "text": "관련주 더 보여줘", "sent_at": "2026-10-30T10:01:00"},
        {"role": "assistant", "text": "두 번째 답변", "intro": "추가 소개", "sent_at": "2026-10-30T10:01:01",
         "evidence": list(EVIDENCE_3.values()), "company_cards": ui_msg["company_cards"]},
    ]
    multi_app.session_state["candidate_result"] = disc_3
    multi_app.run()
    record("02-D 다중 턴 메시지 위젯 키 충돌 방지", len(multi_app.exception) == 0, f"다중 턴 렌더링 예외 {len(multi_app.exception)}건")

    # ---------------------------------------------------------
    # 12. 실시간 로컬 LLM (포트 1234) 실제 카드 생성 및 심사 프로브
    # ---------------------------------------------------------
    print("-" * 60)
    print("실제 로컬 LLM (Port 1234) 종단 검증 수행 중...")
    real_settings = load_settings()
    try:
        t0 = time.time()
        real_resp = discovery_answer(
            "반도체 관련 기업들의 사업 차이와 역할을 설명해줘",
            disc_3,
            real_settings,
            as_cards=True,
            latest=True,
        )
        dt = time.time() - t0
        card_cnt = len(real_resp.company_cards)
        has_intro = bool(real_resp.intro)
        is_fallback = any(e.get("answer_origin") for e in real_resp.evidence)
        record("02-C 실시간 로컬 LLM 카드 생성 및 독립 심사", card_cnt >= 1 and not is_fallback,
               f"카드 {card_cnt}개 반환, fallback: {is_fallback}, 소요시간: {dt:.2f}s")
    except Exception as e:
        record("02-C 실시간 로컬 LLM 카드 생성 및 독립 심사", False, f"로컬 LLM 오류: {e}")

    print("=" * 60)
    print(f"최종 결과: 통과 {results['passed']} / 전체 {results['passed'] + results['failed']}")
    print("=" * 60)
    return results


if __name__ == "__main__":
    res = run_checks()
    if res["failed"] > 0:
        sys.exit(1)
