"""03-A: 희소 사업 정보·부분 미확인 관계(F01-V2) 및 D10 A~F 여정 대조 검수 스크립트."""
import io
import json
from pathlib import Path
import sys
import time
from unittest.mock import patch

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import Settings
from src.models import (
    StockCandidate,
    CandidateDiscoveryResult,
    CompanyBusinessProfile,
    CompanyBusinessSource,
    AppError,
    now_kst,
)
from src.agents.discovery_answer import discovery_answer, business_evidence
from src.data.business import has_direct_theme_support, direct_theme_terms


def run_03a_audit():
    settings = Settings("test", "test", "", "")
    results = {}
    print("=" * 70)
    print("03-A 희소 사업 정보·미확인 관계(F01-V2) 및 D10 A~F 여정 감사")
    print("=" * 70)

    # -------------------------------------------------------------------------
    # 1. F01-V2: 희소 사업 정보 (KIND 업종만 있고 상세 테마 어휘가 없는 경우)
    # -------------------------------------------------------------------------
    print("\n[검수 1] 희소 사업 정보 & 테마 미확인 관계 검증")
    # 예: 테마는 'AI 반도체'인데, 기업 프로필의 주요제품은 일반 '반도체 제조'만 기재된 경우
    stock_ai = StockCandidate("가상반도체", "999001", "KOSPI", "999001.KS")
    profile_sparse = CompanyBusinessProfile(
        stock_ai.name, stock_ai.code, "반도체 제조업", "반도체 소자 제조", now_kst(), "https://kind.krx.co.kr"
    )
    # 직접 어휘 대조
    direct_match = has_direct_theme_support("AI 반도체", profile_sparse)
    matched_terms = direct_theme_terms("AI 반도체", profile_sparse)
    print(f"- 테마: 'AI 반도체' vs 등록제품: '{profile_sparse.products}'")
    print(f"- 직접 테마 지원 여부: {direct_match} (일치 어휘: {matched_terms})")
    assert not direct_match, "일반 반도체 등록만으로 AI 반도체 테마 지원으로 판정되면 안 됨"

    disc_sparse = CandidateDiscoveryResult("AI 반도체", (stock_ai,), now_kst(), business_profiles=(profile_sparse,))
    # DART 사업 절이 없고 프로필만 희소할 때, fallback 답변 관찰
    resp_sparse = discovery_answer("AI 반도체 관련 기업 알려줘", disc_sparse, settings, as_cards=True)
    intro_sparse = resp_sparse.intro
    print(f"- 생성된 도입부:\n{intro_sparse}")
    # 'AI 반도체와의 구체적인 연결까지 확인되지 않았습니다' 또는 미확인 연결이 자연스럽게 설명되는지 확인
    has_unlinked_notice = "구체적인 연결까지 확인되지 않았습니다" in intro_sparse or "확인하지 못했습니다" in intro_sparse
    print(f"- 미확인 연관 관계 적정 고지 여부: {has_unlinked_notice}")
    assert has_unlinked_notice, "희소 정보에서 구체적 연결 미확인이 안내되어야 함"

    results["f01_v2_sparse_info"] = {
        "theme": "AI 반도체",
        "products": profile_sparse.products,
        "direct_supported": direct_match,
        "intro": intro_sparse,
        "unlinked_explained": has_unlinked_notice,
    }

    # -------------------------------------------------------------------------
    # 2. F01-V2: 부분 결측 (3개 후보 중 1개 기업만 사업 정보가 완전히 누락된 경우)
    # -------------------------------------------------------------------------
    print("\n[검수 2] 부분 결측 후보 격리 및 정상 후보 보존 검증")
    s1 = StockCandidate("확인기업A", "111001", "KOSPI", "111001.KS")
    s2 = StockCandidate("결측기업B", "111002", "KOSPI", "111002.KS")
    s3 = StockCandidate("확인기업C", "111003", "KOSPI", "111003.KS")
    p1 = CompanyBusinessProfile(s1.name, s1.code, "통신장비", "스마트폰, 5G 통신장비", now_kst(), "url1")
    p3 = CompanyBusinessProfile(s3.name, s3.code, "통신장비", "광통신 부품, 네트워크 장비", now_kst(), "url3")
    # p2는 결측됨
    disc_partial = CandidateDiscoveryResult("통신", (s1, s2, s3), now_kst(), business_profiles=(p1, p3))
    resp_partial = discovery_answer("통신 관련 기업 알려줘", disc_partial, settings, as_cards=True)
    intro_partial = resp_partial.intro
    cards_partial = resp_partial.company_cards
    print(f"- 생성된 도입부:\n{intro_partial}")
    print(f"- 카드 목록: {[c.stock_name for c in cards_partial]}")

    # 결측 기업에 대한 명시적 안내가 포함되어 있는지 확인
    missing_notice = "결측기업B" in intro_partial and "확보하지 못해" in intro_partial
    print(f"- 결측 기업 정확 분리 안내: {missing_notice}")
    assert missing_notice, "결측 기업에 대해 공식 사업 정보 미확보 사실이 분리 고지되어야 함"

    # 정상 기업 2개(확인기업A, 확인기업C)에 대해서는 카드가 정상 생성되었는지 확인
    card_names = [c.stock_name for c in cards_partial]
    assert s1.name in card_names and s3.name in card_names, "정상 기업의 카드가 보존되어야 함"

    results["f01_v2_partial_missing"] = {
        "missing_stock": s2.name,
        "intro": intro_partial,
        "missing_notice": missing_notice,
        "cards": card_names,
    }

    # -------------------------------------------------------------------------
    # 3. F01-V2: 어휘 부재 != 사업 부재 원칙 검증
    # -------------------------------------------------------------------------
    print("\n[검수 3] '단어 부재 ≠ 실제 사업 부재' 표현 검증")
    # 분야 좁히기에서 근거가 없을 때 '사업이 없다'고 단정하지 않고 '근거를 확보하지 못했다'고 안내하는지 검증
    disc_semi = CandidateDiscoveryResult(
        "반도체", (s1,), now_kst(),
        business_profiles=(CompanyBusinessProfile(s1.name, s1.code, "반도체", "일반 반도체", now_kst(), "url"),)
    )
    resp_no_area = discovery_answer("그중 바이오 쪽만 알려줘", disc_semi, settings)
    text_no_area = getattr(resp_no_area, "text", getattr(resp_no_area, "intro", str(resp_no_area)))
    print(f"- 분야 미확인 시 답변:\n{text_no_area}")
    assert "근거를 확보하지 못했습니다" in text_no_area, "근거 미확보를 명시해야 함"
    assert "사업이 없습니다" not in text_no_area, "단어 부재를 실제 사업 부재로 단정하면 안 됨"

    results["f01_v2_word_absence"] = {
        "answer_text": text_no_area,
        "says_no_evidence": "근거를 확보하지 못했습니다" in text_no_area,
        "avoids_denying_business": "사업이 없습니다" not in text_no_area,
    }

    # -------------------------------------------------------------------------
    # 4. D10: A~F 전체 사용자 여정 현황 대조 감사
    # -------------------------------------------------------------------------
    print("\n[검수 4] D10: A~F 전체 사용자 여정 현황 대조 감사")
    journeys_audit = {
        "Journey_A_Theme_Discovery_Expansion": {
            "title": "A — 테마 발견과 확장",
            "prompt_path": "“관심 테마주” → “반도체/로봇” → “관련주 더 보여줘” → “서로 뭐가 달라?” → “그중 메모리 직접 제조만”",
            "status": "01/02-E 완료 (신규 시장 테마 발견 E01-I2/I3는 04 예정)",
            "implemented": [
                "반도체, 2차전지, 자동차, 바이오, 로봇, 조선 등 복수 테마 최초 탐색 완료",
                "후보 확장('관련주 더 보여줘') 시 기존 후보 보존 및 신규 3종목 독립 카드 생성 완료",
                "기업 간 차이점 질문('이 세 회사는 서로 뭐가 달라?') 시 카드 강제 없이 사업 역할 차이 직결 비교 완료",
                "분야 좁히기('그중 메모리 직접 제조하는 곳만') 시 장비사 제외 및 제조사 2사 카드 압축 완료"
            ],
            "remaining": "시장 전반에서 최신 유행 테마를 스스로 발굴하는 04 단계(E01-I2/I3)",
        },
        "Journey_B_Single_Stock_Analysis": {
            "title": "B — 한 종목 실적과 원인 질문",
            "prompt_path": "“삼성SDI 분석해줘” → “왜 영업이익이 줄었어?”",
            "status": "기반 구현 완료, 대화형 원인 해석은 05 예정",
            "implemented": [
                "단일 종목 실적 분석(매출, 영업이익, 순이익, PER, PBR) 결정적 계산 완료",
                "원가/판관비/기타영업손익 항등식 기반 비용 비중 계산(cost_structure.py) 완료",
                "영업이익 증감의 원가율/판관비율 영향 검증 및 숫자 검사 완료"
            ],
            "remaining": "단순 수치 나열을 넘어선 사업상 배경 및 쉬운 대화형 원인 설명 강화(05 A02-I3)",
        },
        "Journey_C_Comparison_And_Forecast": {
            "title": "C — 두 기업 비교와 전망",
            "prompt_path": "“LG에너지솔루션과 비교하면?” → “그럼 내년 실적은?”",
            "status": "결정적 2~6개사 비교 완료, 대화 연속성은 06 예정",
            "implemented": [
                "2~6개 기업 공통 연간 매출·영업손익·이익률 결정적 비교(verified_comparison) 완료",
                "동일 통화/회계기준/기간 검증 및 적자 전환 엄격 검증 완료",
                "과거 확정 실적과 미래 전망(컨센서스)의 엄격한 분리 검증 완료"
            ],
            "remaining": "비교 후 한 기업 평가 및 ‘그럼 내년은?’의 대화 문맥 자연스러운 승계(06 C02/E03)",
        },
        "Journey_D_Topic_Switch_And_Concept": {
            "title": "D — 주제 전환과 기술/용어 설명",
            "prompt_path": "“그건 그렇고 AI 반도체는?” → “HBM TC 본더가 구체적으로 어떤 기술이야?”",
            "status": "02-E 완료",
            "implemented": [
                "새로운 테마로의 주제 전환 시 이전 종목 문맥 간섭 차단 완료",
                "기술/용어 질의 시 카드를 강제하지 않고 DART 공시 원문 기반의 직결 개념 설명 완료"
            ],
            "remaining": "06 C03 주제 전환 시 캐시/세션 완전 분리 감사",
        },
        "Journey_E_Canvas_And_Excel": {
            "title": "E — 상세 자료 및 캔버스 연동",
            "prompt_path": "카드 [실적 보기] 클릭 → “차트/표로 보여줘” → “Excel 다운로드”",
            "status": "02-D/E 연동 완료, 캔버스 전면 확장은 08 예정",
            "implemented": [
                "카드 내 [실적 보기] 클릭 시 request_status='pending' 전이 및 중복 클릭 방지 완료",
                "8개 시트 Excel 바이트 생성 및 result_id 바인딩 완료",
                "결과 변경 시에만 Excel 캐시 갱신 완료"
            ],
            "remaining": "채팅 내 명시적 차트/비교표 요구 시 캔버스 자동 개방 조건 정리(08 U03/U04)",
        },
        "Journey_F_Summary_And_Exit": {
            "title": "F — 대화 요약과 종료",
            "prompt_path": "“지금까지 대화 내용 요약해줘” → “고마워 여기까지 할게”",
            "status": "09 예정",
            "implemented": [
                "chat_messages 최근 40개 보존 및 순차 이력 관리 완료",
                "텍스트 마크다운 및 출처 메타데이터 보존 완료"
            ],
            "remaining": "요청 시에만 전체/직전 분량별 요약 및 종료 인사 시 추가 분석 강제 없는 깔끔한 마감(09 M01/M03)",
        },
    }

    for j_key, j_val in journeys_audit.items():
        print(f"\n[{j_val['title']}]")
        print(f"  * 경로: {j_val['prompt_path']}")
        print(f"  * 현황: {j_val['status']}")
        for imp in j_val["implemented"]:
            print(f"    - [기구현] {imp}")
        print(f"    - [남은과제] {j_val['remaining']}")

    results["d10_journeys_audit"] = journeys_audit

    out_file = ROOT / "docs" / "검수" / "계획8_03A_근거경계_여정감사_2026-10-30.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[기록 완료] {out_file}")
    print("=" * 70)


if __name__ == "__main__":
    run_03a_audit()
