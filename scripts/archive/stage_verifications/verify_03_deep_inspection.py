"""실행 03 정밀 심층 검수: C01/C04/S01/S03/F01-V2 전수 실측 검증."""
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
from src.models import (
    StockCandidate,
    CandidateDiscoveryResult,
    CompanyBusinessProfile,
    AppError,
    now_kst,
)
from src.agents.discovery_answer import discovery_answer
from src.ui.chat_lifecycle import (
    start_request,
    update_request,
    complete_request,
    fail_request,
    current_request,
)
from src.diagnostics import record_failure, record_validation_failure


def run_deep_inspection():
    settings = load_settings()
    listing = load_listing()
    reports = {}

    print("=" * 70)
    print("실행 03 심층 검토 및 품질 전수 점검")
    print("=" * 70)

    # =========================================================================
    # [1] C01-I1 & C01-V1: 테마 없이 시작하는 다양한 자유 진입의 완결성
    # =========================================================================
    print("\n[검토 1] C01-I1 / C01-V1: 자유 진입 시나리오별 라우팅 및 파라미터 정합성")
    entry_scenarios = [
        ("단일 기업 실적", "삼성전자 실적 어때?", "lookup", "005930", "financials"),
        ("단일 기업 PER", "삼성전자 PER 얼마야?", "lookup", "005930", "finance"),
        ("단일 기업 뉴스", "삼성전자 최근 뉴스 알려줘", "lookup", "005930", "news"),
        ("단독 지표 개념", "PER이 뭐야?", "answer", "", "finance"),
        ("단독 원리 개념", "영업이익과 당기순이익 차이가 뭐야?", "answer", "", "all"),
        ("복수 기업 비교", "삼성전자와 SK하이닉스 비교해줘", "comparison_query", "", "all"),
        ("3개 기업 비교", "삼성전자, SK하이닉스, 한미반도체 비교해줘", "comparison_query", "", "all"),
    ]
    entry_results = []
    for label, query, exp_action, exp_code, exp_scope in entry_scenarios:
        intent = route_message(query, None, None, [], settings, listing=listing)
        matched_action = (intent.action == exp_action)
        matched_code = (intent.code == exp_code if exp_code else True)
        status = "PASS" if matched_action and matched_code else "FAIL"
        print(f"  * [{status}] {label} ('{query}') -> action: {intent.action}, code: {intent.code}, scope: {intent.scope}")
        assert matched_action, f"Action mismatch for {query}: expected {exp_action}, got {intent.action}"
        if exp_code:
            assert intent.code == exp_code, f"Code mismatch for {query}: expected {exp_code}, got {intent.code}"
        entry_results.append({
            "label": label, "query": query, "action": intent.action,
            "code": intent.code, "scope": intent.scope, "status": status
        })
    reports["c01_entry_scenarios"] = entry_results

    # =========================================================================
    # [2] C04-I2, C04-I3, C04-I4: 기간·자료 범위 분리 및 임의 대체 방지
    # =========================================================================
    print("\n[검토 2] C04-I2~I4: 질문 목적별 기간 및 자료 범위 엄격 분리")
    scope_period_cases = [
        ("매출 5년", "삼성전자 최근 5년 매출 추이", "financials", "5Y"),
        ("매출 3년", "삼성전자 3년 매출", "financials", "3Y"),
        ("주가 5년", "삼성전자 5년 주가 차트", "history", "5Y"),
        ("주가 3개월", "삼성전자 3개월 주가 차트", "history", "3M"),
        ("뉴스 1개월", "삼성전자 최근 1개월 뉴스", "news", "1M"),
    ]
    scope_results = []
    for label, query, exp_scope, exp_period in scope_period_cases:
        intent = route_message(query, None, "005930", [], settings, listing=listing)
        status = "PASS" if intent.scope == exp_scope and intent.period == exp_period else "FAIL"
        print(f"  * [{status}] {label} ('{query}') -> scope: {intent.scope}, period: {intent.period}")
        assert intent.scope == exp_scope, f"Scope mismatch: {intent.scope} != {exp_scope}"
        assert intent.period == exp_period, f"Period mismatch: {intent.period} != {exp_period}"
        scope_results.append({
            "label": label, "query": query, "scope": intent.scope,
            "period": intent.period, "status": status
        })
    reports["c04_scope_period"] = scope_results

    # =========================================================================
    # [3] S01-I1, S01-I2, S03-I1: 진단 로그 및 요청 트랜잭션 생명주기
    # =========================================================================
    print("\n[검토 3] S01 / S03: 진단 기록 및 요청 ID 생명주기 불변성")
    mock_state = {}
    # 요청 발급
    req1 = start_request(mock_state, "삼성전자 분석해줘", history=())
    assert req1.status == "idle"
    # 상태 전이
    update_request(mock_state, status="answering", result_id="temp_res_1")
    assert mock_state["chat_request"].status == "answering"
    # 완료 처리
    complete_request(mock_state, result_id="final_res_1")
    assert mock_state["chat_request"].status == "completed"
    assert mock_state["result_id"] == "final_res_1"
    # 완료 후 불변성 확인
    immutable_pass = False
    try:
        update_request(mock_state, status="answering")
    except ValueError:
        immutable_pass = True
    print(f"  * 완료 요청 불변성 보장: {immutable_pass}")
    assert immutable_pass

    # 진단 실패 기록 포맷 검증
    import logging
    log_capture = []
    class ListHandler(logging.Handler):
        def emit(self, record):
            log_capture.append(self.format(record))
    handler = ListHandler()
    logger = logging.getLogger("ai_agent.diagnostics")
    logger.addHandler(handler)
    try:
        record_failure("chat", AppError("chat_numbers", "숫자 불일치"), result_id="a"*32)
        assert any("stage=chat" in msg and "code=chat_numbers" in msg for msg in log_capture)
        print(f"  * 진단 로그 포맷 정상 출력: {log_capture[-1]}")
    finally:
        logger.removeHandler(handler)

    reports["s01_s03_lifecycle"] = {
        "immutable_verified": immutable_pass,
        "diag_log": log_capture[-1] if log_capture else "",
    }

    # =========================================================================
    # [4] F01-V2: 희소 정보, 부분 결측 및 단어 부재 != 사업 부재 원칙
    # =========================================================================
    print("\n[검토 4] F01-V2: 희소 정보·부분 결측·사업 부재 단정 방지 심층 검증")
    # 4-a. 희소 정보
    sparse_stock = StockCandidate("가상소자", "999888", "KOSPI", "999888.KS")
    sparse_prof = CompanyBusinessProfile(sparse_stock.name, sparse_stock.code, "반도체 제조업", "반도체 소자", now_kst(), "url")
    sparse_disc = CandidateDiscoveryResult("AI 반도체", (sparse_stock,), now_kst(), business_profiles=(sparse_prof,))
    sparse_resp = discovery_answer("AI 반도체 관련 기업 알려줘", sparse_disc, settings, as_cards=True)
    sparse_text = sparse_resp.intro
    card_texts = " ".join(s.text for c in sparse_resp.company_cards for s in c.sections)
    # 일반 반도체 등록을 근거 없이 'AI 칩 제조'로 왜곡하지 않고, 확인된 '반도체 소자' 범위만 서술했는지 검증
    assert "반도체 소자" in card_texts or "반도체 소자" in sparse_text or "구체적인 연결까지 확인되지 않았습니다" in sparse_text
    assert "AI 칩을 직접 제조" not in card_texts
    print("  * [PASS] AI 반도체 희소 정보에서 미확인 관계 왜곡 없이 확인된 원문 범위('반도체 소자')만 안전하게 서술함 확인")

    # 4-b. 부분 결측 격리
    s_ok1 = StockCandidate("정상A", "100001", "KOSPI", "100001.KS")
    s_mis = StockCandidate("결측B", "100002", "KOSPI", "100002.KS")
    s_ok2 = StockCandidate("정상C", "100003", "KOSPI", "100003.KS")
    p_ok1 = CompanyBusinessProfile(s_ok1.name, s_ok1.code, "소재", "이차전지 양극재", now_kst(), "url1")
    p_ok2 = CompanyBusinessProfile(s_ok2.name, s_ok2.code, "소재", "이차전지 음극재", now_kst(), "url2")
    part_disc = CandidateDiscoveryResult("2차전지 소재", (s_ok1, s_mis, s_ok2), now_kst(), business_profiles=(p_ok1, p_ok2))
    part_resp = discovery_answer("2차전지 소재 기업 알려줘", part_disc, settings, as_cards=True)
    part_intro = part_resp.intro
    part_cards = [c.stock_name for c in part_resp.company_cards]
    assert "결측B" in part_intro and "확보하지 못해" in part_intro
    assert s_ok1.name in part_cards and s_ok2.name in part_cards
    print(f"  * [PASS] 3개사 중 1개사 결측 시 결측 분리 고지 및 정상 2개사 카드 유지 확인: {part_cards}")

    # 4-c. 단어 부재 != 사업 부재
    no_area_resp = discovery_answer("그중 바이오 쪽만 알려줘", sparse_disc, settings)
    no_area_txt = getattr(no_area_resp, "text", getattr(no_area_resp, "intro", str(no_area_resp)))
    assert "근거를 확보하지 못했습니다" in no_area_txt
    assert "사업이 없습니다" not in no_area_txt
    print("  * [PASS] 단어 부재를 실제 사업 부재로 단정하지 않고 근거 미확보로 바르게 설명함 확인")

    reports["f01_v2_deep"] = {
        "sparse_text": sparse_text,
        "part_intro": part_intro,
        "part_cards": part_cards,
        "no_area_txt": no_area_txt,
    }

    out_file = ROOT / "docs" / "검수" / "계획8_03_심층전수점검_결과_2026-10-30.json"
    out_file.parent.mkdir(parents=True, exist_ok=True)
    out_file.write_text(json.dumps(reports, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"\n[기록 완료] {out_file}")
    print("=" * 70)


if __name__ == "__main__":
    run_deep_inspection()
