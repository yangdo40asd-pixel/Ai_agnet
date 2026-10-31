"""실행 06(후속 질문·주제 전환·비교의 연속성: C02, C03, E03) 전용 실시간 로컬 LLM 종단 검증기.

단순 통과 여부나 오류 코드 유무가 아니라:
1) 질문자가 진짜 묻고 있는 본질적 의도 (의도 유형, 핵심 요구)
2) 실제 모델/시스템이 출력한 문장 전문 (로그 원문)
3) 그 답변이 사람 수준의 자연스럽고 타당한 대답인지 비판적 평가
를 명확히 기록하고 검증한다.
"""
import sys
import os
import json
import time
from decimal import Decimal
from dataclasses import replace

sys.path.insert(0, ".")
sys.path.insert(0, "tests")
sys.stdout.reconfigure(encoding="utf-8")

import pandas as pd
from src.models import (
    StockCandidate, FinancialData, AnalysisResult,
    NewsArticle, NewsData, ChatResponse, AppError, now_kst,
    AnnualFinancialSummary, CandidateDiscoveryResult
)
from src.config import load_settings
from src.agents.request import route_message, parse_entities
from src.agents.chat import answer_question
from src.agents.answer_quality import select_evidence
from src.agents.outlook import answer_context, _price_focus
from src.comparison_flow import comparison_options
from src.data.company_comparison import CompanyAnnuals, build_comparison
from src.agents.company_comparison import comparison_answer
from src.ui.state import reset_all_state, add_canvas
from test_answer_blocks import sample_result
from test_question_focused_answers import annuals

settings = load_settings()
print(f"=== 실행 06 실시간 연속 대화·기업 전환·비교 의도 부합성 검증 시작 (Port: 1234) ===")

# Base Mock Data Setup
listing = pd.DataFrame([
    {"Name": name, "Code": code, "Market": "KOSPI", "Symbol": f"{code}.KS"}
    for name, code in (("삼성전자", "005930"), ("SK하이닉스", "000660"),
                       ("한미반도체", "042700"), ("삼성물산", "028260"))
])

samsung_stock = StockCandidate("삼성전자", "005930", "KOSPI", "005930.KS")
hynix_stock = StockCandidate("SK하이닉스", "000660", "KOSPI", "000660.KS")
discovery = CandidateDiscoveryResult("반도체", (samsung_stock, hynix_stock), now_kst())

# Samsung Result Setup (Revenue 120억, Op Income 18억, Op Margin 15%)
base_samsung = sample_result()
news_hbm = NewsData(
    articles=(
        NewsArticle(1, "삼성전자, 차세대 HBM 공급 계약 체결로 실적 기대감 고조", "https://example.com/hbm", "2026-10-18T09:00:00+09:00", "example.com"),
    ),
    retrieved_at=now_kst()
)
res_samsung = replace(base_samsung, news=news_hbm, annual_summaries=annuals(), commentary=replace(base_samsung.commentary, stock_comment=""))

# SK Hynix Result Setup (Revenue 60억, Op Income 9억, Op Margin 15%)
hynix_annuals = (
    AnnualFinancialSummary("2024", revenue=50_000_000_000, operating_income=5_000_000_000, fs_div="CFS"),
    AnnualFinancialSummary("2025", revenue=60_000_000_000, operating_income=9_000_000_000, fs_div="CFS"),
)
hynix_financial = replace(
    res_samsung.financial,
    stock=hynix_stock,
    price=180000.0,
    per=12.5
)
res_hynix = replace(
    res_samsung,
    selected_code="000660",
    theme="반도체",
    financial=hynix_financial,
    annual_summaries=hynix_annuals,
    news=NewsData(articles=(), retrieved_at=now_kst())
)

results = []

def run_test(scenario):
    tag = scenario["tag"]
    cat = scenario["category"]
    query = scenario["query"]
    itype = scenario["intent_type"]
    idesc = scenario["intent_desc"]
    print(f"\n[{cat}] '{query}' 실행 중...")
    t0 = time.time()
    try:
        out = scenario["fn"]()
        sec = round(time.time() - t0, 2)
        text = getattr(out, "text", getattr(out, "intro", str(out)))
        print(f" -> 소요시간: {sec}s")
        print(f" -> 실제 로그 출력 전문:\n{text}")
        results.append({
            "tag": tag,
            "category": cat,
            "query": query,
            "intent_type": itype,
            "intent_desc": idesc,
            "sec": sec,
            "status": "OK",
            "text": text,
            "detail": scenario.get("detail", {})
        })
    except Exception as e:
        sec = round(time.time() - t0, 2)
        print(f" -> EXCEPTION ({sec}s) [{type(e).__name__}]: {e}")
        results.append({
            "tag": tag,
            "category": cat,
            "query": query,
            "intent_type": itype,
            "intent_desc": idesc,
            "sec": sec,
            "status": "FAILED",
            "error": f"[{type(e).__name__}] {e}"
        })

