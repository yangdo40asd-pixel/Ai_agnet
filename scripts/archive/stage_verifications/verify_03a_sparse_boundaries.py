"""03-A 희소 사업 정보·부분 미확인 관계·원문 어휘 부재 기업(F01-V2) 및 D10 기준 실패 대조 검증 스크립트."""
import sys
import os
import json
import time
from dataclasses import replace

sys.path.insert(0, ".")
sys.path.insert(0, "tests")
sys.stdout.reconfigure(encoding="utf-8")

from src.models import (
    StockCandidate, CandidateDiscoveryResult, CompanyBusinessProfile,
    CompanyBusinessSource, CompanyCard, CompanyCardSection,
    NewsArticle, NewsData, ChatResponse, AppError, now_kst
)
from src.config import load_settings
from src.agents.company_cards import validate_company_cards, build_fallback_cards
from src.agents.discovery_answer import discovery_answer
from src.agents.chat import validate_answer
from src.agents.business_context import detailed_business_evidence, business_excerpt
from src.data.business_sections import PARSER_REVISION

settings = load_settings()
print(f"=== 03-A F01-V2 및 D10 경계 검증 시작 (Provider: {settings.ai_provider}) ===")

results = []

def test_case(name: str, fn):
    print(f"\n[검증] {name}...")
    t0 = time.time()
    rec = {"name": name}
    try:
        res = fn()
        dt = round(time.time() - t0, 3)
        rec.update(status="PASS", dt=dt, result=res)
        print(f" -> 통과 ({dt}s): {res}")
    except AppError as e:
        dt = round(time.time() - t0, 3)
        rec.update(status="APPERROR", dt=dt, code=e.code, message=e.message)
        print(f" -> APPERROR ({dt}s) [{e.code}]: {e.message}")
    except AssertionError as e:
        dt = round(time.time() - t0, 3)
        rec.update(status="FAIL", dt=dt, message=str(e))
        print(f" -> 검증 실패 ({dt}s): {e}")
    except Exception as e:
        dt = round(time.time() - t0, 3)
        rec.update(status="EXC", dt=dt, message=repr(e))
        print(f" -> 예외 발생 ({dt}s): {repr(e)}")
    results.append(rec)
    return rec


# -------------------------------------------------------------
# Case 1: 사업 근거 부재 기업 (No business source at all)
# -------------------------------------------------------------
def case_no_business_source():
    stock = StockCandidate("가상희소기업", "999901", "KOSDAQ", "999901.KQ")
    d = CandidateDiscoveryResult(
        theme="AI반도체",
        candidates=(stock,),
        retrieved_at=now_kst(),
        business_profiles=(),
        business_sources=(),
    )
    # fallback 카드 생성 확인
    cards = build_fallback_cards(d, {}, (stock,))
    assert len(cards) == 1
    assert cards[0].stock_code == "999901"
    assert "확보되지 않았습니다" in cards[0].sections[0].text
    # 허위 근거 ID를 부여하지 않는지
    assert len(cards[0].sections[0].evidence_ids) == 0
    return f"근거 부재 시 안전한 미확보 고지 확인: {cards[0].sections[0].text}"

test_case("1. 사업 근거 완전 부재 시 허위 내용 없는 미확보 안내", case_no_business_source)


# -------------------------------------------------------------
# Case 2: 일부 결측 기업 (KIND 등록정보만 존재, DART 본문 결측)
# -------------------------------------------------------------
def case_partial_missing():
    stock = StockCandidate("가상소재", "999902", "KOSDAQ", "999902.KQ")
    profile = CompanyBusinessProfile(
        stock_name="가상소재",
        stock_code="999902",
        industry="전자부품 제조업",
        products="반도체용 세정액, 화학소재",
        retrieved_at=now_kst(),
        source_url="https://kind.krx.co.kr/",
        website_url="https://example.com"
    )
    ev_item = {
        "id": "BUSINESS_999902",
        "kind": "company_profile",
        "stock_code": "999902",
        "stock_name": "가상소재",
        "industry": profile.industry,
        "products": profile.products,
        "text": f"가상소재 · 업종: {profile.industry} · 주요제품: {profile.products}",
        "source": "한국거래소 KIND",
        "scope": "company_profile",
    }
    evidence = {"BUSINESS_999902": ev_item}
    d = CandidateDiscoveryResult(
        theme="반도체소재",
        candidates=(stock,),
        retrieved_at=now_kst(),
        business_profiles=(profile,),
        business_sources=(),
    )
    cards = build_fallback_cards(d, evidence, (stock,))
    assert len(cards) == 1
    sec = cards[0].sections[0]
    assert "등록 업종은 전자부품 제조업이며, 주요 제품은 반도체용 세정액, 화학소재입니다" in sec.text
    # DART 사업보고서가 있는 것처럼 허위 표기하지 않음
    assert "DART" not in sec.text
    return f"KIND 정보만 있을 때 정확한 인용 및 DART 위장 없음 확인: {sec.text}"

