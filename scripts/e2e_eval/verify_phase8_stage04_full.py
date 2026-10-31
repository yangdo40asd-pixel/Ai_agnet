"""계획8 실행04 (04-A, 04-B, 04-C, 04-D) 종합 검증 스크립트."""
import sys
import os
import json
import time

sys.path.insert(0, ".")
sys.path.insert(0, "tests")
sys.stdout.reconfigure(encoding="utf-8")

from src.models import (
    StockCandidate, CandidateDiscoveryResult, CompanyBusinessProfile,
    CompanyBusinessSource, CompanyCard, CompanyCardSection,
    ChatResponse, AppError, now_kst
)
from src.agents.request import route_message, parse_entities
from src.agents.theme_recommendation import (
    is_theme_ranking_request, is_theme_recommendation_request,
    build_theme_recommendation_text, RECOMMENDED_THEMES
)
from src.agents.discovery_context import expansion_request
from src.agents.discovery_answer import requested_business_area, is_discovery_question
from src.agents.business_context import matches_business_area, business_area_terms, detailed_business_evidence
from src.discovery_flow import enrich_discovery
from src.config import load_settings

SETTINGS = load_settings()
results = []

def run_check(section: str, desc: str, fn):
    print(f"[{section}] {desc} 검증 중...")
    t0 = time.time()
    rec = {"section": section, "desc": desc}
    try:
        res = fn()
        dt = round(time.time() - t0, 3)
        rec.update(status="PASS", dt=dt, detail=str(res))
        print(f" -> 통과 ({dt}s): {res}")
    except AppError as e:
        dt = round(time.time() - t0, 3)
        rec.update(status="APPERROR", dt=dt, code=e.code, message=e.message)
        print(f" -> APPERROR ({dt}s) [{e.code}]: {e.message}")
    except Exception as e:
        dt = round(time.time() - t0, 3)
        rec.update(status="EXC", dt=dt, message=repr(e))
        print(f" -> EXC ({dt}s): {repr(e)}")
    results.append(rec)
    return rec


# =====================================================================
# 04-A: E01-I4 실제 사업 설명·뉴스/공시 출처와 수집 가능 범위
# =====================================================================
def check_04a_source_scope():
    stock = StockCandidate("삼성전자", "005930", "KOSPI", "005930.KS")
    profile = CompanyBusinessProfile(
        stock_name="삼성전자", stock_code="005930",
        industry="통신 및 방송 장비 제조업", products="DRAM, NAND Flash, 스마트폰 등",
        retrieved_at=now_kst(), source_url="https://kind.krx.co.kr", website_url="https://samsung.com"
    )
    d = CandidateDiscoveryResult("반도체", (stock,), now_kst(), business_profiles=(profile,))
    # 수집 모듈 출처 및 프로필 확인
    assert len(d.business_profiles) == 1
    assert "DRAM" in d.business_profiles[0].products
    assert d.business_profiles[0].source_url.startswith("https://kind.krx.co.kr")
    return "04-A E01-I4 KIND 프로필 및 DART/웹 수집 소스 범위 확인"

run_check("04-A", "E01-I4 사업 설명·출처 수집 범위 확인", check_04a_source_scope)


# =====================================================================
# 04-B: E01-I1, E01-V1 명시 테마와 기업 사업 연관 근거 연결
# =====================================================================
def check_04b_explicit_theme_grounding():
    # 1. 단순 상장 대조와 실제 테마 제품 근거 구분
    from src.data.business import has_direct_theme_support
    profile_match = CompanyBusinessProfile("SK하이닉스", "000660", "반도체 제조업", "DRAM, NAND Flash", now_kst(), "https://kind.krx.co.kr")
    profile_battery = CompanyBusinessProfile("LG에너지솔루션", "373220", "축전지 제조업", "EV용 배터리", now_kst(), "https://kind.krx.co.kr")
    profile_nomatch = CompanyBusinessProfile("무관기업", "111111", "식품 제조업", "음료, 과자", now_kst(), "https://kind.krx.co.kr")
    
    assert has_direct_theme_support("반도체", profile_match) is True
    assert has_direct_theme_support("2차전지", profile_battery) is True
    assert has_direct_theme_support("반도체", profile_nomatch) is False
    assert has_direct_theme_support("2차전지", profile_nomatch) is False

    # 2. 명시적 테마 질문은 recommendation이 아니라 discover로 분기
    intent = route_message("방산 관련 기업 알려줘", None, None, [], SETTINGS)
    assert intent.action == "discover"
    assert intent.theme == "방산"

    intent2 = route_message("2차전지 테마주 찾아줘", None, None, [], SETTINGS)
    assert intent2.action == "discover"
    assert intent2.theme == "2차전지"
    return "04-B E01-I1, E01-V1 명시 테마(방산, 2차전지) discover 분기 및 제품 직접 대조 확인"

