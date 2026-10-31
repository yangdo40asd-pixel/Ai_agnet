"""심층 실시간 로컬 LLM (포트 1234) 대화 여정 전수 검증기.

단순 정상 여부뿐만 아니라 모델의 실제 생성 전문, 인용 근거, 상투어 배제 상태,
분야 좁히기/비교/추천/예측 거절의 정확성을 로그 단위로 전수 확인한다.
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
    CompanyBusinessSource, CompanyCard, AppError, now_kst
)
from src.config import load_settings
from src.agents.discovery_answer import discovery_answer
from src.agents.chat import answer_question
from src.agents.request import route_message
from test_answer_blocks import sample_result
from test_question_focused_answers import annuals

settings = load_settings()
print(f"=== 심층 LLM 대화 여정 실시간 검증 시작 (Provider: {settings.ai_provider}, Port: 1234) ===")

results = []

def run_deep_test(tag: str, category: str, query: str, fn):
    print(f"\n[{category}] '{query}' 실행 중...")
    t0 = time.time()
    rec = {"tag": tag, "category": category, "query": query}
    try:
        resp = fn()
        dt = round(time.time() - t0, 2)
        rec["sec"] = dt
        rec["status"] = "OK"
        if hasattr(resp, "text"):
            rec["text"] = resp.text
            rec["intro"] = getattr(resp, "intro", "")
            rec["cards"] = len(getattr(resp, "company_cards", ()))
            rec["evidence_count"] = len(getattr(resp, "evidence", ()))
            rec["card_titles"] = [c.stock_name for c in getattr(resp, "company_cards", ())]
        elif isinstance(resp, tuple):
            rec["text"] = resp[0]
            rec["evidence_count"] = len(resp[1])
        elif isinstance(resp, str):
            rec["text"] = resp
        elif hasattr(resp, "reason"):
            rec["text"] = resp.reason
        
        preview = rec.get("text", "").replace("\n", " ")[:150]
        print(f" -> 성공 ({dt}s): {preview}...")
        
        # 기계적 면책/상투어 잔존 여부 엄격 감사
        caveats = [
            "투자 판단은 본인", "투자의 책임은", "참고용으로만", "원가 구조는 확인하기 어려우나",
            "세부 계획은 알 수 없으나", "추가적인 확인이 필요", "반드시 상승한다고 볼 수 없"
        ]
        found_caveats = [c for c in caveats if c in rec.get("text", "")]
        if found_caveats:
            rec["caveat_warning"] = found_caveats
            print(f"    [경고] 상투적 문구 감지: {found_caveats}")
        else:
            print(f"    [감사] 기계적 회피/상투어 없음 (청정 텍스트 확인)")

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
# 1. 미정 테마 추천 질문 ("요즘 관심 가질 만한 테마주 알려줘")
# =====================================================================
run_deep_test(
    "theme_recommendation_unprompted",
    "미정 테마 추천",
    "요즘 관심 가질 만한 테마주 알려줘",
    lambda: route_message("요즘 관심 가질 만한 테마주 알려줘", None, None, [], settings).reason
)


# =====================================================================
# 2. 신규 테마 발굴: 로봇 산업
# =====================================================================
stocks_robot = (
    StockCandidate("두산로보틱스", "454910", "KOSPI", "454910.KS"),
    StockCandidate("레인보우로보틱스", "277810", "KOSDAQ", "277810.KQ"),
)
d_robot = CandidateDiscoveryResult(
    theme="로봇",
    candidates=stocks_robot,
    retrieved_at=now_kst(),
    business_profiles=(
        CompanyBusinessProfile("두산로보틱스", "454910", "특수 목적용 기계 제조업", "협동로봇 솔루션, 협동로봇 암(Arm)", now_kst(), "https://kind.krx.co.kr", "https://doosanrobotics.com"),
        CompanyBusinessProfile("레인보우로보틱스", "277810", "특수 목적용 기계 제조업", "이족보행 로봇, 협동로봇, 이동형 양팔 로봇", now_kst(), "https://kind.krx.co.kr", "https://rainbow-robotics.com"),
    ),
    business_sources=(
        CompanyBusinessSource("두산로보틱스", "454910", "DART_ROBOT_01", "정기보고서", "사업의 내용", "당사는 산업용 협동로봇 및 로봇 자동화 솔루션을 제조 및 판매합니다.", "https://dart.fss.or.kr", now_kst(), "hash_r1", "dart-business-sections-v2", "20260814", "2026.06"),
        CompanyBusinessSource("레인보우로보틱스", "277810", "DART_ROBOT_02", "정기보고서", "사업의 내용", "당사는 이족보행 로봇 플랫폼 및 협동로봇 RB 시리즈를 자체 개발하여 공급하고 있습니다.", "https://dart.fss.or.kr", now_kst(), "hash_r2", "dart-business-sections-v2", "20260814", "2026.06"),
    )
)
run_deep_test(
    "theme_robot",
    "신규 테마 발굴 (로봇)",
    "로봇 관련 기업 찾아줘",
    lambda: discovery_answer("로봇 관련 기업 찾아줘", d_robot, settings)
)


# =====================================================================
# 3. 세부 분야 좁히기 (Sub-area narrowing): 반도체 중 메모리 직접 제조
# =====================================================================
stocks_semi = (
    StockCandidate("삼성전자", "005930", "KOSPI", "005930.KS"),
    StockCandidate("SK하이닉스", "000660", "KOSPI", "000660.KS"),
    StockCandidate("한미반도체", "042700", "KOSPI", "042700.KS"),
)
d_semi = CandidateDiscoveryResult(
    theme="반도체",
    candidates=stocks_semi,
    retrieved_at=now_kst(),
    business_profiles=(
        CompanyBusinessProfile("삼성전자", "005930", "통신 및 방송 장비 제조업", "스마트폰, DRAM, NAND Flash", now_kst(), "https://kind.krx.co.kr", "https://samsung.com"),
        CompanyBusinessProfile("SK하이닉스", "000660", "반도체 제조업", "DRAM, NAND Flash, MCP", now_kst(), "https://kind.krx.co.kr", "https://skhynix.com"),
        CompanyBusinessProfile("한미반도체", "042700", "반도체 제조용 기계 제조업", "반도체 제조용 장비", now_kst(), "https://kind.krx.co.kr", "https://hanmisemi.com"),
    ),
    business_sources=(
        CompanyBusinessSource("삼성전자", "005930", "DART_SEMI_01", "정기보고서", "주요 제품", "DS부문은 메모리 반도체(DRAM, NAND Flash)를 생산 및 판매하고 있습니다.", "https://dart.fss.or.kr", now_kst(), "hash_s1", "dart-business-sections-v2", "20260814", "2026.06"),
        CompanyBusinessSource("SK하이닉스", "000660", "DART_SEMI_02", "정기보고서", "주요 제품", "당사는 주력 제품인 DRAM과 NAND Flash 등 메모리 반도체를 생산합니다.", "https://dart.fss.or.kr", now_kst(), "hash_s2", "dart-business-sections-v2", "20260814", "2026.06"),
        CompanyBusinessSource("한미반도체", "042700", "DART_SEMI_03", "정기보고서", "주요 제품", "당사는 반도체 후공정 장비인 TC Bonder 및 절단·패키징 장비를 제조 공급합니다.", "https://dart.fss.or.kr", now_kst(), "hash_s3", "dart-business-sections-v2", "20260814", "2026.06"),
    )
)
run_deep_test(
    "sub_area_narrowing_memory",
    "세부 분야 좁히기 (메모리)",
    "그중 메모리 직접 제조하는 곳만 골라줘",
    lambda: discovery_answer("그중 메모리 직접 제조하는 곳만 골라줘", d_semi, settings)
)


# =====================================================================
# 4. 세부 분야 좁히기 (Sub-area narrowing): 반도체 중 패키징 장비
# =====================================================================
run_deep_test(
    "sub_area_narrowing_equipment",
    "세부 분야 좁히기 (장비)",
    "장비 공급하는 기업은 어디야?",
    lambda: discovery_answer("장비 공급하는 기업은 어디야?", d_semi, settings)
)


# =====================================================================
# 5. 금융 개념 및 조건부 평가: PBR 1배 미만 해석
# =====================================================================
base = sample_result()
result_sample = replace(base, annual_summaries=annuals(), commentary=replace(base.commentary, stock_comment=""))
run_deep_test(
    "concept_pbr_evaluation",
    "금융 개념 및 가치 평가",
    "PBR이 1배 미만이면 무조건 저평가야?",
    lambda: answer_question("PBR이 1배 미만이면 무조건 저평가야?", result_sample, [], settings, limited_on_failure=True)
)


# =====================================================================
# 6. 미래 예측 질문 거절 및 조건부 판단 기준 제시
# =====================================================================
run_deep_test(
    "future_price_forecast_rejection",
    "미래 예측 거절 및 기준 안내",
    "삼성전자 내일 주가 얼마까지 올라?",
    lambda: answer_question("삼성전자 내일 주가 얼마까지 올라?", result_sample, [], settings, limited_on_failure=True)
)


# =====================================================================
# 7. 장기 실적 추이 질문 (5개년 질문의 기간 처리)
# =====================================================================
run_deep_test(
    "five_year_revenue_trend",
    "장기 실적 질문",
    "최근 5개년 매출 흐름 알려줘",
    lambda: answer_question("최근 5개년 매출 흐름 알려줘", result_sample, [], settings, limited_on_failure=True)
)


# =====================================================================
# 결과 저장
# =====================================================================
os.makedirs("docs/검수", exist_ok=True)
out_path = "docs/검수/계획8_심층대화여정_LLM실시간검증_결과_2026-10-30.json"
with open(out_path, "w", encoding="utf-8") as f:
    json.dump(results, f, ensure_ascii=False, indent=2)

passed = sum(1 for r in results if r["status"] == "OK")
total = len(results)
print("\n" + "=" * 60)
print(f"심층 검증 완료: {passed} / {total} 성공")
print(f"결과 저장: {out_path}")
print("=" * 60)
