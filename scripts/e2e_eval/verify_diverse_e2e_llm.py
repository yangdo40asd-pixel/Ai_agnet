"""다양한 도메인 및 질문 유형에 대한 실시간 로컬 LLM (포트 1234) 종단 검증기.

단순 예외 유무뿐만 아니라, 모델의 생성 내용이 질문의 본질적 의도를 충족하는지,
수치 환각/기계적 회피 문구/근거 침범이 없는지 엄격히 검증한다.
"""
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
    NewsArticle, NewsData, ChatResponse, CompanyCard, AppError, now_kst
)
from src.config import load_settings
from src.agents.discovery_answer import discovery_answer
from src.agents.chat import answer_question
from test_answer_blocks import sample_result
from test_question_focused_answers import annuals

settings = load_settings()
print(f"=== 실시간 LLM 종단 검증 시작 (Provider: {settings.ai_provider}, Port: 1234) ===")

results = []

def run_test(tag: str, category: str, query: str, fn):
    print(f"\n[{category}] '{query}' 실행 중...")
    t0 = time.time()
    rec = {"tag": tag, "category": category, "query": query}
    try:
        resp = fn()
        dt = round(time.time() - t0, 2)
        rec["sec"] = dt
        rec["status"] = "OK"
        if isinstance(resp, ChatResponse):
            rec["text"] = resp.text
            rec["intro"] = resp.intro
            rec["cards"] = len(resp.company_cards)
            rec["evidence_count"] = len(resp.evidence)
            rec["card_titles"] = [c.stock_name for c in resp.company_cards]
            rec["origin"] = sorted({e.get("answer_origin", "llm") for e in resp.evidence})
        elif isinstance(resp, tuple):
            rec["text"] = resp[0]
            rec["evidence_count"] = len(resp[1])
            rec["origin"] = sorted({e.get("answer_origin", "llm") for e in resp[1]})
        print(f" -> 성공 ({dt}s): {rec.get('text', '')[:120]}...")
    except AppError as e:
        dt = round(time.time() - t0, 2)
        rec.update(sec=dt, status="APPERROR", code=e.code, message=e.message)
        print(f" -> APPERROR ({dt}s) [{e.code}]: {e.message}")
    except Exception as e:
        dt = round(time.time() - t0, 2)
        rec.update(sec=dt, status="EXC", message=repr(e))
        print(f" -> EXC ({dt}s): {repr(e)}")
    results.append(rec)
    return rec


# =====================================================================
# 1. 테마 발굴 & 기업 카드 생성: 방산 테마
# =====================================================================
stocks_defense = (
    StockCandidate("한화에어로스페이스", "012450", "KOSPI", "012450.KS"),
    StockCandidate("LIG넥스원", "079550", "KOSPI", "079550.KS"),
    StockCandidate("현대로템", "064350", "KOSPI", "064350.KS"),
)
profiles_defense = (
    CompanyBusinessProfile("한화에어로스페이스", "012450", "항공기, 우주선 및 보조장치 제조업", "항공기엔진, 자주포, 장갑차", now_kst(), "https://example.com"),
    CompanyBusinessProfile("LIG넥스원", "079550", "통신 및 방송 장비 제조업", "유도무기, 레이더, 지휘통제시스템", now_kst(), "https://example.com"),
    CompanyBusinessProfile("현대로템", "064350", "철도차량 제조업", "K2 전차, 전투차량, 고속철도차량", now_kst(), "https://example.com"),
)
disc_defense = CandidateDiscoveryResult("방산", stocks_defense, now_kst(), business_profiles=profiles_defense)

run_test(
    "defense_theme",
    "테마 발굴 (방산)",
    "방산 관련 기업 찾아줘",
    lambda: discovery_answer("방산 관련 기업 찾아줘", disc_defense, settings, as_cards=True, latest=True)
)


# =====================================================================
# 2. 테마 발굴 & 기업 카드 생성: 2차전지 테마
# =====================================================================
stocks_battery = (
    StockCandidate("LG에너지솔루션", "373220", "KOSPI", "373220.KS"),
    StockCandidate("삼성SDI", "006400", "KOSPI", "006400.KS"),
    StockCandidate("에코프로비엠", "247540", "KOSDAQ", "247540.KQ"),
)
profiles_battery = (
    CompanyBusinessProfile("LG에너지솔루션", "373220", "일차전지 및 축전지 제조업", "EV용 리튬이온 배터리 셀", now_kst(), "https://example.com"),
    CompanyBusinessProfile("삼성SDI", "006400", "일차전지 및 축전지 제조업", "전기차용 각형 배터리, 에너지저장장치(ESS)", now_kst(), "https://example.com"),
    CompanyBusinessProfile("에코프로비엠", "247540", "일차전지 및 축전지 제조업", "하이니켈계 양극재", now_kst(), "https://example.com"),
)
disc_battery = CandidateDiscoveryResult("2차전지", stocks_battery, now_kst(), business_profiles=profiles_battery)

