"""실행 03: 자유 진입(C01), 자료/기간 보존(C04), 요청 생명주기 및 중복 방지(S01/S03) 종합 검증 스크립트."""
import io
import json
from pathlib import Path
import sys
import time

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from src.config import load_settings
from src.data.stock import load_listing
from src.agents.request import route_message
from src.ui.chat_lifecycle import start_request, update_request, complete_request, fail_request
from src.models import AppError


def test_03_capabilities():
    settings = load_settings()
    listing = load_listing()
    results = {}

    print("=" * 70)
    print("실행 03 종합 검증: 자유 진입 / 자료 선택 / 요청 생명주기")
    print("=" * 70)

    # -------------------------------------------------------------------------
    # 1. C01-I1 / C01-V1: 테마 없이 임의의 시작점으로 직접 진입
    # -------------------------------------------------------------------------
    print("\n[테스트 1] 테마 없이 다양한 시작점으로 직접 진입 (C01-I1, C01-V1)")

    # 1-a. 종목명으로 바로 시작
    q_stock = "삼성전자 실적 분석해줘"
    i_stock = route_message(q_stock, None, None, [], settings, listing=listing)
    print(f"  * '{q_stock}' -> action: {i_stock.action}, company: {i_stock.company}, code: {i_stock.code}")
    assert i_stock.action == "lookup" and i_stock.code == "005930"

    # 1-b. 단독 개념 질문으로 바로 시작
    q_concept = "PER과 PBR의 차이가 뭐야?"
    i_concept = route_message(q_concept, None, None, [], settings, listing=listing)
    print(f"  * '{q_concept}' -> action: {i_concept.action}, scope: {i_concept.scope}")
    assert i_concept.action == "answer" and i_concept.scope == "finance"

    # 1-c. 두 종목 직접 비교로 바로 시작
    q_comp = "삼성전자와 SK하이닉스 비교해줘"
    i_comp = route_message(q_comp, None, None, [], settings, listing=listing)
    comp_stocks = [s.name for s in i_comp.entities.mentioned_stocks] if i_comp.entities else []
    print(f"  * '{q_comp}' -> action: {i_comp.action}, stocks: {comp_stocks}")
    assert i_comp.action == "comparison_query" and len(comp_stocks) == 2

    results["c01_direct_entry"] = {
        "stock_lookup": {"question": q_stock, "action": i_stock.action, "code": i_stock.code},
        "concept_answer": {"question": q_concept, "action": i_concept.action, "scope": i_concept.scope},
        "comparison": {"question": q_comp, "action": i_comp.action, "stocks": comp_stocks},
    }

    # -------------------------------------------------------------------------
    # 2. C04-I3 / C04-I4: 기간 및 자료 범위 보존 (매출 vs 주가 기간 분리)
    # -------------------------------------------------------------------------
    print("\n[테스트 2] 기간 및 자료 범위 분리 보존 (C04-I3, C04-I4)")

    q_sales_5y = "삼성전자 최근 5년 매출 추이"
    i_sales_5y = route_message(q_sales_5y, None, "005930", [], settings, listing=listing)
    print(f"  * '{q_sales_5y}' -> scope: {i_sales_5y.scope}, period: {i_sales_5y.period}")
    assert i_sales_5y.scope == "financials" and i_sales_5y.period == "5Y"

    q_price_3m = "삼성전자 3개월 주가 차트"
    i_price_3m = route_message(q_price_3m, None, "005930", [], settings, listing=listing)
    print(f"  * '{q_price_3m}' -> scope: {i_price_3m.scope}, period: {i_price_3m.period}")
    assert i_price_3m.scope == "history" and i_price_3m.period == "3M"

    results["c04_period_scope"] = {
        "sales_5y": {"question": q_sales_5y, "scope": i_sales_5y.scope, "period": i_sales_5y.period},
        "price_3m": {"question": q_price_3m, "scope": i_price_3m.scope, "period": i_price_3m.period},
    }

    # -------------------------------------------------------------------------
    # 3. S03-I1 / S03-I2: 요청 ID 생명주기 및 완료된 요청 불변성 검증
    # -------------------------------------------------------------------------
    print("\n[테스트 3] 요청 생명주기(ChatRequest) 및 1회 확정/불변성 검증 (S03-I1, S03-I2)")

    mock_state = {}
    # 3-a. 요청 시작
    req = start_request(mock_state, "테스트 질문", history=())
    req_id = req.request_id
    print(f"  * start_request 발급 ID: {req_id}, 초기 상태: {req.status}")
    assert req.status == "idle" and mock_state["request_id"] == req_id

    # 3-b. 상태 전이 (fetching -> answering)
    update_request(mock_state, status="answering", data_scope="financials")
    print(f"  * update_request 전이: status={mock_state['chat_request'].status}")
    assert mock_state["chat_request"].status == "answering"

    # 3-c. 완료 확정
    complete_request(mock_state, result_id="res_12345")
    print(f"  * complete_request 완료: status={mock_state['chat_request'].status}, result_id={mock_state['result_id']}")
    assert mock_state["chat_request"].status == "completed"
    assert mock_state["result_id"] == "res_12345"

    # 3-d. 완료된 요청에 대한 임의 변경 차단 확인
    blocked = False
    try:
        update_request(mock_state, status="answering")
    except ValueError as e:
        blocked = True
        print(f"  * 완료된 요청 변경 시도 차단 정상: '{e}'")
    assert blocked, "완료된 요청은 상태를 재변경할 수 없어야 함"

    results["s03_lifecycle"] = {
        "request_id": req_id,
        "final_status": mock_state["chat_request"].status,
        "completed_immutable": blocked,
    }

    out_file = ROOT / "docs" / "검수" / "계획8_03_생명주기_자유진입_검수결과_2026-10-30.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[기록 완료] {out_file}")
    print("=" * 70)


if __name__ == "__main__":
    test_03_capabilities()