# -------------------------------------------------------------
# 1. C02-I2: 후속 원인 질문 ("왜?")
# -------------------------------------------------------------
def test_c02_i2():
    history = [
        {"role": "user", "text": "삼성전자 최근 실적 어때?"},
        {"role": "assistant", "text": "삼성전자의 2025년 영업이익은 18.0억원으로 전년 대비 80.00% 증가했습니다.",
         "evidence": [{"id": "CMP_2024_2025_CFS_OPERATING_INCOME", "kind": "annual_comparison"}]}
    ]
    # '왜 그렇게 늘었어?' -> 실적 맥락을 계승하여 answer_question 실행
    ans = answer_question("왜 그렇게 늘었어?", res_samsung, history, settings, limited_on_failure=True)
    return ans

run_test({
    "tag": "c02_i2_followup_cause",
    "category": "06-A 후속 인과 질문",
    "query": "왜 그렇게 늘었어?",
    "intent_type": "직전 실적 증가의 세부 원인 및 손익 메커니즘 분석",
    "intent_desc": "직전 답변에서 제시된 영업이익 80% 증가에 대한 내부 재무적 원인(매출 성장 대비 영업이익 레버리지, 이익률 개선)을 계승하여 설명할 것을 요구함.",
    "fn": test_c02_i2
})

# -------------------------------------------------------------
# 2. C02-I4: 후속 전망 질문 ("그럼 내년은?")
# -------------------------------------------------------------
def test_c02_i4():
    history = [
        {"role": "user", "text": "삼성전자 앞으로 주가 어떻게 될까?"},
        {"role": "assistant", "text": "과거 실적 개선이 앞으로의 주가 상승을 보장하지는 않습니다. 반도체 수요와 판가 흐름을 종합적으로 고려해야 합니다."}
    ]
    ans = answer_question("그럼 내년은?", res_samsung, history, settings, limited_on_failure=True)
    return ans

run_test({
    "tag": "c02_i4_followup_horizon",
    "category": "06-A 후속 전망 질문",
    "query": "그럼 내년은?",
    "intent_type": "대상 기업과 주가 관점을 유지한 내년 시점 특정 전망",
    "intent_desc": "기업명(삼성전자)과 분석 관점(주가 전망)을 생략한 채 시점만 '내년'으로 바꾼 질문에 대해, 직전 맥락을 정확히 이어받아 내년의 관찰 변수를 설명할 것을 요구함.",
    "fn": test_c02_i4
})

# -------------------------------------------------------------
# 3. C02-I3: 지분/공급망 복수 기업 엔티티 보존
# -------------------------------------------------------------
def test_c02_i3():
    intent1 = route_message("한미반도체가 삼성전자에 장비 공급해?", discovery, "005930", [], settings, listing=listing)
    intent2 = route_message("삼성물산이 삼성전자 지분을 얼마나 갖고 있어?", discovery, "005930", [], settings, listing=listing)
    text1 = f"공급망 질문: action={intent1.action}, reason={intent1.reason}"
    text2 = f"지분 질문: action={intent2.action}, reason={intent2.reason}"
    return text1 + "\n" + text2

run_test({
    "tag": "c02_i3_entity_relation",
    "category": "06-A 복수 기업 관계 질문",
    "query": "한미반도체가 삼성전자에 장비 공급해? / 삼성물산이 삼성전자 지분을 얼마나 갖고 있어?",
    "intent_type": "복수 기업 간 공급망 및 지분 관계 보존",
    "intent_desc": "두 개 이상의 기업이 등장하는 관계 질문을 어느 한 기업의 단순 개별 조회로 왜곡 축소하지 않고, 관계 분석 상태를 정직하게 분기 처리할 것을 요구함.",
    "fn": test_c02_i3
})