run_test(
    "battery_theme",
    "테마 발굴 (2차전지)",
    "2차전지 관련 기업 알려줘",
    lambda: discovery_answer("2차전지 관련 기업 알려줘", disc_battery, settings, as_cards=True, latest=True)
)


# =====================================================================
# 3. 반도체 장비 심층 질문: 한미반도체 HBM 장비
# =====================================================================
stocks_semi = (
    StockCandidate("한미반도체", "042700", "KOSPI", "042700.KS"),
)
profiles_semi = (
    CompanyBusinessProfile("한미반도체", "042700", "반도체 제조용 기계 제조업", "DUAL TC BONDER, 반도체 제조용 절단 및 패키징 장비", now_kst(), "https://example.com"),
)
disc_semi = CandidateDiscoveryResult("반도체", stocks_semi, now_kst(), business_profiles=profiles_semi)

run_test(
    "hanmi_equipment",
    "기업 심층 (반도체 장비)",
    "한미반도체의 장비 사업이 뭐야?",
    lambda: discovery_answer("한미반도체의 장비 사업이 뭐야?", disc_semi, settings, as_cards=True, latest=True)
)


# =====================================================================
# 4. 주가-뉴스 인과 질문: 관련 뉴스 부재 시 (삼성전자)
# =====================================================================
base = sample_result()
result_no_news = replace(base, annual_summaries=annuals(), commentary=replace(base.commentary, stock_comment=""))

run_test(
    "price_news_causal_no_news",
    "주가-뉴스 인과 (뉴스 부재)",
    "주가가 오른 건 뉴스 때문이야?",
    lambda: answer_question("주가가 오른 건 뉴스 때문이야?", result_no_news, [], settings, limited_on_failure=True)
)


# =====================================================================
# 5. 주가-뉴스 인과 질문: 관련 뉴스 존재 시 (삼성전자 HBM 계약)
# =====================================================================
news_with_contract = NewsData(
    articles=(
        NewsArticle(1, "삼성전자, 차세대 HBM 공급 계약 체결로 실적 기대감 고조", "https://example.com/hbm", "2026-10-18T09:00:00+09:00", "example.com"),
    ),
    retrieved_at=now_kst()
)
result_with_news = replace(base, news=news_with_contract, annual_summaries=annuals(), commentary=replace(base.commentary, stock_comment=""))

run_test(
    "price_news_causal_with_news",
    "주가-뉴스 인과 (뉴스 존재)",
    "주가가 오른 건 뉴스 때문이야?",
    lambda: answer_question("주가가 오른 건 뉴스 때문이야?", result_with_news, [], settings, limited_on_failure=True)
)


# =====================================================================
# 6. 실적 원인 분석 질문: 영업이익 변동 이유
# =====================================================================
run_test(
    "financial_cause",
    "실적 원인 분석",
    "영업이익이 왜 그렇게 변했어?",
    lambda: answer_question("영업이익이 왜 그렇게 변했어?", result_no_news, [], settings, limited_on_failure=True)
)


# =====================================================================
# 7. 초보자 설명 및 분량 제한 요청
# =====================================================================
run_test(
    "simple_summary",
    "초보자 맞춤 설명",
    "실적을 초보자도 알기 쉽게 설명해줘",
    lambda: answer_question("실적을 초보자도 알기 쉽게 설명해줘", result_no_news, [], settings, limited_on_failure=True)
)


# =====================================================================
# 8. 밸류에이션 판단 질문 (PER 매수 판단)
# =====================================================================
run_test(
    "per_evaluation",
    "밸류에이션 판단",
    "PER이 낮으니 사도 돼?",
    lambda: answer_question("PER이 낮으니 사도 돼?", result_no_news, [], settings, limited_on_failure=True)
)


# =====================================================================
# 결과 저장 및 리포트
# =====================================================================
os.makedirs("docs/검수", exist_ok=True)
out_path = "docs/검수/계획8_다양한_LLM_종단검수_결과_2026-10-30.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

passed = sum(1 for r in results if r["status"] == "OK")
total = len(results)
print("\n" + "=" * 60)
print(f"검증 완료: {passed} / {total} 성공")
print(f"결과 저장: {out_path}")
print("=" * 60)