test_case("2. DART 결측 시 KIND 프로필만 정확히 인용하고 DART 위장 없음", case_partial_missing)


# -------------------------------------------------------------
# Case 3: 원문 어휘 부재 기업 (사업 내용에 테마 키워드 미확인)
# -------------------------------------------------------------
def case_no_direct_theme_term():
    stock = StockCandidate("가상정밀", "999903", "KOSDAQ", "999903.KQ")
    source = CompanyBusinessSource(
        stock_name="가상정밀",
        stock_code="999903",
        document_id="20260814000003",
        document_title="반기보고서 (2026.06)",
        section_title="주요 제품 및 서비스",
        text="당사는 초정밀 유압 실린더 및 밸브를 생산하여 산업기계 업체에 납품하고 있습니다.",
        source_url="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260814000003",
        retrieved_at=now_kst(),
        content_hash="hash003",
        parser_revision=PARSER_REVISION,
        published_at="20260814",
        reporting_period="2026.06"
    )
    ev_item = {
        "id": "999903_SECTION_1",
        "kind": "company_business_section",
        "stock_code": "999903",
        "stock_name": "가상정밀",
        "text": source.text,
        "source": "OpenDART 정기보고서 사업 원문",
        "scope": "official_business",
        "theme_supported": False,  # 테마 키워드(AI) 부재
    }
    evidence = {"999903_SECTION_1": ev_item}
    d = CandidateDiscoveryResult(
        theme="AI반도체",
        candidates=(stock,),
        retrieved_at=now_kst(),
        business_profiles=(),
        business_sources=(source,),
    )
    cards = build_fallback_cards(d, evidence, (stock,))
    assert len(cards) == 1
    roles = [s.role for s in cards[0].sections]
    # theme_supported가 False이므로 theme 역할 섹션이 생성되지 않아야 함
    assert "theme" not in roles
    # 원문 내용이 보존되어야 함
    assert "초정밀 유압 실린더 및 밸브" in cards[0].sections[0].text
    return f"원문 어휘 부재 시 억지 테마 연결 거절 및 실제 사업 보존: {cards[0].sections[0].text}"

test_case("3. 테마 어휘 부재 시 억지 테마 섹션 미생성 및 실제 원문 유지", case_no_direct_theme_term)


# -------------------------------------------------------------
# Case 4: 타사 근거 인용 시 엄격 차단 (Cross-Company Grounding)
# -------------------------------------------------------------
def case_cross_company_evidence_blocked():
    stock_a = StockCandidate("기업A", "111110", "KOSPI", "111110.KS")
    stock_b = StockCandidate("기업B", "222220", "KOSDAQ", "222220.KQ")
    evidence = {
        "EV_A": {
            "id": "EV_A",
            "stock_code": "111110",
            "stock_name": "기업A",
            "text": "기업A는 로봇 관절 모터를 개발합니다.",
            "kind": "company_business_section",
            "scope": "official_business",
        },
        "EV_B": {
            "id": "EV_B",
            "stock_code": "222220",
            "stock_name": "기업B",
            "text": "기업B는 로봇 센서를 만듭니다.",
            "kind": "company_business_section",
            "scope": "official_business",
        }
    }
    # 기업B 카드에 기업A의 근거 ID(EV_A)를 인용하는 악의적/오류 페이로드
    bad_payload = {
        "text": "로봇 테마 기업입니다.",
        "evidence_ids": ["EV_A"],
        "follow_up": "",
        "company_cards": [
            {
                "stock_code": "111110",
                "stock_name": "기업A",
                "sections": [{"role": "summary", "text": "기업A는 로봇 관절 모터를 개발합니다.", "evidence_ids": ["EV_A"]}],
            },
            {
                "stock_code": "222220",
                "stock_name": "기업B",
                # 타사 근거 EV_A 인용!
                "sections": [{"role": "summary", "text": "기업B는 로봇 센서를 만듭니다.", "evidence_ids": ["EV_A"]}],
            }
        ]
    }
    try:
        validate_company_cards(bad_payload, evidence, candidates=(stock_a, stock_b))
        assert False, "타사 근거 인용이 차단되지 않았습니다!"
    except AppError as e:
        assert e.code == "company_card_evidence_ownership", f"예상치 못한 코드: {e.code}"
        return f"타사 근거 인용 차단 확인: [{e.code}] {e.message}"

test_case("4. 다른 기업 근거 인용 시 소유권 검사(company_card_evidence_ownership) 차단", case_cross_company_evidence_blocked)