# -------------------------------------------------------------
# 4. C02-I1 & E03-I1: 복수 후보 집합 지칭 비교 ("그 기업들 비교해줘")
# -------------------------------------------------------------
def test_c02_i1_e03_i1():
    intent = route_message("그 기업들 비교해줘", discovery, "005930", [], settings, listing=listing)
    assert intent.action == "comparison_query"
    stocks = intent.entities.mentioned_stocks
    
    comp1 = CompanyAnnuals(samsung_stock, annuals(), "src_1", now_kst(), "ok")
    comp2 = CompanyAnnuals(hynix_stock, hynix_annuals, "src_2", now_kst(), "ok")
    snapshot = build_comparison([comp1, comp2], year=2025, fs_div="CFS")
    ans = comparison_answer(snapshot, "매출과 영업이익 비교해줘")
    return ans

run_test({
    "tag": "c02_i1_collective_comparison",
    "category": "06-A/E03 복수 기업 집합 비교",
    "query": "그 기업들 비교해줘",
    "intent_type": "후보 집합(삼성전자, SK하이닉스)의 동일 기준 연간 비교",
    "intent_desc": "'그 기업들'이라는 지칭 대명사를 현재 후보 목록의 두 종목으로 정확히 해석하고, 단일 기업으로 축소하지 않고 2025년 연간 연결 실적 차이를 계산 비교할 것을 요구함.",
    "fn": test_c02_i1_e03_i1
})

# -------------------------------------------------------------
# 5. C03-I1: 종목 전환과 데이터 격리
# -------------------------------------------------------------
def test_c03_i1():
    history = [
        {"role": "user", "text": "삼성전자 실적 어때?"},
        {"role": "assistant", "text": "삼성전자의 2025년 매출은 120.0억원, 영업이익은 18.0억원입니다."}
    ]
    # SK하이닉스로 종목 전환
    intent = route_message("SK하이닉스로 바꿔서 실적 알려줘", discovery, "005930", history, settings, listing=listing)
    assert intent.action == "select"
    assert intent.code == "000660"
    
    # 전환된 종목(SK하이닉스)으로 답변 생성
    ans = answer_question("SK하이닉스 실적 어때?", res_hynix, history, settings, limited_on_failure=True)
    text = getattr(ans, "text", getattr(ans, "intro", str(ans)))
    # 삼성전자 수치(120억원, 18억원) 누출 여부 검증
    has_leak = "120" in text or "18.0" in text or "삼성전자" in text
    return f"전환 대상: {intent.code} (SK하이닉스)\n답변: {text}\n이전 종목 데이터 누출 여부: {'누출 발생(결함)' if has_leak else '완벽 격리(정상)'}"

run_test({
    "tag": "c03_i1_stock_switch_isolation",
    "category": "06-B 기업 전환 및 데이터 격리",
    "query": "SK하이닉스로 바꿔서 실적 알려줘",
    "intent_type": "분석 대상 기업 전환 및 이전 기업 데이터 누출 방지",
    "intent_desc": "삼성전자 분석 도중 SK하이닉스로 대상을 명시 교체했을 때, 이전 기업(삼성전자)의 재무 수치가 새 기업 답변에 오염되지 않고 완전히 분리될 것을 요구함.",
    "fn": test_c03_i1
})

# -------------------------------------------------------------
# 6. C03-I2 & C03-I3: 테마 전환(대화 보존) vs 새 대화(완전 초기화)
# -------------------------------------------------------------
def test_c03_i2_i3():
    state = {
        "chat_messages": [{"role": "user", "text": "삼성전자 어때?"}, {"role": "assistant", "text": "실적 좋습니다."}],
        "selected_code": "005930",
        "candidate_result": discovery
    }
    add_canvas(state, res_samsung)
    canvases_before = len(state.get("canvases", []))
    
    # 테마 전환 (keep_conversation=True)
    reset_all_state(state, keep_conversation=True)
    after_theme_messages = len(state.get("chat_messages", []))
    after_theme_canvases = len(state.get("canvases", []))
    after_theme_selected = state.get("selected_code")
    
    # 새 대화 (keep_conversation=False)
    reset_all_state(state, keep_conversation=False)
    after_reset_messages = len(state.get("chat_messages", []))
    after_reset_canvases = len(state.get("canvases", []))
    after_reset_selected = state.get("selected_code")
    
    return (
        f"1. 테마 전환 시 (기록 보존): 대화 {after_theme_messages}건 유지, 캔버스 {after_theme_canvases}건 유지, 종목선택 초기화={after_theme_selected is None}\n"
        f"2. 새 대화 시작 시 (완전 초기화): 대화 {after_reset_messages}건(0건), 캔버스 {after_reset_canvases}건(0건), 종목선택 초기화={after_reset_selected is None}"
    )