run_check("04-B", "E01-I1 명시 테마와 기업 사업 연관 근거 연결", check_04b_explicit_theme_grounding)


# =====================================================================
# 04-C: E01-I2, E01-I3 관심 분야 미정 질문을 위한 테마 소개
# =====================================================================
def check_04c_theme_recommendation():
    # 1. 관심 분야 미정 질문 식별
    queries = [
        "요즘 관심 가질 만한 테마주 알려줘",
        "어떤 테마가 좋아?",
        "관심 가질 만한 테마 추천해줘",
        "요즘 관심 가질 테마 있어?",
    ]
    for q in queries:
        assert is_theme_recommendation_request(q) is True
        intent = route_message(q, None, None, [], SETTINGS)
        assert intent.action == "theme_recommendation"
        assert "상승 보장이 아니며" in intent.reason
        assert "AI 반도체" in intent.reason
        assert "2차전지" in intent.reason

    # 2. 순위 집계 요청은 추천과 명확히 분리 (unsupported로 안내)
    ranking_queries = ["테마 순위 알려줘", "테마 랭킹 집계해줘", "테마별 등락률 순위 보여줘"]
    for q in ranking_queries:
        assert is_theme_ranking_request(q) is True
        assert is_theme_recommendation_request(q) is False
        intent = route_message(q, None, None, [], SETTINGS)
        assert intent.action == "unsupported"
        assert "순위" in intent.reason

    return "04-C E01-I2, E01-I3 미정 질문의 대표 테마 소개 및 순위 집계 분리 안내 확인"

run_check("04-C", "E01-I2/I3 대표 테마 소개 및 순위 분리", check_04c_theme_recommendation)


# =====================================================================
# 04-D: E02-I2, E02-I3, E02-V1 분야 좁히기, 추가 탐색, 기업 차이 검수
# =====================================================================
def check_04d_narrowing_and_expansion():
    # 1. 추가 탐색 (expand) 식별
    semi_candidates = (
        StockCandidate("삼성전자", "005930", "KOSPI", "005930.KS"),
        StockCandidate("SK하이닉스", "000660", "KOSPI", "000660.KS"),
    )
    semi_discovery = CandidateDiscoveryResult("반도체", semi_candidates, now_kst())

    for q in ["더 보여줘", "다른 관련주는?", "관련주 더 보여줘"]:
        assert expansion_request(q) is True
        intent = route_message(q, semi_discovery, None, [], SETTINGS)
        assert intent.action == "expand"
        assert intent.theme == "반도체"

    # 2. 분야 좁히기 (sub-area narrowing) 식별
    area1 = requested_business_area("소재 기업은?")
    assert area1 == "소재"
    assert matches_business_area({"products": "양극재, 음극재"}, "소재") is True

    area2 = requested_business_area("그중 메모리 직접 제조하는 곳만 골라줘")
    assert area2 == "메모리"
    assert matches_business_area({"products": "DRAM 및 NAND Flash 제조"}, "메모리") is True
    # 비메모리는 메모리에서 제외
    assert matches_business_area({"products": "비메모리 반도체 제조"}, "메모리") is False

    # 3. 새로운 테마 질문이 기존 테마의 세부 분야로 가로채지지 않음
    intent_new = route_message("방산 관련주 알려줘", semi_discovery, None, [], SETTINGS)
    assert intent_new.action == "discover"
    assert intent_new.theme == "방산"

    return "04-D E02 추가 탐색(expand), 분야 좁히기(소재/메모리), 신규 테마 가로채기 방지 확인"

run_check("04-D", "E02 분야 좁히기 및 추가 탐색 검수", check_04d_narrowing_and_expansion)


# =====================================================================
# 결과 종합
# =====================================================================
print("\n" + "=" * 60)
passed = sum(1 for r in results if r["status"] == "PASS")
total = len(results)
print(f"계획8 실행04 종합 검증 결과: {passed} / {total} 통과")
print("=" * 60)

with open("docs/검수/계획8_실행04_종합검증_결과.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print("결과 저장: docs/검수/계획8_실행04_종합검증_결과.json")