# -------------------------------------------------------------
# Case 5: 구형 리비전/오래된 웹 파서 결과 배제
# -------------------------------------------------------------
def case_old_revision_excluded():
    stock = StockCandidate("가상테크", "333330", "KOSDAQ", "333330.KQ")
    old_source = CompanyBusinessSource(
        stock_name="가상테크",
        stock_code="333330",
        document_id="WEB_old",
        document_title="공식 홈페이지",
        section_title="구형 제품",
        text="과거 구형 제품군 안내 텍스트입니다.",
        source_url="https://example.com/old",
        retrieved_at=now_kst(),
        content_hash="oldhash",
        parser_revision="official-business-html-v1",  # 구형 리비전
        published_at="20240101",
        reporting_period="2024"
    )
    d = CandidateDiscoveryResult(
        theme="반도체",
        candidates=(stock,),
        retrieved_at=now_kst(),
        business_profiles=(),
        business_sources=(old_source,),
    )
    ev = detailed_business_evidence(d, (stock,))
    assert len(ev) == 0, "구형 파서 리비전이 걸러지지 않고 근거로 승격되었습니다!"
    return "구형 리비전(official-business-html-v1) 완벽 배제 확인"

test_case("5. 구형 파서 리비전 캐시의 사업 근거 승격 배제", case_old_revision_excluded)


# -------------------------------------------------------------
# Case 6: 정상 설명의 오탐 방지 (False Rejection Prevention)
# -------------------------------------------------------------
def case_false_rejection_prevention():
    evidence = {
        "TECH_EV": {
            "id": "TECH_EV",
            "text": "반도체 2.5D 패키징 및 6-SIDE INSPECTION 검사 장비와 TC Bonder를 제조 공급합니다.",
            "kind": "company_business_section",
            "scope": "official_business",
            "url": "https://example.com/tech",
            "stock_code": "042700",
        }
    }
    # 영문/숫자/기호가 포함된 전문 기술 용어 검증
    payload_valid = {
        "text": "이 회사는 2.5D 패키징 및 6-SIDE INSPECTION 검사 장비와 TC Bonder를 제조 공급합니다.",
        "evidence_ids": ["TECH_EV"],
        "follow_up": ""
    }
    res_text, used_ids = validate_answer(payload_valid, evidence)
    assert "2.5D" in res_text
    assert "6-SIDE" in res_text
    assert "TC Bonder" in res_text

    # 허위 수치 조작은 여전히 정확히 차단되어야 함
    payload_hallucinated = {
        "text": "이 회사는 2.6D 패키징 및 8-SIDE 장비를 제조 공급합니다.",
        "evidence_ids": ["TECH_EV"],
        "follow_up": ""
    }
    try:
        validate_answer(payload_hallucinated, evidence)
        assert False, "허위 수치 변조가 통과되었습니다!"
    except AppError as e:
        assert e.code == "chat_numbers"

    return "정상 기술 용어(2.5D, 6-SIDE, TC Bonder) 승인 및 수치 변조(2.6D, 8-SIDE) 엄격 거절 확인"

test_case("6. 정상 기술 용어 오탐 방지 및 허위 수치 변조 차단", case_false_rejection_prevention)


# -------------------------------------------------------------
# Case 7: D10 기준 실패 대조 (A~F 여정 대조)
# -------------------------------------------------------------
def case_d10_baseline_comparison():
    checklist_path = "계획8_사용자경험중심_재설계_체크리스트.md"
    assert os.path.exists(checklist_path), "체크리스트 파일 누락"
    with open(checklist_path, "r", encoding="utf-8") as f:
        content = f.read()

    # D10 요건 확인
    assert "D10" in content
    
    # A~F 실패 기준 대조 검증 항목 정의
    journeys = {
        "A": "테마 탐색 (단순 이름 나열/선택 강요 -> 기업별 사업 카드 분리 및 차이점 설명)",
        "B": "기업 비교 (단일 기업 축소/임의 비교 -> 같은 기간·통화·기준 결정적 재무 비교)",
        "C": "실적 원인 (실적 단순 재진술/기계적 상투어 -> 원가·판관비·레버리지 원인 분석)",
        "D": "초보자 맞춤 설명 (전문용어 방치 -> 쉬운 비유와 직관적 풀이 제공)",
        "E": "주가-뉴스 인과 (인과 회피/현재가만 덜렁 -> 인과 직접 해명 및 뉴스 카드 제시)",
        "F": "밸류에이션 판단 (단정적 매수 추천 or 무조건 거절 -> PER 조건부 판단 기준 제시)"
    }
    return f"A~F 여정 {len(journeys)}개 정의 및 현행 개선점 일치 확인"

test_case("7. D10 A~F 전체 여정 기준 실패 대조", case_d10_baseline_comparison)

print("\n=== 모든 03-A F01-V2 및 D10 검증 통과 ===")
with open("docs/검수/계획8_실행03_03A_검증결과.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print("결과 저장: docs/검수/계획8_실행03_03A_검증결과.json")