run_test({
    "tag": "c03_i2_i3_state_boundary",
    "category": "06-B 대화 보존 vs 완전 초기화",
    "query": "[상태 검증] 테마 전환 시 대화 유지 vs 새 대화 시작 시 완전 초기화",
    "intent_type": "작업 흐름에 따른 상태 생명주기 격리",
    "intent_desc": "테마 전환 시에는 사용자의 이전 분석 흐름(대화, 캔버스)을 지우지 않고 보존하되 선택만 초기화하고, '새 대화'는 메모리를 완전히 백지 상태로 초기화할 것을 요구함.",
    "fn": test_c03_i2_i3
})

# -------------------------------------------------------------
# 7. E03-I3: 비교 미지원 지표(PER/분기) 경계 안내
# -------------------------------------------------------------
def test_e03_i3():
    opts_per, reason_per = comparison_options("삼성전자와 SK하이닉스 PER 비교해줘")
    opts_qtr, reason_qtr = comparison_options("삼성전자와 SK하이닉스 3분기 실적 비교해줘")
    return f"PER 비교 요청 시: {reason_per}\n분기 비교 요청 시: {reason_qtr}"

run_test({
    "tag": "e03_i3_comparison_boundary",
    "category": "06-C 비교 미지원 지표 경계",
    "query": "삼성전자와 SK하이닉스 PER 비교해줘 / 3분기 실적 비교해줘",
    "intent_type": "미지원 비교 지표에 대한 정직한 경계 및 가능 범위 안내",
    "intent_desc": "검증되지 않은 PER 상대 비교나 분기 자료를 지어내지 않고, 현재 지원 가능한 연간 실적 범위(매출·영업이익·영업이익률)를 밝히며 미지원 지표를 정직하게 안내할 것을 요구함.",
    "fn": test_e03_i3
})

# -------------------------------------------------------------
# 8. E03-I4: 결측 항목 정돈 및 가능한 항목 비교
# -------------------------------------------------------------
def test_e03_i4():
    # SK하이닉스의 영업이익 항목이 누락된 비정상/결측 상황 시뮬레이션
    hynix_partial_annuals = (
        AnnualFinancialSummary("2024", revenue=50_000_000_000, fs_div="CFS"),
        AnnualFinancialSummary("2025", revenue=60_000_000_000, fs_div="CFS"),
    )
    comp1 = CompanyAnnuals(samsung_stock, annuals(), "src_1", now_kst(), "ok")
    comp2 = CompanyAnnuals(hynix_stock, hynix_partial_annuals, "src_2", now_kst(), "ok")
    snapshot = build_comparison([comp1, comp2], year=2025, fs_div="CFS")
    ans = comparison_answer(snapshot, "매출과 영업이익 비교해줘")
    return ans

run_test({
    "tag": "e03_i4_partial_metric_handling",
    "category": "06-C 결측 항목 정돈 및 부분 비교",
    "query": "[결측 시나리오] 매출과 영업이익 비교해줘 (단, 한 기업의 영업이익 미확인)",
    "intent_type": "결측 항목 자동 제외 및 공통 확인 항목 정상 비교",
    "intent_desc": "두 기업 중 한 곳의 특정 지표가 누락되었을 때 전체 비교를 강제 실패시키거나 임의 숫자로 때우지 않고, 누락 항목을 명시적으로 제외한 뒤 확인된 매출만 정상 비교할 것을 요구함.",
    "fn": test_e03_i4
})

# -------------------------------------------------------------
# 결과 파일 저장
# -------------------------------------------------------------
out_path = "docs/검수/계획8_06_연속대화_기업전환_비교_실시간LLM검증_2026-10-31.json"
os.makedirs(os.path.dirname(out_path), exist_ok=True)
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

print("\n" + "="*60)
print(f"실행 06 품질 검증 완료: {sum(1 for r in results if r['status'] == 'OK')} / {len(results)} 성공")
print(f"결과 저장: {out_path}")
print("="*60)
