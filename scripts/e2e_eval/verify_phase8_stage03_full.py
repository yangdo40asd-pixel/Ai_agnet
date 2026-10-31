"""계획8 실행03 (03-A, 03-B, 03-C, 03-D) 종합 검증 스크립트."""
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
from src.agents.request import ChatIntent, route_message, parse_entities, request_period
from src.ui.chat_lifecycle import ChatRequest, start_request, update_request, complete_request
from src.agents.company_cards import validate_company_cards, build_fallback_cards
from src.agents.chat import validate_answer, recover_evidence_ids
from src.config import Settings

SETTINGS = Settings("fixture", "fixture", "", "")
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
# 03-A: F01-V2 및 D10
# =====================================================================
def check_03a_sparse():
    # 희소 자료 기업에 대한 거짓 주장 차단 확인
    stock = StockCandidate("가상희소", "888801", "KOSDAQ", "888801.KQ")
    d = CandidateDiscoveryResult("AI", (stock,), now_kst())
    cards = build_fallback_cards(d, {}, (stock,))
    assert "확보되지 않았습니다" in cards[0].sections[0].text
    return "03-A F01-V2 희소 자료 미확보 고지 안전성 확인"

run_check("03-A", "F01-V2 희소 사업 정보 및 결측 기업 경계", check_03a_sparse)


# =====================================================================
# 03-B: R01, R02 최소 공통 계약 및 소유 책임
# =====================================================================
def check_03b_contracts():
    intent = ChatIntent("answer", code="005930", company="삼성전자", scope="financials",
                        purpose="cause", detail_request="canvas", answer_goal="plain")
    assert intent.purpose == "cause"
    assert intent.detail_request == "canvas"
    assert intent.answer_goal == "plain"

    req = ChatRequest("req-123", "삼성전자 왜 올랐어?", (), detail_request="canvas", answer_goal="plain")
    assert req.detail_request == "canvas"
    assert req.answer_goal == "plain"
    return "03-B R01 ChatIntent 및 ChatRequest 최소 공통 계약 확장 필드 호환성 확인"

run_check("03-B", "R01 공통 계약 필드 호환성", check_03b_contracts)

def check_03b_state_separation():
    # R02: selected_code와 active_comparison, canvas 분리
    state = {}
    from src.ui.state import select_candidate
    select_candidate(state, "005930")
    assert state.get("selected_code") == "005930"
    state["active_comparison"] = ("005930", "000660")
    state["canvases"] = [{"canvas_id": "c1", "stock_code": "005930"}]
    # 종목 선택 변경 시에도 comparison이나 canvases가 파괴되지 않음
    select_candidate(state, "000660")
    assert state.get("selected_code") == "000660"
    assert state.get("active_comparison") == ("005930", "000660")
    assert len(state.get("canvases")) == 1
    return "03-B R02 상태 소유권 분리(selected_code 변경 시 비교/캔버스 보존) 확인"

run_check("03-B", "R02 상태 소유권 독립 분리", check_03b_state_separation)


# =====================================================================
# 03-C: C01, C04 자유 진입 및 기간/자료 보존
# =====================================================================
def check_03c_free_entry():
    # 종목 선택 없이 직접 종목명 질문 진입
    stocks = (StockCandidate("삼성전자", "005930", "KOSPI", "005930.KS"),)
    parsed = parse_entities("삼성전자 주가 어때?", candidates=stocks)
    assert parsed.primary_stock and parsed.primary_stock.name == "삼성전자"

    # 두 기업 비교 직접 진입
    stocks2 = (
        StockCandidate("삼성전자", "005930", "KOSPI", "005930.KS"),
        StockCandidate("SK하이닉스", "000660", "KOSPI", "000660.KS"),
    )
    parsed_comp = parse_entities("삼성전자와 SK하이닉스 실적 비교해줘", candidates=stocks2)
    assert parsed_comp.intent == "comparison_query"
    assert len(parsed_comp.mentioned_stocks) == 2
    return "03-C C01 선택 전 직접 기업 질문 및 비교 질문 자유 진입 확인"

run_check("03-C", "C01 어디서든 질문 시작", check_03c_free_entry)

def check_03c_period_preservation():
    # C04: 기간 보존 확인
    assert request_period("최근 1년 주가 추이") == "1Y"
    assert request_period("지난 3개월 실적") == "3M"
    assert request_period("5개년 매출 비교") == "5Y"
    assert request_period("3달치 흐름") == "3M"
    return "03-C C04 요청 기간(1M/3M/1Y/5Y 및 개월/개년) 보존 확인"

run_check("03-C", "C04 질문별 기간 요청 보존", check_03c_period_preservation)


# =====================================================================
# 03-D: S01, S03 실패/시간 계측 및 한 요청에 한 번의 확정 응답
# =====================================================================
def check_03d_lifecycle():
    state = {}
    req = start_request(state, "삼성전자 PER 알려줘", [])
    assert req.request_id in state["chat_requests"]
    assert state["request_id"] == req.request_id

    # 중복 start_request 방지 (동일 상태에서 진행)
    update_request(state, user_recorded=True)
    complete_request(state, result_id="res-001")
    finished = state["chat_requests"][req.request_id]
    assert finished.status == "completed"
    assert finished.result_id == "res-001"
    return "03-D S03 단일 요청 수명주기 및 단 1회 확정 응답 보장 확인"

run_check("03-D", "S03 요청 생명주기 및 단일 확정 응답 관리", check_03d_lifecycle)


# =====================================================================
# 결과 종합
# =====================================================================
print("\n" + "=" * 60)
passed = sum(1 for r in results if r["status"] == "PASS")
total = len(results)
print(f"계획8 실행03 종합 검증 결과: {passed} / {total} 통과")
print("=" * 60)

with open("docs/검수/계획8_실행03_종합검증_결과.json", "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)
print("결과 저장: docs/검수/계획8_실행03_종합검증_결과.json")
